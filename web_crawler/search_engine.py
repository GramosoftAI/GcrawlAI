import os
import httpx
import logging
from ddgs import DDGS
from typing import List, Dict, Any

logger = logging.getLogger(__name__)

# Global cache to avoid hitting GeoIP API on every single search
_LOCALE_DATA = None

def get_detected_locale() -> dict:
    """Detects locale, city, and region based on IP."""
    global _LOCALE_DATA
    if _LOCALE_DATA:
        return _LOCALE_DATA
    
    try:
        with httpx.Client() as client:
            resp = client.get("https://ipapi.co/json/", timeout=5.0).json()
            locale = resp.get("languages", "en-US").split(",")[0]
            city = resp.get("city", "")
            region = resp.get("region", "")
            
            _LOCALE_DATA = {
                "locale": locale,
                "city": city,
                "region": region
            }
            logger.info(f"🔍 [SEARCH] Auto-detected: {locale} ({city}, {region})")
            return _LOCALE_DATA
    except Exception as e:
        logger.warning(f"⚠️ [SEARCH] Location auto-detection failed ({e}). Defaulting to en-US.")
        return {"locale": "en-US", "city": "", "region": ""}


def searxng_search(query: str, limit: int) -> List[Dict[str, str]]:
    url = os.getenv("SEARXNG_ENDPOINT")
    if not url:
        return []
        
    location_data = get_detected_locale()
    locale = location_data["locale"]
    city = location_data["city"]
    
    # Refine query with city name for better local results
    refined_query = query
    if city and city.lower() not in query.lower():
        refined_query = f"{query} in {city}"
        logger.info(f"📍 [SEARCH] Refined query for local results: \"{refined_query}\"")

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
            with httpx.Client() as client:
                response = client.get(
                    url,
                    params={"q": refined_query, "format": "json", "pageno": pageno, "language": locale},
                    headers=headers,
                    timeout=5.0
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
        location_data = get_detected_locale()
        city = location_data["city"]
        
        # Refine query for DDG fallback too
        refined_query = query
        if city and city.lower() not in query.lower():
            refined_query = f"{query} in {city}"

        ddgs = DDGS()
        # Text returns list of dict with 'href', 'title', 'body'
        results = list(ddgs.text(refined_query, max_results=limit))
        
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

