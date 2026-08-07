#!/usr/bin/env python3
import logging
from typing import Optional, List
from fastapi import APIRouter, HTTPException, Depends, Query
from psycopg2.extras import RealDictCursor
from api.core.database import get_db_connection
from api.routes.admin_users_routes import verify_admin_user
from api.models.payloads import ReportIssueListResponse, ReportIssueAdminResponse

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/admin/reported-issues", tags=["Admin Reported Issues"])

@router.get("", response_model=ReportIssueListResponse)
async def get_admin_reported_issues(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    status: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    _: bool = Depends(verify_admin_user)
):
    """
    Fetch all reported issues for the admin panel with search, filtering and pagination.
    """
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        
        offset = (page - 1) * page_size
        
        query = "SELECT * FROM reported_issues"
        count_query = "SELECT COUNT(*) as total FROM reported_issues"
        
        where_clauses = []
        params = []
        
        if status:
            where_clauses.append("status = %s")
            params.append(status)
            
        if category:
            where_clauses.append("%s = ANY(issue_related_to)")
            params.append(category)
            
        if search:
            where_clauses.append("(url_affected ILIKE %s OR email ILIKE %s OR explanation ILIKE %s)")
            search_param = f"%{search}%"
            params.extend([search_param, search_param, search_param])
            
        if where_clauses:
            where_str = " WHERE " + " AND ".join(where_clauses)
            query += where_str
            count_query += where_str
            
        query += " ORDER BY created_at DESC LIMIT %s OFFSET %s"
        
        cursor.execute(count_query, params)
        total_count = cursor.fetchone()['total']
        
        cursor.execute(query, params + [page_size, offset])
        rows = cursor.fetchall()
        
        issues_list = []
        for row in rows:
            created_at_str = row['created_at'].isoformat() if row['created_at'] else ""
            issues_list.append(ReportIssueAdminResponse(
                id=row['id'],
                formatted_id=f"iss_{row['id']}",
                url_affected=row['url_affected'],
                issue_related_to=row['issue_related_to'] or [],
                explanation=row['explanation'],
                email=row['email'],
                user_id=row['user_id'],
                status=row['status'],
                created_at=created_at_str
            ))
            
        return ReportIssueListResponse(
            success=True,
            data=issues_list,
            total_count=total_count
        )
        
    except Exception as e:
        logger.error(f"Error fetching admin reported issues: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to fetch reported issues: {str(e)}")
    finally:
        if conn:
            conn.close()
