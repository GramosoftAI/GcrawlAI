#!/usr/bin/env python3
"""
Admin Auto Robots CRUD Management Routes
"""
import logging
from typing import Optional, List
from datetime import datetime
from fastapi import APIRouter, HTTPException, Depends, Query
from psycopg2.extras import RealDictCursor
import json

from api.core.database import get_pooled_connection
from api.routes.admin_users_routes import verify_admin_user
from api.models.payloads import (
    CreateAutoRobotRequest,
    UpdateAutoRobotRequest,
    AutoRobotResponse,
    AutoRobotListResponse,
    StandardResponse
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/admin/auto-robots", tags=["Admin Auto Robots Management"])

@router.post("", response_model=AutoRobotResponse)
async def create_auto_robot(
    payload: CreateAutoRobotRequest,
    _: bool = Depends(verify_admin_user)
):
    """Create a new auto robot configuration"""
    try:
        with get_pooled_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                # Convert dynamic fields list to json string
                dynamic_fields_json = json.dumps([df.dict() for df in payload.dynamic_fields])
                sample_schema_json = json.dumps(payload.sample_schema)
                
                cursor.execute(
                    """
                    INSERT INTO auto_robots (
                        title, category, target_platform, status, sample_url, description, dynamic_fields, sample_schema
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb)
                    RETURNING id, title, category, target_platform, status, sample_url, description, dynamic_fields, sample_schema, created_at, updated_at
                    """,
                    (
                        payload.title,
                        payload.category,
                        payload.target_platform,
                        payload.status,
                        payload.sample_url,
                        payload.description,
                        dynamic_fields_json,
                        sample_schema_json
                    )
                )
                row = cursor.fetchone()
                conn.commit()
                
                if row:
                    row['created_at'] = row['created_at'].isoformat() if isinstance(row['created_at'], datetime) else str(row['created_at'])
                    if row['updated_at']:
                        row['updated_at'] = row['updated_at'].isoformat() if isinstance(row['updated_at'], datetime) else str(row['updated_at'])
                    return row
                raise HTTPException(status_code=500, detail="Failed to create auto robot")
    except Exception as e:
        logger.error(f"Error creating auto robot: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@router.get("", response_model=AutoRobotListResponse)
async def list_auto_robots(
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=100),
    search: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    _: bool = Depends(verify_admin_user)
):
    """Retrieve all auto robots with search and filtering"""
    offset = (page - 1) * limit
    try:
        with get_pooled_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                query_where = []
                query_params = []
                
                if search:
                    query_where.append("(title ILIKE %s OR target_platform ILIKE %s OR description ILIKE %s)")
                    search_param = f"%{search}%"
                    query_params.extend([search_param, search_param, search_param])
                if category:
                    query_where.append("category = %s")
                    query_params.append(category)
                if status:
                    query_where.append("status = %s")
                    query_params.append(status)
                    
                where_clause = " WHERE " + " AND ".join(query_where) if query_where else ""
                
                # Fetch total count
                count_sql = f"SELECT COUNT(*) FROM auto_robots{where_clause}"
                cursor.execute(count_sql, query_params)
                total_count = cursor.fetchone()['count']
                
                # Fetch paginated records
                data_sql = f"""
                    SELECT id, title, category, target_platform, status, sample_url, description, dynamic_fields, sample_schema, created_at, updated_at
                    FROM auto_robots
                    {where_clause}
                    ORDER BY id DESC
                    LIMIT %s OFFSET %s
                """
                cursor.execute(data_sql, query_params + [limit, offset])
                rows = cursor.fetchall()
                
                data = []
                for row in rows:
                    row['created_at'] = row['created_at'].isoformat() if isinstance(row['created_at'], datetime) else str(row['created_at'])
                    if row['updated_at']:
                        row['updated_at'] = row['updated_at'].isoformat() if isinstance(row['updated_at'], datetime) else str(row['updated_at'])
                    data.append(row)
                    
                return {
                    "status_code": 200,
                    "status": "success",
                    "data": data,
                    "total_count": total_count
                }
    except Exception as e:
        logger.error(f"Error listing auto robots: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/{id}", response_model=AutoRobotResponse)
async def get_auto_robot(
    id: int,
    _: bool = Depends(verify_admin_user)
):
    """Retrieve details of a single auto robot"""
    try:
        with get_pooled_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT id, title, category, target_platform, status, sample_url, description, dynamic_fields, sample_schema, created_at, updated_at
                    FROM auto_robots
                    WHERE id = %s
                    """,
                    (id,)
                )
                row = cursor.fetchone()
                
                if not row:
                    raise HTTPException(status_code=404, detail="Auto Robot not found")
                    
                row['created_at'] = row['created_at'].isoformat() if isinstance(row['created_at'], datetime) else str(row['created_at'])
                if row['updated_at']:
                    row['updated_at'] = row['updated_at'].isoformat() if isinstance(row['updated_at'], datetime) else str(row['updated_at'])
                return row
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching auto robot {id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@router.put("/{id}", response_model=AutoRobotResponse)
async def update_auto_robot(
    id: int,
    payload: UpdateAutoRobotRequest,
    _: bool = Depends(verify_admin_user)
):
    """Update field values of an existing auto robot"""
    try:
        with get_pooled_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute("SELECT id FROM auto_robots WHERE id = %s", (id,))
                if not cursor.fetchone():
                    raise HTTPException(status_code=404, detail="Auto Robot not found")
                
                update_fields = []
                update_params = []
                
                if payload.title is not None:
                    update_fields.append("title = %s")
                    update_params.append(payload.title)
                if payload.category is not None:
                    update_fields.append("category = %s")
                    update_params.append(payload.category)
                if payload.target_platform is not None:
                    update_fields.append("target_platform = %s")
                    update_params.append(payload.target_platform)
                if payload.status is not None:
                    update_fields.append("status = %s")
                    update_params.append(payload.status)
                if payload.sample_url is not None:
                    update_fields.append("sample_url = %s")
                    update_params.append(payload.sample_url)
                if payload.description is not None:
                    update_fields.append("description = %s")
                    update_params.append(payload.description)
                if payload.dynamic_fields is not None:
                    update_fields.append("dynamic_fields = %s::jsonb")
                    update_params.append(json.dumps([df.dict() for df in payload.dynamic_fields]))
                if payload.sample_schema is not None:
                    update_fields.append("sample_schema = %s::jsonb")
                    update_params.append(json.dumps(payload.sample_schema))
                    
                if not update_fields:
                    cursor.execute(
                        """
                        SELECT id, title, category, target_platform, status, sample_url, description, dynamic_fields, sample_schema, created_at, updated_at
                        FROM auto_robots WHERE id = %s
                        """,
                        (id,)
                    )
                    row = cursor.fetchone()
                    row['created_at'] = row['created_at'].isoformat() if isinstance(row['created_at'], datetime) else str(row['created_at'])
                    if row['updated_at']:
                        row['updated_at'] = row['updated_at'].isoformat() if isinstance(row['updated_at'], datetime) else str(row['updated_at'])
                    return row
                    
                update_fields.append("updated_at = %s")
                update_params.append(datetime.now())
                
                update_sql = f"""
                    UPDATE auto_robots
                    SET {", ".join(update_fields)}
                    WHERE id = %s
                    RETURNING id, title, category, target_platform, status, sample_url, description, dynamic_fields, sample_schema, created_at, updated_at
                """
                cursor.execute(update_sql, update_params + [id])
                row = cursor.fetchone()
                conn.commit()
                
                if row:
                    row['created_at'] = row['created_at'].isoformat() if isinstance(row['created_at'], datetime) else str(row['created_at'])
                    if row['updated_at']:
                        row['updated_at'] = row['updated_at'].isoformat() if isinstance(row['updated_at'], datetime) else str(row['updated_at'])
                    return row
                raise HTTPException(status_code=500, detail="Failed to update auto robot")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating auto robot {id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/{id}", response_model=StandardResponse)
async def delete_auto_robot(
    id: int,
    _: bool = Depends(verify_admin_user)
):
    """Delete an auto robot configuration"""
    try:
        with get_pooled_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT id FROM auto_robots WHERE id = %s", (id,))
                if not cursor.fetchone():
                    raise HTTPException(status_code=404, detail="Auto Robot not found")
                    
                cursor.execute("DELETE FROM auto_robots WHERE id = %s", (id,))
                conn.commit()
                return {
                    "status_code": 200,
                    "status": "success",
                    "success": True,
                    "message": "Auto Robot deleted successfully"
                }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting auto robot {id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
