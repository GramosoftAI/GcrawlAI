import os
import httpx
import asyncio
import logging
import time
from ddgs import DDGS
from typing import List, Dict, Any, Optional

from web_crawler.search.google_search import scrape_google

logger = logging.getLogger(__name__)

# Cache to avoid hitting GeoIP APIs on every search
_SERVER_LOCALE_CACHE = None
_USER_LOCALE_CACHE: Dict[str, Any] = {}

# ─────────────────────────────────────────────────────────────────────────────
# SearXNG Circuit Breaker
# After the first connection failure, skip SearXNG for _SEARXNG_COOLDOWN seconds
# instead of wasting ~4s per request trying to connect to a dead service.
# ─────────────────────────────────────────────────────────────────────────────
_SEARXNG_LAST_FAILURE: Optional[float] = None
_SEARXNG_COOLDOWN: float = 300.0  # 5 minutes

# DDG Fallback Control — set ALLOW_DDG_FALLBACK=true to enable DDG as last resort
_ALLOW_DDG_FALLBACK: bool = os.getenv("ALLOW_DDG_FALLBACK", "false").lower() == "true"

# Google Retry Configuration — how many times to retry Google before giving up
# Short delays are optimal because we use rotating proxies, so retries use a fresh IP instantly.
_GOOGLE_MAX_RETRIES: int = 4
_GOOGLE_RETRY_DELAYS: list = [1.0, 2.0, 3.0, 4.0]  # Fast delays for rapid proxy rotation

def get_detected_locale(ip: Optional[str] = None) -> dict:
    """Detects locale, city, and region based on IP. If IP is None, detects server IP."""
    global _SERVER_LOCALE_CACHE, _USER_LOCALE_CACHE

    if not ip and _SERVER_LOCALE_CACHE:
        return _SERVER_LOCALE_CACHE
    if ip and ip in _USER_LOCALE_CACHE:
        return _USER_LOCALE_CACHE[ip]

    providers = [
        {"url": f"https://ipapi.co/{ip + '/' if ip else ''}json/", "type": "ipapi"},
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

                if resp.get("status") == "fail" or resp.get("error"):
                    continue

                if provider["type"] == "ipapi":
                    data = {
                        "locale": resp.get("languages", "en-US").split(",")[0] if resp.get("languages") else "en-US",
                        "city": resp.get("city", ""),
                        "region": resp.get("region", "")
                    }
                else:
                    data = {
                        "locale": "en-US",
                        "city": resp.get("city", ""),
                        "region": resp.get("regionName", resp.get("region", ""))
                    }

                if ip:
                    _USER_LOCALE_CACHE[ip] = data
                else:
                    _SERVER_LOCALE_CACHE = data

                logger.info(f"🔍 [SEARCH] Detected via {provider['type']} for {ip or 'server'}: {data['city']}, {data['region']}")
                return data

        except Exception as e:
            logger.debug(f"Provider {provider['type']} error: {e}")
            continue

    return {"locale": "en-US", "city": "", "region": ""}


def searxng_search(query: str, limit: int, ip: Optional[str] = None) -> List[Dict[str, str]]:
    """Searxng search."""
    global _SEARXNG_LAST_FAILURE
    url = os.getenv("SEARXNG_ENDPOINT")
    if not url:
        return []

    # SearXNG circuit breaker: skip if recently failed
    if _SEARXNG_LAST_FAILURE is not None:
        elapsed = time.time() - _SEARXNG_LAST_FAILURE
        if elapsed < _SEARXNG_COOLDOWN:
            logger.info(
                f"⏭️ [SEARCH] SearXNG circuit breaker OPEN — skipping "
                f"(failed {elapsed:.0f}s ago, cooldown={_SEARXNG_COOLDOWN:.0f}s)"
            )
            return []
        else:
            logger.info("🔁 [SEARCH] SearXNG circuit breaker HALF-OPEN — retrying")
            _SEARXNG_LAST_FAILURE = None

    location_data = get_detected_locale(ip)
    locale = location_data["locale"]

    all_results = []
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
        "Accept": "application/json",
        "Accept-Language": "en-US,en;q=0.9",
    }

    for pageno in range(1, 11):
        try:
            with httpx.Client() as client:
                response = client.get(
                    url,
                    params={"q": query, "format": "json", "pageno": pageno, "language": locale},
                    headers=headers,
                    timeout=5.0
                )
            if response.status_code == 200:
                # SearXNG is back! Reset circuit breaker
                if _SEARXNG_LAST_FAILURE is not None:
                    logger.info("✅ [SEARCH] SearXNG circuit breaker CLOSED (connection restored)")
                    _SEARXNG_LAST_FAILURE = None

                page_data = response.json()
                page_results = page_data.get("results", [])

                if not page_results:
                    break

                all_results.extend(page_results)

                if len(all_results) >= limit:
                    break
            else:
                logger.warning(f"SearXNG pageno {pageno} failed with status {response.status_code}")
                break
        except Exception as e:
            logger.warning(f"SearXNG engine at {url} page {pageno} failed: {e}")
            # Open circuit breaker on connection failure
            _SEARXNG_LAST_FAILURE = time.time()
            logger.warning(
                f"⚡ [SEARCH] SearXNG circuit breaker OPENED — "
                f"will skip for {_SEARXNG_COOLDOWN:.0f}s"
            )
            break

    formatted = []
    for r in all_results[:limit]:
        formatted.append({
            "url": r.get("url"),
            "title": r.get("title"),
            "description": r.get("content", "")
        })
    return formatted


