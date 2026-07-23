#!/usr/bin/env python3
"""
Admin Error Logs Management Routes
"""
import logging
import json
from datetime import datetime
from typing import Optional, List, Dict, Any
from fastapi import APIRouter, HTTPException, Depends, Query, status, WebSocket, WebSocketDisconnect
from psycopg2.extras import RealDictCursor
from api.routes.api_key_routes import get_db_connection
from api.routes.admin_users_routes import verify_admin_user
from api.models.payloads import StandardResponse
from pydantic import BaseModel

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/admin", tags=["Admin User Management"])

class ErrorLogItem(BaseModel):
    id: int
    log_id: str
    timestamp: str
    source_tool: str
    target_domain: str
    error_type: str
    severity: str
    proxy_ip: Optional[str] = None
    user_id: Optional[str] = None

class ErrorLogListResponse(BaseModel):
    success: bool
    logs: List[ErrorLogItem]
    total_count: int

class ErrorLogDetailResponse(BaseModel):
    success: bool
    id: int
    log_id: str
    timestamp: str
    source_tool: str
    target_domain: str
    error_type: str
    severity: str
    proxy_ip: Optional[str] = None
    error_details: Optional[str] = None
    request_params: Optional[Dict[str, Any]] = None
    stack_trace: Optional[str] = None
    user_id: Optional[str] = None
    user_name: Optional[str] = None

@router.get("/error-logs", response_model=ErrorLogListResponse)
async def get_admin_error_logs(
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=100),
    search: Optional[str] = Query(None),
    severity: Optional[str] = Query(None),
    error_type: Optional[str] = Query(None),
    source_tool: Optional[str] = Query(None),
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    _: bool = Depends(verify_admin_user)
):
    """
    Retrieve paginated and filtered admin error logs.
    Allows filtering by timestamp date range (start_date, end_date).
    """
    offset = (page - 1) * limit
    
    # 1. Parse date filters if provided
    parsed_start = None
    if start_date:
        try:
            parsed_start = datetime.strptime(start_date, "%Y-%m-%d")
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid start_date format. Use YYYY-MM-DD.")
            
    parsed_end = None
    if end_date:
        try:
            # Set time to end of day to include the entire day
            parsed_end = datetime.strptime(f"{end_date} 23:59:59", "%Y-%m-%d %H:%M:%S")
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid end_date format. Use YYYY-MM-DD.")

    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        
        # Build dynamic query conditions
        conditions = []
        params = []
        
        if search:
            conditions.append("(target_domain ILIKE %s OR error_details ILIKE %s OR log_id ILIKE %s)")
            search_param = f"%{search}%"
            params.extend([search_param, search_param, search_param])
            
        if severity:
            conditions.append("severity = %s")
            params.append(severity)
            
        if error_type:
            conditions.append("error_type = %s")
            params.append(error_type)
            
        if source_tool:
            conditions.append("source_tool = %s")
            params.append(source_tool)

        if parsed_start:
            conditions.append("timestamp >= %s")
            params.append(parsed_start)
            
        if parsed_end:
            conditions.append("timestamp <= %s")
            params.append(parsed_end)
            
        where_clause = ""
        if conditions:
            where_clause = "WHERE " + " AND ".join(conditions)
            
        # Count total logs matching filters
        count_query = f"SELECT COUNT(*) FROM admin_error_logs {where_clause}"
        cursor.execute(count_query, tuple(params))
        total_count = cursor.fetchone()['count']
        
        # Fetch matching logs
        select_query = f"""
            SELECT id, log_id, timestamp, source_tool, target_domain, error_type, severity, proxy_ip, user_id
            FROM admin_error_logs
            {where_clause}
            ORDER BY timestamp DESC, id DESC
            LIMIT %s OFFSET %s
        """
        select_params = params + [limit, offset]
        cursor.execute(select_query, tuple(select_params))
        rows = cursor.fetchall()
        cursor.close()
        
        logs = []
        for row in rows:
            ts = row['timestamp']
            ts_str = ts.isoformat() if isinstance(ts, datetime) else str(ts)
            
            logs.append(ErrorLogItem(
                id=row['id'],
                log_id=row['log_id'],
                timestamp=ts_str,
                source_tool=row['source_tool'],
                target_domain=row['target_domain'],
                error_type=row['error_type'],
                severity=row['severity'],
                proxy_ip=row['proxy_ip'],
                user_id=row['user_id']
            ))
            
        return ErrorLogListResponse(
            success=True,
            logs=logs,
            total_count=total_count
        )
        
    except Exception as e:
        logger.error(f"Error fetching admin error logs: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to fetch error logs: {str(e)}")
    finally:
        if conn:
            conn.close()

