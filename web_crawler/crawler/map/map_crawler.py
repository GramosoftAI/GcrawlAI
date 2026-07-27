"""
Map Crawler — Firecrawl-style site URL discovery.

If sitemap + static HTML discovery yields too few results,
falls back to browser-based rendering (Playwright/ClockBrowser) to
capture JS-loaded navigation links.
"""

import logging
import threading
import time
from typing import Optional, Set
from urllib.parse import urlparse, urljoin
import requests
from bs4 import BeautifulSoup
from concurrent.futures import ThreadPoolExecutor

# Import split components
from web_crawler.crawler.map.map_crawler_utils import (
    _get,
    _origin,
    _same_host,
    _clean_url,
    _is_page_url,
    _PAGE_TIMEOUT,
    _ROBOTS_TIMEOUT,
    _HEADERS,
    MAX_URLS,
)
from web_crawler.crawler.map.map_crawler_xml import (
    _collect_sitemap_urls,
)

logger = logging.getLogger(__name__)

_BROWSER_FALLBACK_THRESHOLD = 5  # if we find ≤ this many URLs, try browser rendering


# ── Step 3: Homepage <a href> extraction ─────────────────────────────────────

def _parse_homepage_html(
    resp: requests.Response,
    base_url: str,
    collected: Set[str],
    lock: threading.Lock,
    limit: int = MAX_URLS,
) -> int:
    """
    Parse homepage HTML from an already-fetched Response.
    Adds new internal links into `collected` (thread-safe via lock).
    Returns count of URLs newly added.
    """
    soup = BeautifulSoup(resp.text, "lxml")
    base_host = urlparse(base_url).netloc.lower()
    if base_host.startswith("www."): base_host = base_host[4:]
    seen_paths: Set[str] = set()
    new_urls: list = []

    for anchor in soup.find_all("a", href=True):
        href = anchor["href"].strip()
        if not href or href.startswith(("#", "mailto:", "tel:", "javascript:", "data:")):
            continue

        abs_url = urljoin(base_url, href)
        if not abs_url.startswith("http"):
            continue

        parsed = urlparse(abs_url)
        url_host = parsed.netloc.lower()
        if url_host.startswith("www."): url_host = url_host[4:]
        if url_host != base_host:
            continue  # external domain / subdomain

        if not _is_page_url(abs_url):
            continue  # asset / binary file

        clean = _clean_url(abs_url)
        path = urlparse(clean).path
        if path in seen_paths:
            continue
        seen_paths.add(path)
        new_urls.append(clean)

    added = 0
    with lock:
        for url in new_urls:
            if len(collected) >= limit:
                break
            if url not in collected:
                collected.add(url)
                added += 1

    return added


def _collect_homepage_links_from_resp(
    resp: Optional[requests.Response],
    base_url: str,
    collected: Set[str],
    lock: threading.Lock,
    limit: int = MAX_URLS,
) -> int:
    """
    Use a pre-fetched homepage Response to extract links.
    Skips the HTTP request entirely — resp is already in memory.
    """
    with lock:
        if len(collected) >= limit:
            logger.info("⛔ Limit already reached — skipping homepage link extraction")
            return 0

    if not resp:
        logger.warning("Homepage pre-fetch failed — skipping link extraction")
        return 0

    added = _parse_homepage_html(resp, base_url, collected, lock, limit)
    logger.info(f"  → added {added} new URLs from homepage (pool: {len(collected)})")
    return added



# ── Step 4: Browser-based link extraction (fallback) ────────────────────────

