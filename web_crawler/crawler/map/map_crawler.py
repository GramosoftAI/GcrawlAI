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
    _find_sitemaps_from_robots,
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
            if len(collected) >= MAX_URLS:
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
) -> int:
    """
    Use a pre-fetched homepage Response to extract links.
    Skips the HTTP request entirely — resp is already in memory.
    """
    with lock:
        if len(collected) >= MAX_URLS:
            logger.info("⛔ Limit already reached — skipping homepage link extraction")
            return 0

    if not resp:
        logger.warning("Homepage pre-fetch failed — skipping link extraction")
        return 0

    added = _parse_homepage_html(resp, base_url, collected, lock)
    logger.info(f"  → added {added} new URLs from homepage (pool: {len(collected)})")
    return added


def _collect_homepage_links(
    base_url: str, 
    collected: Set[str], 
    lock: threading.Lock,
    proxy_dict: Optional[dict] = None
) -> int:
    """
    Fetch the homepage and extract internal links.
    (Used as fallback when pre-fetching is not used.)
    """
    with lock:
        if len(collected) >= MAX_URLS:
            logger.info("⛔ Limit already reached — skipping homepage link extraction")
            return 0

    logger.info(f"🔗 Fetching homepage links: {base_url}")
    resp = _get(base_url, timeout=_PAGE_TIMEOUT, proxy_dict=proxy_dict)
    if not resp:
        logger.warning("Homepage fetch failed — skipping link extraction")
        return 0

    added = _parse_homepage_html(resp, base_url, collected, lock)
    logger.info(f"  → added {added} new URLs from homepage (pool: {len(collected)})")
    return added


# ── Step 4: Browser-based link extraction (fallback) ────────────────────────

def _browser_extract_links(
    start_url: str,
    collected: Set[str],
    lock: threading.Lock,
) -> int:
    """
    Render the homepage with Playwright/ClockBrowser and extract internal links
    from the fully-rendered DOM.  This catches JS-loaded navigation (e.g.
    sites that fetch header/footer HTML fragments at runtime).

    Returns the number of NEW URLs added to `collected`.
    """
    logger.info("🌐 Browser fallback — rendering homepage with ClockBrowser...")
    added = 0
    try:
        from playwright.sync_api import sync_playwright

        base_host = urlparse(start_url).netloc.lower()

        with sync_playwright() as pw:
            browser = pw.chromium.launch(
                headless=True,
                args=[
                    '--no-sandbox',
                    '--disable-setuid-sandbox',
                    '--disable-dev-shm-usage',
                    '--disable-gpu',
                    '--disable-blink-features=AutomationControlled',
                    '--dns-over-https-server=https://cloudflare-dns.com/dns-query'
                ]
            )
            context = browser.new_context(
                viewport={"width": 1920, "height": 1080},
                user_agent=_HEADERS["User-Agent"],
                java_script_enabled=True,
                ignore_https_errors=True,
            )
            page = context.new_page()

            try:
                page.goto(start_url, wait_until="domcontentloaded", timeout=30_000)
            except Exception as nav_err:
                logger.warning(f"  ⚠ Browser navigation error: {nav_err}")
                # Even on timeout, the page may have partially loaded

            # Extract all <a href> from the rendered DOM
            raw_links = page.evaluate("""
                () => Array.from(document.querySelectorAll('a[href]'))
                          .map(a => a.href)
            """)

            browser.close()

        new_urls: list = []
        for href in raw_links:
            if not href or not href.startswith("http"):
                continue
            parsed = urlparse(href)
            # Accept same host OR www variant
            link_host = parsed.netloc.lower()
            base_bare = base_host.replace("www.", "")
            link_bare = link_host.replace("www.", "")
            if link_bare != base_bare:
                continue
            if not _is_page_url(href):
                continue
            clean = _clean_url(href)
            new_urls.append(clean)

        with lock:
            for url in new_urls:
                if len(collected) >= MAX_URLS:
                    break
                if url not in collected:
                    collected.add(url)
                    added += 1

        logger.info(f"  → Browser fallback added {added} new URLs (pool: {len(collected)})")

    except ImportError:
        logger.warning("  ⚠ Playwright not installed — skipping browser fallback")
    except Exception as e:
        logger.warning(f"  ⚠ Browser fallback failed: {e}")

    return added


# ── Public API ───────────────────────────────────────────────────────────────

def map_website(start_url: str, proxy_dict: Optional[dict] = None) -> dict:
    """
    Firecrawl-style map mode: discover page URLs on a site.
    """
    logger.info(f"🗺️  Map mode started for: {start_url} (limit: {MAX_URLS} URLs)")

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

    # ── Step 2: XML sitemaps (parallel child fetching) ───────────────────────
    before_sitemap = len(collected)
    t0 = time.perf_counter()
    homepage_text = homepage_resp.text if homepage_resp else ""
    _collect_sitemap_urls(start_url, sitemap_hints, collected, lock, homepage_text, proxy_dict)
    from_sitemap = len(collected) - before_sitemap
    logger.info(f"⏱  sitemaps: {time.perf_counter()-t0:.2f}s → {from_sitemap} URLs (pool: {len(collected)})")

    # ── Step 3: Homepage link extraction (use pre-fetched response) ─────────
    t0 = time.perf_counter()
    from_homepage = _collect_homepage_links_from_resp(homepage_resp, start_url, collected, lock)
    logger.info(f"⏱  homepage: {time.perf_counter()-t0:.2f}s → {from_homepage} new URLs (pool: {len(collected)})")

    # ── Step 4: Browser fallback (if too few URLs found) ─────────────────────
    from_browser = 0
    if len(collected) <= _BROWSER_FALLBACK_THRESHOLD:
        logger.info(
            f"⚠ Only {len(collected)} URL(s) found via sitemap + static HTML "
            f"(threshold={_BROWSER_FALLBACK_THRESHOLD}) — trying browser fallback"
        )
        t0 = time.perf_counter()
        from_browser = _browser_extract_links(start_url, collected, lock)
        logger.info(f"⏱  browser: {time.perf_counter()-t0:.2f}s → {from_browser} new URLs (pool: {len(collected)})")

    # ── Build result ─────────────────────────────────────────────────────────
    sorted_urls = sorted(collected)
    total = len(sorted_urls)
    capped = total >= MAX_URLS

    logger.info(
        f"✅ Map complete — {total} unique URLs"
        + (f" (limit of {MAX_URLS} reached during extraction)" if capped else "")
    )

    return {
        "urls":          sorted_urls,
        "total":         total,
        "capped":        capped,
        "from_sitemap":  from_sitemap,
        "from_homepage": from_homepage,
        "sitemaps_used": sitemap_hints,
    }