@router.get("/error-logs/{log_id_or_pk}", response_model=ErrorLogDetailResponse)
async def get_admin_error_log_detail(
    log_id_or_pk: str,
    _: bool = Depends(verify_admin_user)
):
    """
    Retrieve full details for a specific admin error log by its PK id or log_id (UUID/hash).
    """
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        
        # Determine if log_id_or_pk is integer PK or log_id string
        is_pk = False
        try:
            pk_val = int(log_id_or_pk)
            is_pk = True
        except ValueError:
            pass
            
        if is_pk:
            cursor.execute("""
                SELECT el.id, el.log_id, el.timestamp, el.source_tool, el.target_domain, el.error_type, el.severity, el.proxy_ip, el.error_details, el.request_params, el.stack_trace, el.user_id, u.name AS user_name
                FROM admin_error_logs el
                LEFT JOIN users u ON el.user_id = u.user_id::text
                WHERE el.id = %s
            """, (pk_val,))
        else:
            cursor.execute("""
                SELECT el.id, el.log_id, el.timestamp, el.source_tool, el.target_domain, el.error_type, el.severity, el.proxy_ip, el.error_details, el.request_params, el.stack_trace, el.user_id, u.name AS user_name
                FROM admin_error_logs el
                LEFT JOIN users u ON el.user_id = u.user_id::text
                WHERE el.log_id = %s
                LIMIT 1
            """, (log_id_or_pk,))
            
        row = cursor.fetchone()
        cursor.close()
        
        if not row:
            raise HTTPException(status_code=404, detail="Error log not found")
            
        ts = row['timestamp']
        ts_str = ts.isoformat() if isinstance(ts, datetime) else str(ts)
        
        # Parse request_params
        request_params_dict = None
        if row['request_params']:
            if isinstance(row['request_params'], dict):
                request_params_dict = row['request_params']
            elif isinstance(row['request_params'], str):
                try:
                    request_params_dict = json.loads(row['request_params'])
                except Exception:
                    request_params_dict = {"raw": row['request_params']}
                    
        return ErrorLogDetailResponse(
            success=True,
            id=row['id'],
            log_id=row['log_id'],
            timestamp=ts_str,
            source_tool=row['source_tool'],
            target_domain=row['target_domain'],
            error_type=row['error_type'],
            severity=row['severity'],
            proxy_ip=row['proxy_ip'],
            error_details=row['error_details'],
            request_params=request_params_dict,
            stack_trace=row['stack_trace'],
            user_id=row['user_id'],
            user_name=row['user_name']
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching admin error log detail for {log_id_or_pk}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to fetch error log detail: {str(e)}")
    finally:
        if conn:
            conn.close()

@router.delete("/error-logs", response_model=StandardResponse)
async def clear_all_admin_error_logs(
    _: bool = Depends(verify_admin_user)
):
    """
    Truncate/clear all error logs from the system database.
    """
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("TRUNCATE TABLE admin_error_logs")
        conn.commit()
        cursor.close()
        return StandardResponse(
            success=True,
            message="All admin error logs successfully cleared."
        )
    except Exception as e:
        logger.error(f"Error clearing admin error logs: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to clear error logs: {str(e)}")
    finally:
        if conn:
            conn.close()

@router.delete("/error-logs/{log_pk}", response_model=StandardResponse)
async def delete_admin_error_log(
    log_pk: int,
    _: bool = Depends(verify_admin_user)
):
    """
    Permanently delete a specific error log entry from the system database.
    """
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM admin_error_logs WHERE id = %s", (log_pk,))
        conn.commit()
        
        # Verify deletion affected rows
        row_count = cursor.rowcount
        cursor.close()
        
        if row_count == 0:
            raise HTTPException(status_code=404, detail="Error log not found or already deleted.")
            
        return StandardResponse(
            success=True,
            message=f"Error log with id {log_pk} successfully deleted."
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting admin error log id={log_pk}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to delete error log: {str(e)}")
    finally:
        if conn:
            conn.close()

@router.websocket("/error-logs")
async def ws_error_logs(websocket: WebSocket):
    """
    WebSocket endpoint to retrieve paginated/filtered error logs in real-time.
    """
    await websocket.accept()
    try:
        while True:
            data_str = await websocket.receive_text()
            try:
                params = json.loads(data_str)
            except Exception:
                await websocket.send_json({"success": False, "error": "Invalid JSON format"})
                continue
                
            page = int(params.get("page", 1))
            limit = int(params.get("limit", 20))
            search = params.get("search")
            severity = params.get("severity")
            error_type = params.get("error_type")
            source_tool = params.get("source_tool")
            
            offset = (page - 1) * limit
            conn = None
            try:
                conn = get_db_connection()
                cursor = conn.cursor(cursor_factory=RealDictCursor)
                
                conditions = []
                sql_params = []
                
                if search:
                    conditions.append("(target_domain ILIKE %s OR error_details ILIKE %s OR log_id ILIKE %s)")
                    search_param = f"%{search}%"
                    sql_params.extend([search_param, search_param, search_param])
                    
                if severity:
                    conditions.append("severity = %s")
                    sql_params.append(severity)
                    
                if error_type:
                    conditions.append("error_type = %s")
                    sql_params.append(error_type)
                    
                if source_tool:
                    conditions.append("source_tool = %s")
                    sql_params.append(source_tool)
                    
                where_clause = ""
                if conditions:
                    where_clause = "WHERE " + " AND ".join(conditions)
                    
                count_query = f"SELECT COUNT(*) FROM admin_error_logs {where_clause}"
                cursor.execute(count_query, tuple(sql_params))
                total_count = cursor.fetchone()['count']
                
                select_query = f"""
                    SELECT id, log_id, timestamp, source_tool, target_domain, error_type, severity, proxy_ip, user_id
                    FROM admin_error_logs
                    {where_clause}
                    ORDER BY timestamp DESC, id DESC
                    LIMIT %s OFFSET %s
                """
                select_params = sql_params + [limit, offset]
                cursor.execute(select_query, tuple(select_params))
                rows = cursor.fetchall()
                cursor.close()
                
                logs = []
                for row in rows:
                    ts = row['timestamp']
                    ts_str = ts.isoformat() if isinstance(ts, datetime) else str(ts)
                    logs.append({
                        "id": row['id'],
                        "log_id": row['log_id'],
                        "timestamp": ts_str,
                        "source_tool": row['source_tool'],
                        "target_domain": row['target_domain'],
                        "error_type": row['error_type'],
                        "severity": row['severity'],
                        "proxy_ip": row['proxy_ip'],
                        "user_id": row['user_id']
                    })
                    
                await websocket.send_json({
                    "success": True,
                    "logs": logs,
                    "total_count": total_count
                })
            except Exception as db_err:
                logger.error(f"WS error logs DB fetch error: {db_err}")
                await websocket.send_json({"success": False, "error": str(db_err)})
            finally:
                if conn:
                    conn.close()
    except WebSocketDisconnect:
        logger.info("Admin error logs WebSocket disconnected.")
    except Exception as ws_err:
        logger.error(f"Admin error logs WebSocket error: {ws_err}")