def _browser_extract_links(
    start_url: str,
    collected: Set[str],
    lock: threading.Lock,
    limit: int = MAX_URLS,
    proxy_dict: Optional[dict] = None,
) -> int:
    """
    Render the homepage with Playwright/ClockBrowser and extract internal links
    from the fully-rendered DOM using multiple rotated proxy attempts running in parallel.

    Returns the number of NEW URLs added to `collected`.
    """
    logger.info("🌐 Browser fallback — rendering homepage with CloakBrowser...")
    added_links = []
    success_event = threading.Event()
    success_lock = threading.Lock()

    def _worker_attempt(attempt_idx):
        """Worker attempt."""
        if success_event.is_set():
            return
        
        browser = None
        try:
            import cloakbrowser
            import random
            import re
            from web_crawler.common.proxy_manager import parse_proxy_for_playwright

            base_host = urlparse(start_url).netloc.lower()

            # Parse proxy settings if available and rotate session ID to get a clean IP
            pw_proxy = None
            if proxy_dict:
                proxy_url = proxy_dict.get("https") or proxy_dict.get("http")
                if proxy_url:
                    new_session = "".join(random.choices("0123456789abcdef", k=8))
                    proxy_url = re.sub(r'session-[a-zA-Z0-9]+', f'session-{new_session}', proxy_url)
                    pw_proxy = parse_proxy_for_playwright(proxy_url)

            # Generate human-like random fingerprint configuration for CloakBrowser
            platform_choice = random.choices(["windows", "macos", "linux"], weights=[85, 10, 5])[0]
            seed = random.randint(100000, 9999999)
            width, height = 1920, 1080
            fingerprint_args = [
                f"--fingerprint={seed}",
                f"--fingerprint-platform={platform_choice}",
                f"--fingerprint-screen-width={width}",
                f"--fingerprint-screen-height={height}",
            ]

            launch_args = {
                "headless": True,
                "timezone": "America/Los_Angeles",
                "locale": "en-US",
                "args": fingerprint_args,
            }
            if pw_proxy:
                launch_args["proxy"] = pw_proxy

            logger.info(f"🌐 Threaded browser fallback: Launching Parallel Attempt {attempt_idx}...")
            browser = cloakbrowser.launch(humanize=True, **launch_args)
            page = browser.new_page()

            # Block heavy/unnecessary resources for ultra-fast loading
            def block_resources(route):
                """Block resources."""
                req_type = route.request.resource_type
                if req_type in ["image", "stylesheet", "font", "media"]:
                    return route.abort()
                route.continue_()

            page.route("**/*", block_resources)

            if success_event.is_set():
                browser.close()
                return

            page.goto(start_url, wait_until="domcontentloaded", timeout=20_000)
            page_title = page.title()
            
            # Extract links
            raw_links = page.evaluate("""
                () => Array.from(document.querySelectorAll('a[href]'))
                          .map(a => a.href)
            """)

            browser.close()

            if page_title and len(raw_links) > 0:
                with success_lock:
                    if not success_event.is_set():
                        success_event.set()
                        logger.info(f"  ✓ Parallel Attempt {attempt_idx} succeeded! Title: {page_title}, Links: {len(raw_links)}")
                        
                        # Process links inside the lock to avoid concurrency issues
                        for href in raw_links:
                            if not href or not href.startswith("http"):
                                continue
                            parsed = urlparse(href)
                            link_host = parsed.netloc.lower()
                            base_bare = base_host.replace("www.", "")
                            link_bare = link_host.replace("www.", "")
                            if link_bare != base_bare:
                                continue
                            if not _is_page_url(href):
                                continue
                            clean = _clean_url(href)
                            added_links.append(clean)
            else:
                logger.warning(f"  ⚠ Parallel Attempt {attempt_idx} got blocked (Title empty or 0 links found).")

        except ImportError:
            logger.warning(f"  ⚠ Parallel Attempt {attempt_idx} failed: Playwright or cloakbrowser not installed")
        except Exception as e:
            logger.warning(f"  ⚠ Parallel Attempt {attempt_idx} failed: {e}")
            if browser:
                try:
                    browser.close()
                except:
                    pass

    # Try up to 2 rounds of parallel attempts (total 6 attempts)
    for round_idx in range(1, 3):
        logger.info(f"🌐 Threaded browser fallback: Starting Round {round_idx}/2...")
        threads = []
        for idx in range(1, 4):
            attempt_idx = (round_idx - 1) * 3 + idx
            t = threading.Thread(target=_worker_attempt, args=(attempt_idx,))
            threads.append(t)
            t.start()
            # Stagger the thread starts slightly to prevent Playwright process spawning race conditions in uvloop
            time.sleep(1.5)

        # Wait for all attempts in this round to finish/terminate
        for t in threads:
            t.join()

        # If any attempt succeeded in this round, break the round loop early!
        if success_event.is_set():
            logger.info(f"  ✓ Threaded browser fallback: Success in Round {round_idx}!")
            break
        else:
            logger.warning(f"  ⚠ Round {round_idx} failed to retrieve any links.")

    added = 0
    with lock:
        for url in added_links:
            if len(collected) >= limit:
                break
            if url not in collected:
                collected.add(url)
                added += 1

    logger.info(f"  → Browser fallback added {added} new URLs (pool: {len(collected)})")
    return added


