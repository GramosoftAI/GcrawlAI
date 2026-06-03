"""
Search Engine Routes

Provides an API endpoint for searching using the unified search router.
Supports multiple search engines with fallback logic.
"""

import logging
from typing import List, Dict, Optional

from fastapi import APIRouter, HTTPException, Request, Depends, Header
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, Field

from web_crawler.search.search_engine import execute_search_router
import uuid
import pytz
from datetime import datetime
from api.core.database import get_pooled_connection

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/search", tags=["Crawler"])


class SearchRequest(BaseModel):
    query: str = Field(..., min_length=1, description="Search query text")
    limit: int = Field(10, ge=1,le = 100, description="Number of results to return")


class SearchResult(BaseModel):
    position: Optional[int] = None
    url: Optional[str] = None
    title: Optional[str] = None
    description: Optional[str] = None


class SearchResponse(BaseModel):
    query: str
    limit: int
    count: int
    results: List[SearchResult]


from fastapi import Header

@router.post("", response_model=SearchResponse)
async def search(
    search_req: SearchRequest,
    request: Request,
    authorization: Optional[str] = Header(None, description="Authorization: Bearer <token>"),
    x_api_key: Optional[str] = Header(None, alias="X-API-Key", description="API key for client access")
) -> SearchResponse:
    """Perform a search using engine fallback configured in `web_crawler.search_engine`."""
    recaptcha_header = request.headers.get("recaptcha_token") or request.headers.get("recaptcha-token")
    api_key_header = x_api_key or request.headers.get("x-api-key") or request.headers.get("api_key") or request.headers.get("api-key") or request.headers.get("apikey")
    from api.core.security import validate_recaptcha_or_jwt, check_plan_limits_and_get_details, increment_used_requests
    from api.services.queue_manager import queue_manager
    
    user_id = validate_recaptcha_or_jwt(
        auth_header=authorization,
        recaptcha_header=recaptcha_header,
        api_key_header=api_key_header
    )
    
    plan_type, concurrency_limit = check_plan_limits_and_get_details(user_id)
    
    # Extract client IP with fallback logic
    # 1. Check X-Forwarded-For (standard for multi-hop proxies)
    # 2. Check X-Real-IP (common for Nginx/single-proxy)
    # 3. Fallback to direct client host
    client_ip = request.headers.get("x-forwarded-for")
    if client_ip:
        client_ip = client_ip.split(",")[0].strip()
    else:
        client_ip = request.headers.get("x-real-ip") or (request.client.host if request.client else None)

    search_id = uuid.uuid4().hex
    ist = pytz.timezone("Asia/Kolkata")
    created_at = datetime.now(ist)

    with get_pooled_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO search_jobs
            (search_id, query, "limit", created_at, updated_at, user_id)
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (search_id, search_req.query, search_req.limit, created_at, created_at, user_id)
        )
        conn.commit()

    try:
        # Pass to the global Priority Queue instead of executing directly
        results: List[Dict[str, str]] = await queue_manager.submit_task(
            user_id=user_id,
            plan_type=plan_type,
            user_limit=concurrency_limit,
            func=execute_search_router,
            query=search_req.query,
            limit=search_req.limit,
            ip=client_ip
        )
        # On success, deduct/increment used credit
        increment_used_requests(user_id)
    except Exception as exc:
        logger.exception("Search route failed")
        from api.core.database import log_activity
        try:
            log_activity(user_id, "/SEARCH", search_req.query, "FAILED", job_id=search_id if 'search_id' in locals() else None)
            with get_pooled_connection() as conn:
                cur = conn.cursor()
                cur.execute(
                    """
                    INSERT INTO search_errors (search_id, query, error_source, reason, created_at, user_id)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                    (search_id, search_req.query, "SEARCH", str(exc), datetime.now(ist), user_id)
                )
                conn.commit()
        except Exception:
            pass
            
        try:
            from api.core.config_setup import load_config
            import os
            from api.services.email_service import EmailService
            
            admin_email = os.getenv("ADMIN_EMAIL")
            if admin_email:
                config = load_config()
                smtp_config = config.get("email", {})
                email_service = EmailService(smtp_config)
                
                email_service.send_report_issue_email(
                    to_email=admin_email,
                    url_affected=f"SEARCH: {search_req.query}",
                    issue_related_to=["Search Engine Failure", "All Search Tiers Exhausted"],
                    explanation=f"The search engine completely failed for the query.\n\nError Details: {str(exc)}"
                )
        except Exception as e:
            logger.error(f"Failed to send alert email for search failure: {e}")
            
        raise HTTPException(status_code=500, detail=f"Search failed: {exc}") from exc

    from api.core.database import log_activity
    try:
        log_activity(user_id, "/SEARCH", search_req.query, "COMPLETED", job_id=search_id)
    except Exception:
        pass

    try:
        with get_pooled_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                "UPDATE search_jobs SET updated_at = %s WHERE search_id = %s",
                (datetime.now(ist), search_id)
            )
            conn.commit()
    except Exception as e:
        logger.error(f"Failed to update search_jobs for {search_id}: {e}")

    summary = {
        "query": search_req.query,
        "limit": search_req.limit,
        "count": len(results),
        "results": results,
    }
    from api.core.database import upsert_job_result
    upsert_job_result(search_id, summary, str(user_id) if user_id else None)

    return SearchResponse(
        query=search_req.query,
        limit=search_req.limit,
        count=len(results),
        results=[SearchResult(**item) for item in results],
    )
