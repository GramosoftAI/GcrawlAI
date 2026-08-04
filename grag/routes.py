import os
import uuid
import logging
import json
from typing import List, Union, Optional
from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect, Header
from pydantic import BaseModel, HttpUrl
import redis.asyncio as aioredis
from api.services.queue_manager import queue_manager

logger = logging.getLogger(__name__)

router = APIRouter()

# Redis connection
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
redis_client_async = aioredis.from_url(REDIS_URL, decode_responses=True, socket_timeout=None)

class ScrapeLinksRequest(BaseModel):
    urls: Union[str, List[str]]

@router.post("/scrape-links")
async def scrape_links(payload: ScrapeLinksRequest):
    # 1. Parse URLs (accept both list of strings or comma-separated string)
    raw_urls = []
    if isinstance(payload.urls, list):
        raw_urls = payload.urls
    elif isinstance(payload.urls, str):
        raw_urls = [u.strip() for u in payload.urls.split(",") if u.strip()]
        
    # Clean and validate URLs
    clean_urls = []
    for u in raw_urls:
        if not u.startswith("http://") and not u.startswith("https://"):
            u = "https://" + u
        clean_urls.append(u)
        
    if not clean_urls:
        raise HTTPException(status_code=400, detail="No valid URLs provided")
        
    gsearch_id = uuid.uuid4().hex
    
    # Insert initial placeholder row so GET requests don't 404
    from api.core.database import get_pooled_connection
    try:
        with get_pooled_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    "INSERT INTO gsearch_results (gsearch_id, json_content, status) VALUES (%s, '[]'::jsonb, 'processing')",
                    (gsearch_id,)
                )
            conn.commit()
    except Exception as db_err:
        logger.error(f"Failed to insert initial row for {gsearch_id}: {db_err}")
    
    # 2. Trigger task (Celery or local background ThreadPool fallback)
    use_celery = os.getenv("USE_CELERY", "false").lower() == "true"
    if not use_celery:
        try:
            from web_crawler.crawler.celery_config import celery_app
            insp = celery_app.control.inspect(timeout=0.2)
            if insp and insp.ping():
                use_celery = True
        except Exception:
            pass

    if use_celery:
        try:
            from web_crawler.crawler.celery_tasks import scrape_links_task
            scrape_links_task.delay(gsearch_id, clean_urls)
            logger.info(f"Offloaded grag scrape task {gsearch_id} to Celery")
        except Exception as celery_err:
            logger.error(f"Failed to submit Celery task, falling back to local pool: {celery_err}")
            use_celery = False

    if not use_celery:
        from web_crawler.crawler.celery_tasks import local_scrape_links_worker
        queue_manager.thread_pool.submit(local_scrape_links_worker, gsearch_id, clean_urls)
        logger.info(f"Started grag scrape task {gsearch_id} in local background thread pool")
        
    return {
        "status_code": 200,
        "status": "success",
        "gsearch_id": gsearch_id,
        "urls_submitted": len(clean_urls),
        "websocket_url": f"/api/v1/grag/ws/{gsearch_id}"
    }

@router.websocket("/ws/{gsearch_id}")
async def grag_ws(websocket: WebSocket, gsearch_id: str):
    await websocket.accept()
    logger.info(f"WebSocket client connected to Grag updates: {gsearch_id}")
    
    # Subscribe to live updates on Redis channel grag:{gsearch_id}
    pubsub = redis_client_async.pubsub()
    await pubsub.subscribe(f"grag:{gsearch_id}")
    
    try:
        async for message in pubsub.listen():
            if message["type"] != "message":
                continue
            data = message["data"]
            await websocket.send_text(data)
            
            # If final completed event is received, close the WebSocket connection
            try:
                payload = json.loads(data)
                if payload.get("type") == "gsearch_completed":
                    logger.info(f"Grag scraping task {gsearch_id} completed. Closing WebSocket.")
                    break
            except Exception:
                pass
    except (WebSocketDisconnect, Exception) as e:
        logger.info(f"WebSocket client disconnected/closed for gsearch_id {gsearch_id}: {e}")
    finally:
        await pubsub.unsubscribe(f"grag:{gsearch_id}")
        await pubsub.close()

@router.get("/scrape-links/results/{gsearch_id}")
async def get_scrape_links_results(gsearch_id: str):

    from api.core.database import get_pooled_connection
    import json
    
    try:
        with get_pooled_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    "SELECT status, json_content FROM gsearch_results WHERE gsearch_id = %s",
                    (gsearch_id,)
                )
                row = cursor.fetchone()
                
                if not row:
                    raise HTTPException(status_code=404, detail="Job results not found")
                    
                status = row[0]
                json_content = row[1]
                if isinstance(json_content, str):
                    json_content = json.loads(json_content)
                    
                return {
                    "status_code": 200,
                    "status": status,
                    "gsearch_id": gsearch_id,
                    "data": json_content
                }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching results for grag job {gsearch_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))
