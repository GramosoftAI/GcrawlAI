from fastapi import APIRouter, Request, Query, WebSocket, WebSocketDisconnect
from typing import Optional
from psycopg2.extras import DictCursor
import logging
import asyncio
from api.core.database import get_pooled_connection

router = APIRouter(prefix="/admin", tags=["Admin Overall Logs"])
logger = logging.getLogger(__name__)

# Basic active connections manager for WebSockets
class ConnectionManager:
    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: dict):
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception as e:
                logger.error(f"Error sending ws message: {e}")
                
manager = ConnectionManager()

@router.get("/overall-logs")
async def get_overall_logs(
    request: Request,
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=100)
):
    """
    Get overall logs combining activity, bandwidth, and error details.
    """
    offset = (page - 1) * limit
    try:
        with get_pooled_connection() as conn:
            with conn.cursor(cursor_factory=DictCursor) as cursor:
                # Query combining activity_logs as base, with proxy_bandwidth_usage and error tables
                query = """
                    SELECT 
                        a.job_id,
                        a.user_id,
                        a.endpoint,
                        a.url as target,
                        a.status,
                        a.time_taken,
                        a.created_at,
                        COALESCE(ce.reason, ce.blocked_message, se.reason, se.blocked_message) as error_reason,
                        p.nodemaven,
                        p.evomi_premium,
                        p.evomi_core
                    FROM activity_logs a
                    LEFT JOIN proxy_bandwidth_usage p ON a.job_id = p.job_id
                    LEFT JOIN crawl_errors ce ON a.job_id = ce.crawl_id
                    LEFT JOIN search_errors se ON a.job_id = se.search_id
                    ORDER BY a.created_at DESC
                    LIMIT %s OFFSET %s
                """
                cursor.execute(query, (limit, offset))
                rows = cursor.fetchall()
                
                # Get total count for pagination
                cursor.execute("SELECT COUNT(*) FROM activity_logs")
                total_count = cursor.fetchone()[0]

                logs = []
                for row in rows:
                    total_bytes = (row['nodemaven'] or 0) + (row['evomi_premium'] or 0) + (row['evomi_core'] or 0)
                    bandwidth_used_mb = round(total_bytes / (1024 * 1024), 2) if total_bytes > 0 else 0
                    
                    logs.append({
                        "job_id": row['job_id'],
                        "user_id": row['user_id'],
                        "endpoint": row['endpoint'],
                        "target": row['target'],
                        "status": row['status'],
                        "error_reason": row['error_reason'],
                        "bandwidth_used_mb": bandwidth_used_mb,
                        "time_taken": row['time_taken'],
                        "created_at": row['created_at'].isoformat() if row['created_at'] else None
                    })

                return {
                    "status": "success",
                    "data": logs,
                    "pagination": {
                        "page": page,
                        "limit": limit,
                        "total": total_count,
                        "total_pages": (total_count + limit - 1) // limit
                    }
                }
    except Exception as e:
        logger.error(f"Error fetching overall logs: {e}", exc_info=True)
        return {"status": "error", "message": "Failed to fetch overall logs"}

@router.websocket("/ws/overall-logs")
async def websocket_overall_logs(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            # We don't expect messages from client, but we need to keep connection open
            data = await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        manager.disconnect(websocket)

async def notify_overall_log(job_data: dict):
    """
    Helper function to be called from job completion areas to notify websocket clients.
    job_data should match the structure of a log item.
    """
    await manager.broadcast(job_data)
