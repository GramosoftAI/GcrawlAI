import os
import httpx
import asyncio
import logging
from ddgs import DDGS
from typing import List, Dict, Any, Optional

from web_crawler.google_search import scrape_google

logger = logging.getLogger(__name__)

# Cache to avoid hitting GeoIP APIs on every search
_SERVER_LOCALE_CACHE = None
_USER_LOCALE_CACHE: Dict[str, Any] = {}

def get_detected_locale(ip: Optional[str] = None) -> dict:
    """Detects locale, city, and region based on IP. If IP is None, detects server IP."""
    global _SERVER_LOCALE_CACHE, _USER_LOCALE_CACHE
    
    # Check cache first
    if not ip and _SERVER_LOCALE_CACHE:
        return _SERVER_LOCALE_CACHE
    if ip and ip in _USER_LOCALE_CACHE:
        return _USER_LOCALE_CACHE[ip]

    # List of providers to try
    providers = [
        # Provider 1: ipapi.co (detailed, including languages)
        {"url": f"https://ipapi.co/{ip + '/' if ip else ''}json/", "type": "ipapi"},
        # Provider 2: ip-api.com (reliable fallback)
        {"url": f"http://ip-api.com/json/{ip or ''}", "type": "ip-api"}
    ]

    for provider in providers:
        try:
            with httpx.Client() as client:
                response = client.get(provider["url"], timeout=3.0)
                
                if response.status_code != 200:
                    logger.warning(f"⚠️ [SEARCH] {provider['type']} failed with status {response.status_code}")
                    continue
                    
                resp = response.json()
                
                # Check for error status in JSON body (common for 429/blocked)
                if resp.get("status") == "fail" or resp.get("error"):
                    continue

                if provider["type"] == "ipapi":
                    data = {
                        "locale": resp.get("languages", "en-US").split(",")[0] if resp.get("languages") else "en-US",
                        "city": resp.get("city", ""),
                        "region": resp.get("region", "")
                    }
                else:  # ip-api.com
                    data = {
                        "locale": "en-US", # ip-api doesn't provide language code in free tier
                        "city": resp.get("city", ""),
                        "region": resp.get("regionName", resp.get("region", ""))
                    }

                # Update cache
                if ip:
                    _USER_LOCALE_CACHE[ip] = data
                else:
                    _SERVER_LOCALE_CACHE = data
                
                logger.info(f"🔍 [SEARCH] Detected via {provider['type']} for {ip or 'server'}: {data['city']}, {data['region']}")
                return data
                
        except Exception as e:
            logger.debug(f"Provider {provider['type']} error: {e}")
            continue

    # Final fallback if all providers fail
    return {"locale": "en-US", "city": "", "region": ""}


def searxng_search(query: str, limit: int, ip: Optional[str] = None) -> List[Dict[str, str]]:
    url = os.getenv("SEARXNG_ENDPOINT")
    if not url:
        return []
        
    location_data = get_detected_locale(ip)
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

def ddg_search(query: str, limit: int, ip: Optional[str] = None) -> List[Dict[str, str]]:
    try:
        location_data = get_detected_locale(ip)
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

async def execute_search_router(query: str, limit: int, ip: Optional[str] = None) -> List[Dict[str, str]]:
    """
    Implements a fallback router for search engines.
    1. Google (Primary) - Uses Playwright for scraping
    2. SearXNG (Secondary)
    3. DuckDuckGo (Fallback)
    """
    import time
    start_time = time.time()

    def _finalize(res):
        elapsed = time.time() - start_time
        logger.info(f"⏱️ [SEARCH] Total execution time: {elapsed:.2f} seconds")
        return filter_and_deduplicate(res, limit)

    # Request slightly more than limit to account for deduplication (30% buffer)
    search_limit = int(limit * 1.3) + 1

    # 1. Primary: Google
    logger.info(f"🔍 [SEARCH] Attempting search with primary engine: Google")
    try:
        results = await scrape_google(query, search_limit, ip, headless=True, fast_mode=False)
        if results:
            logger.info(f"✅ [SEARCH] Google search successful. Found results.")
            return _finalize(results)
    except Exception as e:
        logger.error(f"❌ [SEARCH] Google search failed with error: {type(e).__name__}: {e}")
        import traceback
        logger.error(f"Stacktrace: {traceback.format_exc()}")

    # 2. Secondary: SearXNG
    if os.getenv("SEARXNG_ENDPOINT"):
        logger.info(f"🔍 [SEARCH] Attempting search with secondary engine: SearXNG")
        results = searxng_search(query, search_limit, ip)
        if results:
            logger.info(f"✅ [SEARCH] SearXNG search successful. Found results.")
            return _finalize(results)

    # 3. Fallback: DuckDuckGo
    logger.info(f"🦆 [SEARCH] Attempting search with fallback engine: DuckDuckGo (DDGS)")
    results = ddg_search(query, search_limit, ip)
    if results:
        logger.info(f"✅ [SEARCH] DuckDuckGo search successful. Found results.")
        
    return _finalize(results or [])



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

