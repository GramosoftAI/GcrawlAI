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
        
    all_results = []
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
        "Accept": "application/json",
        "Accept-Language": "en-US,en;q=0.9",
    }
    
    # Attempt to fetch multiple pages if needed (each page typically has 10-20 results)
    # We'll try up to 10 pages to reach the limit
    for pageno in range(1, 11):
        try:
            response = httpx.get(
                url,
                params={"q": query, "format": "json", "pageno": pageno},
                headers=headers,
                timeout=15.0
            )
            if response.status_code == 200:
                page_data = response.json()
                page_results = page_data.get("results", [])
                
                if not page_results:
                    break
                    
                all_results.extend(page_results)
                
                # Stop if we hit the limit early
                if len(all_results) >= limit:
                    break
            else:
                logger.warning(f"SearXNG pageno {pageno} failed with status {response.status_code}")
                break
        except Exception as e:
            logger.warning(f"SearXNG engine at {url} page {pageno} failed: {e}")
            break
            
    # Format to match internal structure
    formatted = []
    for r in all_results[:limit]:
        formatted.append({
            "url": r.get("url"),
            "title": r.get("title"),
            "description": r.get("content", "")
        })
    return formatted

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

