"""
Search Engine Routes

Provides an API endpoint for searching using the unified search router.
Supports multiple search engines with fallback logic.
"""

import logging
from typing import List, Dict, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from web_crawler.search.search_engine import execute_search_router

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/search", tags=["Search"])


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


@router.post("", response_model=SearchResponse)
async def search(search_req: SearchRequest, request: Request) -> SearchResponse:
    """Perform a search using engine fallback configured in `web_crawler.search_engine`."""
    # Extract client IP with fallback logic
    # 1. Check X-Forwarded-For (standard for multi-hop proxies)
    # 2. Check X-Real-IP (common for Nginx/single-proxy)
    # 3. Fallback to direct client host
    client_ip = request.headers.get("x-forwarded-for")
    if client_ip:
        client_ip = client_ip.split(",")[0].strip()
    else:
        client_ip = request.headers.get("x-real-ip") or (request.client.host if request.client else None)

    try:
        results: List[Dict[str, str]] = await execute_search_router(search_req.query, search_req.limit, client_ip)
    except Exception as exc:
        logger.exception("Search route failed")
        raise HTTPException(status_code=500, detail=f"Search failed: {exc}") from exc

    return SearchResponse(
        query=search_req.query,
        limit=search_req.limit,
        count=len(results),
        results=[SearchResult(**item) for item in results],
    )
