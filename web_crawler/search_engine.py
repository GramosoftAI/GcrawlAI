import os
import httpx
import logging
from ddgs import DDGS
from typing import List, Dict, Any

logger = logging.getLogger(__name__)

def searxng_search(query: str, limit: int) -> List[Dict[str, str]]:
    url = os.getenv("SEARXNG_ENDPOINT")
    if not url:
        return []
        
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
            "Accept": "application/json",
            "Accept-Language": "en-US,en;q=0.9",
        }
        response = httpx.get(
            url,
            params={"q": query, "format": "json"},
            headers=headers,
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
        logger.warning(f"SearXNG engine at {url} failed: {e}")
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
    1. SearXNG (Primary)
    2. DuckDuckGo (Fallback)
    """
    # Double the limit to allow for deduplication / filtering
    search_limit = max(10, limit * 2)
    
    # 1. Primary: SearXNG
    if os.getenv("SEARXNG_ENDPOINT"):
        logger.info(f"🔍 [SEARCH] Attempting search with primary engine: SearXNG")
        results = searxng_search(query, search_limit)
        if results:
            logger.info(f"✅ [SEARCH] SearXNG search successful. Found results.")
            return filter_and_deduplicate(results, limit)
            
    # 2. Fallback: DuckDuckGo
    logger.info(f"🦆 [SEARCH] Attempting search with fallback engine: DuckDuckGo (DDGS)")
    results = ddg_search(query, search_limit)
    if results:
        logger.info(f"✅ [SEARCH] DuckDuckGo search successful. Found results.")
    return filter_and_deduplicate(results, limit)



def filter_and_deduplicate(results: List[Dict[str, str]], limit: int) -> List[Dict[str, str]]:
    seen_urls = set()
    filtered = []
    
    for r in results:
        url = r.get("url")
        if not url or url in seen_urls:
            continue
            
        seen_urls.add(url)
        r["position"] = len(filtered) + 1
        filtered.append(r)
        
        if len(filtered) >= limit:
            break
            
    return filtered

