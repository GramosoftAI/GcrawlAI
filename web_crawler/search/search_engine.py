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
# With FIX 12 (no cache poisoning), retries now actually hit Google again.
# Longer delays give Google's CAPTCHA flag time to expire for the IP subnet.
_GOOGLE_MAX_RETRIES: int = 4
_GOOGLE_RETRY_DELAYS: list = [8.0, 15.0, 25.0, 30.0]  # Escalating delays between retries

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


def _is_valid_google_result(results: Any) -> bool:
    """
    Determine whether the value returned by scrape_google is a genuine
    non-empty list of search results.

    scrape_google() returns:
      - []                          → timeout / exception (treat as failure)
      - [{"url": ..., ...}, ...]    → success
      - {"error": ..., ...}         → error dict leaked from search() (treat as failure)

    Any dict at the top level (including error dicts) is a failure. Only a
    non-empty list whose first item is a dict with a "url" key is a success.
    """
    if not results:
        return False
    if isinstance(results, dict):
        # Should not happen after the async wrapper, but guard anyway
        return False
    if not isinstance(results, list):
        return False
    # Confirm it looks like actual search results, not a list of error dicts
    first = results[0] if results else {}
    if not isinstance(first, dict):
        return False
    # A valid result must have a url; an error result has an "error" key
    if "error" in first and "url" not in first:
        return False
    return True


async def execute_search_router(query: str, limit: int, ip: Optional[str] = None) -> List[Dict[str, str]]:
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
        elapsed = time.time() - start_time
        logger.info(f"⏱️ [SEARCH] Total execution time: {elapsed:.2f} seconds")
        return filter_and_deduplicate(res, limit)

    search_limit = int(limit * 1.3) + 1

    # ── Attempt 1: Google Primary ────────────────────────────────────────────
    logger.info(f"🔍 [SEARCH] Attempting search with primary engine: Google (attempt 1/{_GOOGLE_MAX_RETRIES})")
    last_google_error = None
    try:
        results = await scrape_google(query, search_limit, ip, headless=True, fast_mode=False)

        if _is_valid_google_result(results):
            logger.info(f"✅ [SEARCH] Google search successful. Found {len(results)} results.")
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
            results = await scrape_google(query, search_limit, ip, headless=True, fast_mode=False)

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