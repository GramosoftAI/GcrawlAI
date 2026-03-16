"""
Search Engine Routes

Provides an API endpoint for searching using the unified search router.
Supports multiple search engines with fallback logic.
"""

import logging
from typing import List, Dict, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from web_crawler.search_engine import execute_search_router

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
def search(request: SearchRequest) -> SearchResponse:
    """Perform a search using engine fallback configured in `web_crawler.search_engine`."""
    try:
        results: List[Dict[str, str]] = execute_search_router(request.query, request.limit)
    except Exception as exc:
        logger.exception("Search route failed")
        raise HTTPException(status_code=500, detail=f"Search failed: {exc}") from exc

    return SearchResponse(
        query=request.query,
        limit=request.limit,
        count=len(results),
        results=[SearchResult(**item) for item in results],
    )