def ddg_search(query: str, limit: int, ip: Optional[str] = None) -> List[Dict[str, str]]:
    """Ddg search."""
    try:
        location_data = get_detected_locale(ip)
        city = location_data["city"]

        refined_query = query
        if city and city.lower() not in query.lower():
            refined_query = f"{query} in {city}"

        ddgs = DDGS()
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


async def serper_search(query: str, limit: int) -> List[Dict[str, str]]:
    """Search Google using Serper.dev API."""
    from pathlib import Path
    from dotenv import load_dotenv

    BASE_DIR = Path(__file__).resolve().parent.parent.parent
    dotenv_path = BASE_DIR / '.env'
    load_dotenv(dotenv_path, override=True)

    api_key = os.getenv("SERPER_API_KEY")
    if not api_key:
        logger.warning("⚠️ [SEARCH] Serper API key not found in environment.")
        return []

    url = "https://google.serper.dev/search"
    headers = {
        "X-API-KEY": api_key,
        "Content-Type": "application/json"
    }

    all_results = []
    page = 1

    # We fetch page-by-page until we reach the requested limit
    while len(all_results) < limit:
        payload = {
            "q": query,
            "page": page
        }
        logger.info(f"🔍 [SEARCH] Serper.dev: Fetching page {page} for query: '{query}'")
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(url, json=payload, headers=headers)

            if response.status_code != 200:
                logger.warning(f"⚠️ [SEARCH] Serper.dev page {page} returned status code {response.status_code}: {response.text}")
                break

            data = response.json()
            organic = data.get("organic", [])
            if not organic:
                logger.info(f"ℹ️ [SEARCH] Serper.dev: No organic results returned on page {page}")
                break

            page_results = []
            for item in organic:
                link = item.get("link")
                title = item.get("title", "")
                snippet = item.get("snippet", "")
                if link:
                    page_results.append({
                        "url": link,
                        "title": title,
                        "description": snippet
                    })

            if not page_results:
                break

            all_results.extend(page_results)
            logger.info(f"✅ [SEARCH] Serper.dev: Page {page} fetched. Current total results: {len(all_results)}")

            page += 1

        except Exception as e:
            logger.error(f"❌ [SEARCH] Serper.dev error on page {page}: {e}")
            break

    return all_results[:limit]


def _is_valid_google_result(results: Any) -> bool:
    """
    Determine whether the value returned by scrape_google is a genuine
    non-empty list of search results.

    scrape_google() returns:
      - {"results": []}                          → timeout / exception (treat as failure)
      - {"results": [{"url": ..., ...}, ...], "proxy_usage": ...}    → success
    """
    if not isinstance(results, dict):
        return False
    res_list = results.get("results", [])
    if not res_list:
        return False
    first = res_list[0] if res_list else {}
    if not isinstance(first, dict):
        return False
    if "error" in first and "url" not in first:
        return False
    return True