# ── Public API ───────────────────────────────────────────────────────────────

def map_website(start_url: str, limit: int = MAX_URLS, proxy_dict: Optional[dict] = None) -> dict:
    """
    Firecrawl-style map mode: discover page URLs on a site.
    """
    logger.info(f"🗺️  Map mode started for: {start_url} (limit: {limit} URLs)")

    # Shared mutable state — all steps write into this single set
    collected: Set[str] = set()
    lock = threading.Lock()

    # Always seed with the start URL itself
    collected.add(_clean_url(start_url))

    # ── Pre-fetch robots.txt AND homepage HTML in parallel ───────────────────
    t_total = time.perf_counter()

    with ThreadPoolExecutor(max_workers=2) as pre_exec:
        fut_robots   = pre_exec.submit(_get, f"{_origin(start_url)}/robots.txt", _ROBOTS_TIMEOUT, proxy_dict)
        fut_homepage = pre_exec.submit(_get, start_url, _PAGE_TIMEOUT, proxy_dict)

    robots_resp   = fut_robots.result()
    homepage_resp = fut_homepage.result()

    # ── Step 1: robots.txt (parse already-fetched response) ────────────────
    t0 = time.perf_counter()
    sitemap_hints = []
    if robots_resp:
        for line in robots_resp.text.splitlines():
            stripped = line.strip()
            if stripped.lower().startswith("sitemap:"):
                sitemap_url = stripped.split(":", 1)[1].strip()
                if sitemap_url.startswith("http"):
                    sitemap_hints.append(sitemap_url)
                    logger.info(f"  📄 Found sitemap directive: {sitemap_url}")
    else:
        logger.info("robots.txt not found or inaccessible")
    logger.info(f"⏱  robots.txt parsed: {time.perf_counter()-t0:.2f}s ({len(sitemap_hints)} sitemap(s))")

    # ── Step 2: Homepage link extraction (use pre-fetched response) ─────────
    t0 = time.perf_counter()
    from_homepage = _collect_homepage_links_from_resp(homepage_resp, start_url, collected, lock, limit)
    logger.info(f"⏱  homepage: {time.perf_counter()-t0:.2f}s → {from_homepage} new URLs (pool: {len(collected)})")

    # ── Step 3: XML sitemaps (parallel child fetching) ───────────────────────
    # If the homepage yielded 0 links, we are either blocked by a WAF or it is a headless JS site.
    # In either case, skip XML sitemaps probe to avoid wasting time on timeout checks.
    before_sitemap = len(collected)
    t0 = time.perf_counter()
    if homepage_resp and from_homepage > 0:
        homepage_text = homepage_resp.text
        _collect_sitemap_urls(start_url, sitemap_hints, collected, lock, homepage_text, proxy_dict, limit)
        from_sitemap = len(collected) - before_sitemap
        logger.info(f"⏱  sitemaps: {time.perf_counter()-t0:.2f}s → {from_sitemap} URLs (pool: {len(collected)})")
    else:
        from_sitemap = 0
        logger.info("  ⚠ Static homepage yielded 0 links. Skipping sitemaps probe to save time.")

    # ── Step 4: Browser fallback (if too few URLs found) ─────────────────────
    from_browser = 0
    if len(collected) <= _BROWSER_FALLBACK_THRESHOLD:
        logger.info(
            f"⚠ Only {len(collected)} URL(s) found via sitemap + static HTML "
            f"(threshold={_BROWSER_FALLBACK_THRESHOLD}) — trying browser fallback"
        )
        t0 = time.perf_counter()
        from_browser = _browser_extract_links(start_url, collected, lock, limit, proxy_dict)
        logger.info(f"⏱  browser: {time.perf_counter()-t0:.2f}s → {from_browser} new URLs (pool: {len(collected)})")

    # ── Build result ─────────────────────────────────────────────────────────
    sorted_urls = sorted(collected)
    total = len(sorted_urls)
    capped = total >= limit

    logger.info(
        f"✅ Map complete — {total} unique URLs"
        + (f" (limit of {limit} reached during extraction)" if capped else "")
    )

    return {
        "urls":          sorted_urls,
        "total":         total,
        "capped":        capped,
        "from_sitemap":  from_sitemap,
        "from_homepage": from_homepage,
        "sitemaps_used": sitemap_hints,
    }
