import os
import httpx
import logging
from ddgs import DDGS
from typing import List, Dict, Any

logger = logging.getLogger(__name__)

def proprietary_search(query: str, limit: int) -> List[Dict[str, str]]:
    url = os.getenv("FIRE_ENGINE_BETA_URL")
    if not url:
        return []
    
    try:
        response = httpx.post(
            f"{url}/search",
            json={"query": query, "limit": limit},
            timeout=10.0
        )
        if response.status_code == 200:
            return response.json().get("results", [])
    except Exception as e:
        logger.warning(f"Proprietary engine failed: {e}")
    return []

def searxng_search(query: str, limit: int) -> List[Dict[str, str]]:
    url = os.getenv("SEARXNG_ENDPOINT")
    if not url:
        return []
        
    try:
        response = httpx.get(
            url,
            params={"q": query, "format": "json"},
            timeout=10.0
        )
        if response.status_code == 200:
            results = response.json().get("results", [])
            # Format to match duckduckgo: url, title, body
            formatted = []
            for r in results[:limit]:
                formatted.append({
                    "url": r.get("url"),
                    "title": r.get("title"),
                    "description": r.get("content", "")
                })
            return formatted
    except Exception as e:
        logger.warning(f"SearXNG engine failed: {e}")
    return []

def ddg_search(query: str, limit: int) -> List[Dict[str, str]]:
    try:
        ddgs = DDGS()
        # Text returns list of dict with 'href', 'title', 'body'
        results = list(ddgs.text(query, max_results=limit))
        
        formatted = []
        for r in results:
            formatted.append({
                "url": r.get("href"),
                "title": r.get("title"),
                "description": r.get("body")
            })
        return formatted
    except Exception as e:
        logger.warning(f"DuckDuckGo engine failed: {e}")
    return []

def execute_search_router(query: str, limit: int) -> List[Dict[str, str]]:
    """
    Implements a fallback router for search engines.
    1. Proprietary Search Engine
    2. SearXNG
    3. DuckDuckGo Fallback
    """
    # Double the limit to allow for deduplication / filtering
    search_limit = 10
    
    # 1. First Priority: Proprietary Search Engine
    if os.getenv("FIRE_ENGINE_BETA_URL"):
        results = proprietary_search(query, search_limit)
        if results:
            return filter_and_deduplicate(results, limit)
            
    # 2. Second Priority: SearXNG
    if os.getenv("SEARXNG_ENDPOINT"):
        results = searxng_search(query, search_limit)
        if results:
            return filter_and_deduplicate(results, limit)
            
    # 3. Fallback: DuckDuckGo
    results = ddg_search(query, search_limit)
    return filter_and_deduplicate(results, limit)

def filter_and_deduplicate(results: List[Dict[str, str]], limit: int) -> List[Dict[str, str]]:
    seen_urls = set()
    filtered = []
    
    for r in results:
        url = r.get("url")
        if not url or url in seen_urls:
            continue
            
        seen_urls.add(url)
        filtered.append(r)
        
        if len(filtered) >= limit:
            break
            
    return filtered
