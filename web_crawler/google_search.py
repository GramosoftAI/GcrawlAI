import json
import argparse
import threading
import random
import os
import logging
from typing import Dict, Any, Optional
from dotenv import load_dotenv
from web_crawler.retriever import DynamicFetcher, StealthyFetcher, PersistentStealthyFetcher

load_dotenv()
logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Singleton persistent fetcher
#
# Created ONCE at startup and reused forever.
# Recreating the browser on every call is the #1 reason Google shows CAPTCHA
# — a fresh headless session every 60s is an obvious bot signal.
#
# Proxy rotation happens at the network level (Evomi session_id).
# The browser process stays warm.
# ─────────────────────────────────────────────────────────────────────────────

_fetcher_lock = threading.Lock()
_persistent_fetcher: Optional[PersistentStealthyFetcher] = None
_search_call_count: int = 0

# ─── Tunable constants ────────────────────────────────────────────────────────
# Rotate proxy (recreate browser) every N search calls.
# Low value  → more IP changes, less session warmth → harder for Google to rate-limit one IP
# High value → warmer session, but same IP stays longer → Google may soft/hard block
# 3 is a safe default: Google typically allows 3-5 rapid searches per IP before /sorry
_ROTATE_EVERY_N_CALLS: int = 3
# ─────────────────────────────────────────────────────────────────────────────


def _make_fetcher(proxy_config: Optional[Dict]) -> PersistentStealthyFetcher:
    """Create a brand-new PersistentStealthyFetcher with the given proxy."""
    logger.info("[GoogleSearch] Creating PersistentStealthyFetcher with fresh proxy session.")
    return PersistentStealthyFetcher(
        headless=True,
        block_resources=False,  # Google needs JS/CSS — never block these
        proxy=proxy_config,
        timeout=180_000,        # 180s — covers CapMonster solve time
        solve_cloudflare=True,
        locale="en-US",         # must match --lang=en-US in launch args
    )


def _get_persistent_fetcher(proxy_config: Optional[Dict] = None) -> PersistentStealthyFetcher:
    """
    Return the process-level PersistentStealthyFetcher.

    Rotation logic:
      - Every _ROTATE_EVERY_N_CALLS searches, close the old browser and open
        a fresh one with a new proxy session_id → different exit IP.
      - Between rotations the browser stays warm (cookies/history survive).

    Why this works:
      - Old code: proxy_config ignored after first creation → SAME IP forever → hard block.
      - New code: new session_id per rotation window → Google sees different IPs.
      - Browser recreated only every N calls, not every call → still gets warmth benefit.
    """
    global _persistent_fetcher, _search_call_count

    with _fetcher_lock:
        _search_call_count += 1

        should_rotate = (
            _persistent_fetcher is None                           # first call
            or (_search_call_count % _ROTATE_EVERY_N_CALLS == 1  # rotation boundary
                and _search_call_count > 1)
        )

        if should_rotate:
            # Close old browser gracefully before creating new one
            if _persistent_fetcher is not None:
                logger.info(f"[GoogleSearch] Rotating proxy after {_search_call_count - 1} calls.")
                try:
                    _persistent_fetcher.close()
                except Exception:
                    pass

            _persistent_fetcher = _make_fetcher(proxy_config)

        return _persistent_fetcher


def _force_rotate_fetcher() -> None:
    """
    Force-rotate the fetcher immediately — call this when Google hard-blocks.
    Hard block = IP is fully banned, no CAPTCHA widget shown.
    Rotating here ensures the next search() call gets a completely fresh IP.
    """
    global _persistent_fetcher, _search_call_count
    with _fetcher_lock:
        if _persistent_fetcher is not None:
            logger.warning("[GoogleSearch] Force-rotating due to hard block.")
            try:
                _persistent_fetcher.close()
            except Exception:
                pass
            _persistent_fetcher = None
        # Reset counter so next call triggers a fresh fetcher
        _search_call_count = 0


def build_google_search_url(query: str, num: int = 10, start: int = 0) -> str:
    import urllib.parse
    return "https://www.google.com/search?" + urllib.parse.urlencode({"q": query, "num": num, "start": start})


def extract_search_results(response, limit: int = 20) -> Dict[str, Any]:
    results: Dict[str, Any] = {"query": "", "status": response.status, "results": []}

    for link in response.select("a[href]"):
        href = link.get("href")
        title = link.get_text(strip=True)
        if not href or not href.startswith("http") or len(title) <= 3:
            continue
        if any(x in href for x in ("google.", "/search?", "/url?")):
            continue

        snippet = ""
        parent = link.find_parent("div")
        if parent:
            for div in parent.find_all(["div", "span"]):
                text = div.get_text(strip=True)
                if text and len(text) > 10:
                    snippet = text
                    break

        results["results"].append({"title": title, "url": href, "snippet": snippet})

    seen: set = set()
    unique = []
    for r in results["results"]:
        if r["url"] not in seen:
            seen.add(r["url"])
            unique.append(r)

    results["results"] = unique[:limit]
    return results


