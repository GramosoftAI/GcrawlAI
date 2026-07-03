import json
import logging
from datetime import datetime
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from websockets.exceptions import ConnectionClosed
import redis.asyncio as aioredis
from api.core.database import get_pooled_connection

logger = logging.getLogger(__name__)

router = APIRouter()
redis_client_async = aioredis.from_url("redis://localhost:6379/0", decode_responses=True, socket_timeout=None)

@router.websocket("/crawl/{crawl_id}")
async def crawl_ws(websocket: WebSocket, crawl_id: str):
    await websocket.accept()

    # Safe defaults
    crawl_mode = "all"
    found_completion_event = False
    replayed_event_types: set = set()

    # 1. Check DB for job info and historical events
    try:
        with get_pooled_connection() as conn:
            cur = conn.cursor()
            
            cur.execute("SELECT crawl_mode, updated_at FROM crawl_jobs WHERE crawl_id = %s", (crawl_id,))
            job_row = cur.fetchone()
            crawl_mode = job_row[0] if job_row else "all"
            is_finished_db = job_row[1] is not None if job_row and job_row[1] else False
    
            cur.close()
            
            if is_finished_db and not found_completion_event:
                await websocket.send_json({
                    "type": "crawl_completed",
                    "summary": {"status": "completed", "note": "Replayed from background status"}
                })
                found_completion_event = True
    

            if found_completion_event:
                logger.info(f"Replayed finished crawl for {crawl_id}. Closing.")
                await websocket.close()
                return

    except (WebSocketDisconnect, ConnectionClosed):
        logger.info(f"WebSocket disconnected during DB replay: {crawl_id}")
        return
    except Exception as e:
        logger.error(f"Error replaying historical events: {e}")

    # 2. Subscribe for live updates
    pubsub = redis_client_async.pubsub()
    await pubsub.subscribe(f"crawl:{crawl_id}")

    try:
        async for message in pubsub.listen():
            if message["type"] != "message":
                continue

            data = message["data"]

            try:
                msg_type = json.loads(data).get("type")
                if msg_type and msg_type in replayed_event_types:
                    logger.debug(f"Skipping already-replayed event type '{msg_type}' for crawl_id={crawl_id}")
                    replayed_event_types.discard(msg_type)
                    continue
            except Exception:
                pass

            await websocket.send_text(data)

            try:
                payload = json.loads(data)
                event_type = payload.get("type")
                
                if event_type:
                    if event_type == "crawl_completed":
                        try:
                            summary_data = payload.get("summary", {})
                            links_file_path = payload.get("links_file_path") or summary_data.get("links_file_path")
                            summary_file_path = payload.get("summary_file_path") or summary_data.get("summary_file_path")

                            with get_pooled_connection() as conn_job:
                                cur_job = conn_job.cursor()
                                cur_job.execute(
                                    "UPDATE crawl_jobs SET updated_at = %s WHERE crawl_id = %s",
                                    (datetime.now(), crawl_id)
                                )
                                conn_job.commit()
                                cur_job.close()
                        except Exception as e:
                            logger.error(f"Error updating completion timestamp: {e}")



                if event_type == "crawl_completed":
                    logger.info(f"Closing WebSocket for crawl_id={crawl_id}")
                    break

            except Exception as e:
                logger.error(f"Error persisting event: {e}")
                continue

    except (WebSocketDisconnect, ConnectionClosed):
        logger.info(f"WebSocket disconnected: {crawl_id}")
    except Exception as e:
        logger.info(f"PubSub stream closed for crawl_id={crawl_id}: {e}")

    finally:
        await pubsub.unsubscribe(f"crawl:{crawl_id}")
        await pubsub.aclose()
        try:
            await websocket.close()
        except Exception:
            pass 
        logger.info(f"WebSocket closed for crawl_id={crawl_id}")
