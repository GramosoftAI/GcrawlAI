#!/usr/bin/env python3
import logging
from typing import Optional
from fastapi import APIRouter, HTTPException, Depends
from psycopg2.extras import RealDictCursor
from api.routes.api_key_routes import get_db_connection
from api.routes.admin_users_routes import verify_admin_user
from api.models.payloads import CustomRequestListResponse, CustomRequestAdminResponse

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/admin/custom-requests", tags=["Admin Custom Requests"])

@router.get("", response_model=CustomRequestListResponse)
async def get_admin_custom_requests(
    page: int = 1,
    page_size: int = 50,
    status: Optional[str] = None,
    _: bool = Depends(verify_admin_user)
):
    """
    Fetch all custom scraping requests for the admin panel.
    """
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        
        offset = (page - 1) * page_size
        
        query = "SELECT * FROM custom_requests"
        count_query = "SELECT COUNT(*) as total FROM custom_requests"
        
        params = []
        if status:
            query += " WHERE status = %s"
            count_query += " WHERE status = %s"
            params.append(status)
            
        query += " ORDER BY created_at DESC LIMIT %s OFFSET %s"
        params.extend([page_size, offset])
        
        cursor.execute(count_query, params[:-2] if status else [])
        total_count = cursor.fetchone()['total']
        
        cursor.execute(query, params)
        rows = cursor.fetchall()
        
        requests_list = []
        for row in rows:
            created_at_str = row['created_at'].isoformat() if row['created_at'] else ""
            requests_list.append(CustomRequestAdminResponse(
                id=row['id'],
                formatted_id=f"CR-{row['id']:03d}",
                full_name=row['full_name'],
                work_email=row['work_email'],
                company=row['company'],
                expected_volume=row['expected_volume'],
                request_type=row['request_type'],
                target_websites=row['target_websites'],
                description=row['description'],
                status=row['status'],
                created_at=created_at_str
            ))
            
        return CustomRequestListResponse(
            success=True,
            data=requests_list,
            total_count=total_count
        )
        
    except Exception as e:
        logger.error(f"Error fetching admin custom requests: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to fetch custom requests: {str(e)}")
    finally:
        if conn:
            conn.close()