def _build_proxy_config(proxy_url: Optional[str] = None) -> Optional[Dict]:
    """Build proxy config. Generates a new Evomi session_id for IP rotation."""
    if not proxy_url:
        evomi_server   = os.getenv("EVOMI_PROXY_SERVER")
        evomi_user     = os.getenv("EVOMI_PROXY_USERNAME")
        evomi_pass     = os.getenv("EVOMI_PROXY_PASSWORD")

        if evomi_server and evomi_user and evomi_pass:
            session_id = random.randint(100_000, 9_999_999)
            server_no_scheme = evomi_server.split("://")[-1]
            scheme = evomi_server.split("://")[0] if "://" in evomi_server else "http"
            proxy_url = f"{scheme}://{evomi_user}:{evomi_pass}@{server_no_scheme}?session={session_id}"
            logger.info(f"[GoogleSearch] Proxy session rotated — session_id={session_id}")
        else:
            proxy_url = os.getenv("CRAWL_PROXY")

    if not proxy_url:
        return None

    import urllib.parse
    parsed = urllib.parse.urlparse(proxy_url)
    if parsed.username and parsed.password:
        server_url = f"{parsed.scheme}://{parsed.hostname}:{parsed.port}"
        if parsed.query:
            server_url += f"?{parsed.query}"
        return {"server": server_url, "username": parsed.username, "password": parsed.password}

    return {"server": proxy_url}


def search(
    query: str,
    limit: int = 20,
    use_stealth: bool = True,
    headless: bool = True,
    output_file: str = None,
    proxy_url: str = None,
) -> Dict[str, Any]:
    results_per_page = 10  # Google shows ~10 organic results per page
    all_results: list = []
    seen_urls: set = set()
    pages_fetched = 0
    max_pages = (limit // results_per_page) + 2  # +2 for safety margin

    proxy_config = _build_proxy_config(proxy_url)

    if use_stealth:
        fetcher = _get_persistent_fetcher(proxy_config=proxy_config)
    else:
        fetcher = DynamicFetcher(
            headless=headless,
            block_resources=False,
            proxy=proxy_config,
            timeout=60_000,
        )

    start = 0
    while len(all_results) < limit and pages_fetched < max_pages:
        url = build_google_search_url(query, num=results_per_page, start=start)
        logger.info(f"[GoogleSearch] Query: {query} | Page: {pages_fetched + 1} | URL: {url}")

        logger.info("[GoogleSearch] Fetching with browser...")
        response = fetcher.fetch(url)

        # ── Hard block detection — rotate immediately ─────────────────────────
        if use_stealth and not response.ok:
            if response.error and "hard block" in response.error.lower():
                logger.warning("[GoogleSearch] Hard block detected → force rotating proxy.")
                _force_rotate_fetcher()
            elif response.status == 0:
                logger.warning("[GoogleSearch] Zero-status response → force rotating proxy.")
                _force_rotate_fetcher()

        if not response.ok:
            error_msg = response.error or f"Request failed with status {response.status}"
            logger.error(f"[GoogleSearch] Fetch failed: {error_msg}")
            if not all_results:
                return {"error": error_msg, "query": query, "url": url}
            break  # Use partial results

        logger.info(f"[GoogleSearch] Fetch success — status={response.status}")

        page_results = extract_search_results(response, limit=results_per_page * 2)
        new_results = 0
        for r in page_results.get("results", []):
            if r["url"] not in seen_urls:
                seen_urls.add(r["url"])
                all_results.append(r)
                new_results += 1

        pages_fetched += 1
        logger.info(f"[GoogleSearch] Page {pages_fetched}: found {new_results} new results (total: {len(all_results)}/{limit})")

        if new_results == 0:
            logger.info("[GoogleSearch] No new results — stopping pagination")
            break

        start += results_per_page

    results = {
        "query": query,
        "status": 200,
        "results": all_results[:limit],
        "pages_fetched": pages_fetched,
    }

    if output_file:
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2, ensure_ascii=False)
        logger.info(f"[GoogleSearch] Saved to: {output_file}")

    return results


async def scrape_google(
    query: str,
    limit: int,
    ip: str = None,
    headless: bool = True,
    fast_mode: bool = False,
) -> list:
    """
    Async wrapper around search().
    Timeout is 180s to match PersistentStealthyFetcher.timeout.
    """
    import asyncio
    loop = asyncio.get_event_loop()

    def run_search():
        return search(query=query, limit=limit, use_stealth=True, headless=headless)

    try:
        search_results = await asyncio.wait_for(
            loop.run_in_executor(None, run_search),
            timeout=180.0,
        )
    except asyncio.TimeoutError:
        logger.warning("⚠️ [GOOGLE] 180s deadline exceeded — skipping to fallback.")
        return []
    except Exception as e:
        logger.error(f"❌ [GOOGLE] Search failed: {e}")
        return []

    formatted = []
    if "results" in search_results:
        for r in search_results["results"][:limit]:
            formatted.append({
                "url": r.get("url"),
                "title": r.get("title"),
                "description": r.get("snippet", ""),
            })
    return formatted


def main():
    parser = argparse.ArgumentParser(description="Google Search Scraper")
    parser.add_argument("query", type=str)
    parser.add_argument("--no-stealth", action="store_true")
    parser.add_argument("--headful", action="store_true")
    parser.add_argument("--output", "-o", type=str)
    parser.add_argument("--quiet", "-q", action="store_true")
    parser.add_argument("--proxy", "-p", type=str)
    args = parser.parse_args()

    results = search(
        query=args.query,
        limit=20,
        use_stealth=not args.no_stealth,
        headless=not args.headful,
        output_file=args.output,
        proxy_url=args.proxy,
    )
    if not args.quiet:
        print("\n=== Search Results (JSON) ===\n")
    print(json.dumps(results, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()