async def execute_search_router(query: str, limit: int, ip: Optional[str] = None, proxy_geo: Optional[str] = None) -> Dict:
    """
    Implements a robust search router with aggressive Google retry.

    Strategy:
      1. Google (Primary) — first attempt
      2. Google (Retry) — up to 2 more attempts with escalating delays
      3. SearXNG (Secondary) — only if circuit breaker allows
      4. DuckDuckGo (Fallback) — ONLY if ALLOW_DDG_FALLBACK=true

    The key insight: Google 403/empty results are TRANSIENT. Retrying with
    a fresh proxy after a cooldown usually succeeds. DDG should never be
    needed in normal operation.
    """
    import time
    start_time = time.time()

    def _finalize(res):
        """Finalize."""
        elapsed = time.time() - start_time
        logger.info(f"⏱️ [SEARCH] Total execution time: {elapsed:.2f} seconds")
        
        # Ensure we always return a dict
        if isinstance(res, list):
            res_list = res
            res = {"results": res_list}
        else:
            res_list = res.get("results", [])
            
        res["results"] = filter_and_deduplicate(res_list, limit)
        return res

    search_limit = max(int(limit * 1.5) + 5, limit + 5)

    # ── Attempt 0: Serper.dev Search (Primary, if api key is present) ────────
    serper_api_key = os.getenv("SERPER_API_KEY")
    if serper_api_key:
        logger.info(f"🔍 [SEARCH] Attempting search with primary engine: Serper.dev")
        try:
            results = await serper_search(query, limit)
            if results:
                logger.info(f"✅ [SEARCH] Serper.dev search successful. Found {len(results)} results.")
                return _finalize(results)
            else:
                logger.warning("⚠️ [SEARCH] Serper.dev returned no results. Falling back to Google.")
        except Exception as e:
            logger.error(f"❌ [SEARCH] Serper.dev search failed: {e}. Falling back to Google.")

    # ── Attempt 1: Google Primary ────────────────────────────────────────────
    logger.info(f"🔍 [SEARCH] Attempting search with primary engine: Google (attempt 1/{_GOOGLE_MAX_RETRIES}) using proxy_geo={proxy_geo}")
    last_google_error = None
    try:
        results = await scrape_google(query, limit, ip, headless=True, fast_mode=False, proxy_geo=proxy_geo)

        if _is_valid_google_result(results):
            logger.info(f"✅ [SEARCH] Google search successful. Found {len(results.get('results', []))} results.")
            return _finalize(results)
        else:
            last_google_error = f"Google returned unusable result: {str(results)[:120]}"
            logger.warning(f"⚠️ [SEARCH] {last_google_error}")

    except Exception as e:
        last_google_error = f"{type(e).__name__}: {e}"
        logger.error(f"❌ [SEARCH] Google search failed: {last_google_error}")
        import traceback
        logger.error(f"Stacktrace: {traceback.format_exc()}")

    # ── Attempts 2+: Google Retry with Escalating Delays ────────────────────
    for retry_num in range(1, _GOOGLE_MAX_RETRIES):
        delay = _GOOGLE_RETRY_DELAYS[min(retry_num - 1, len(_GOOGLE_RETRY_DELAYS) - 1)]
        logger.info(
            f"🔄 [SEARCH] Google retry {retry_num + 1}/{_GOOGLE_MAX_RETRIES} "
            f"after {delay:.1f}s cooldown (previous: {last_google_error})"
        )
        await asyncio.sleep(delay)

        try:
            results = await scrape_google(query, limit, ip, headless=True, fast_mode=False, proxy_geo=proxy_geo)

            if _is_valid_google_result(results):
                logger.info(
                    f"✅ [SEARCH] Google retry {retry_num + 1} successful! "
                    f"Found {len(results)} results."
                )
                return _finalize(results)
            else:
                last_google_error = f"Google returned unusable result: {str(results)[:120]}"
                logger.warning(f"⚠️ [SEARCH] Google retry {retry_num + 1}: {last_google_error}")

        except Exception as e:
            last_google_error = f"{type(e).__name__}: {e}"
            logger.error(f"❌ [SEARCH] Google retry {retry_num + 1} failed: {last_google_error}")

    # ── SearXNG (only if circuit breaker allows) ────────────────────────────
    if os.getenv("SEARXNG_ENDPOINT"):
        logger.info(f"🔍 [SEARCH] Attempting search with secondary engine: SearXNG")
        results = searxng_search(query, search_limit, ip)
        if results:
            logger.info(f"✅ [SEARCH] SearXNG search successful. Found results.")
            return _finalize(results)

    # ── DuckDuckGo (ONLY if explicitly allowed) ─────────────────────────────
    if _ALLOW_DDG_FALLBACK:
        logger.info(f"🦆 [SEARCH] Attempting search with fallback engine: DuckDuckGo (DDGS)")
        results = ddg_search(query, search_limit, ip)
        if results:
            logger.info(f"✅ [SEARCH] DuckDuckGo search successful. Found results.")
            return _finalize(results)
    else:
        logger.warning(
            f"🚫 [SEARCH] All {_GOOGLE_MAX_RETRIES} Google attempts failed for "
            f"query='{query}'. DDG fallback is DISABLED. "
            f"Set ALLOW_DDG_FALLBACK=true to enable. Last error: {last_google_error}"
        )

    return _finalize([])


def filter_and_deduplicate(results: List[Dict[str, str]], limit: int) -> List[Dict[str, str]]:
    """Filter and deduplicate."""
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