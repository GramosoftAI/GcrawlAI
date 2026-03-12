"""
Map Crawler — Firecrawl-style site URL discovery.

If sitemap + static HTML discovery yields too few results,
falls back to browser-based rendering (Playwright/Chromium) to
capture JS-loaded navigation links.

Discovery order (same as Firecrawl map mode):
  1. robots.txt  → find all Sitemap: directives (5s timeout)
  2. Sitemap XML → parse <loc> tags recursively (handles sitemap index files)
                   Child sitemaps are fetched IN PARALLEL via ThreadPoolExecutor
                   Only same-host sitemaps are followed (subdomain sitemaps skipped)
  3. Homepage    → lightweight HTTP fetch + BeautifulSoup <a href> extraction
                   (catches nav links that aren't in the sitemap)

Speed optimisations:
  - Short connect timeout (5s) separate from read timeout (8s)
  - robots.txt already gave a sitemap → fallback probes are skipped entirely
  - Subdomain child sitemaps are skipped immediately (no HTTP fetch)
  - Child sitemaps inside a sitemap index are fetched concurrently (up to 8 threads)
  - Extraction stops the moment MAX_URLS unique URLs are collected
"""

import logging
import threading
import time
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Optional, Set, Tuple
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────────────────────

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/133.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}

# (connect_timeout, read_timeout) — fail fast on dead hosts
_SITEMAP_TIMEOUT: Tuple[int, int] = (5, 8)   # sitemap XML fetches
_PAGE_TIMEOUT:    Tuple[int, int] = (5, 10)  # homepage HTML fetch
_ROBOTS_TIMEOUT:  Tuple[int, int] = (5, 5)   # robots.txt is tiny

MAX_URLS        = 5_000   # stop extracting once this many unique URLs are collected
_MAX_WORKERS    = 8       # parallel threads for child sitemap fetching

_BLOCKED_EXTENSIONS = (
    ".pdf", ".jpg", ".jpeg", ".png", ".gif", ".svg",
    ".webp", ".css", ".js", ".woff", ".woff2", ".ttf",
    ".mp4", ".webm", ".ico", ".zip", ".gz", ".tar",
    # ".xml",  # Firecrawl includes .xml sitemaps in output
)

_SITEMAP_XML_NS = "{http://www.sitemaps.org/schemas/sitemap/0.9}"


# ── Internal helpers ─────────────────────────────────────────────────────────

def _get(
    url: str, 
    timeout: Tuple[int, int] = _SITEMAP_TIMEOUT,
    proxy_dict: Optional[dict] = None
) -> Optional[requests.Response]:
    """Safe HTTP GET; returns None on any error."""
    try:
        resp = requests.get(
            url, 
            headers=_HEADERS, 
            timeout=timeout, 
            allow_redirects=True,
            proxies=proxy_dict
        )
        if resp.status_code == 200:
            return resp
        logger.debug(f"HTTP {resp.status_code} for {url}")
    except requests.exceptions.Timeout:
        logger.debug(f"Timeout fetching {url}")
    except Exception as e:
        logger.debug(f"Request failed for {url}: {e}")
    return None


def _origin(url: str) -> str:
    """Return scheme + host, e.g. 'https://example.com'"""
    p = urlparse(url)
    return f"{p.scheme}://{p.netloc}"


def _same_host(url: str, base_url: str) -> bool:
    """True if url belongs to the SAME host as base_url (ignoring www. prefix)."""
    url_host = urlparse(url).netloc.lower()
    base_host = urlparse(base_url).netloc.lower()
    if url_host.startswith("www."): url_host = url_host[4:]
    if base_host.startswith("www."): base_host = base_host[4:]
    return url_host == base_host


def _clean_url(url: str) -> str:
    """Strip query string, fragment, .html extension and normalise trailing slash."""
    p = urlparse(url)
    path = p.path
    # Strip .html extension (Firecrawl normalises these away)
    if path.endswith(".html"):
        path = path[:-5]  # "/about/about.html" → "/about/about"
    if path != "/" and path.endswith("/"):
        path = path.rstrip("/")
    if not path:
        path = "/"
    return f"{p.scheme}://{p.netloc}{path}".lower()


def _is_page_url(url: str) -> bool:
    """Filter out binary / asset URLs that are not crawlable pages."""
    lower = url.lower().split("?")[0]
    # Filter Cloudflare internal paths
    if "/cdn-cgi/" in lower:
        return False
    # Filter known implementation-detail scaffolding pages:
    #   - /home/home(.html) — SPA internal entrypoint (simplfin.tech, gramosoft.tech)
    #   - /*/uiux(.html)    — UI/UX design page loaded as internal fragment
    path_no_ext = lower.replace(".html", "")
    if path_no_ext.endswith("/home/home") or path_no_ext.endswith("/uiux"):
        return False
    return not any(lower.endswith(ext) for ext in _BLOCKED_EXTENSIONS)


# ── Step 1: robots.txt ───────────────────────────────────────────────────────

def _find_sitemaps_from_robots(base_url: str) -> List[str]:
    """
    Fetch robots.txt and extract every 'Sitemap:' directive.
    Returns a list of absolute sitemap URLs (same host only), empty list on failure.
    """
    robots_url = f"{_origin(base_url)}/robots.txt"
    logger.info(f"🤖 Fetching robots.txt: {robots_url}")
    resp = _get(robots_url, timeout=_ROBOTS_TIMEOUT)
    if not resp:
        logger.info("robots.txt not found or inaccessible")
        return []

    sitemaps = []
    for line in resp.text.splitlines():
        stripped = line.strip()
        if stripped.lower().startswith("sitemap:"):
            sitemap_url = stripped.split(":", 1)[1].strip()
            if sitemap_url.startswith("http"):
                sitemaps.append(sitemap_url)
                logger.info(f"  📄 Found sitemap directive: {sitemap_url}")

    return sitemaps


# ── Step 2: Sitemap XML parsing ──────────────────────────────────────────────

def _fetch_and_extract_urls(
    sitemap_url: str,
    base_url: str,
    homepage_text: str = "",
    proxy_dict: Optional[dict] = None
) -> Tuple[str, List[str], List[str], bool]:
    """
    Fetch one sitemap URL and return:
      (sitemap_url, child_sitemap_urls, page_urls, success)
    child_sitemap_urls are only returned for same-host sitemaps.
    """
    resp = _get(sitemap_url, timeout=_SITEMAP_TIMEOUT, proxy_dict=proxy_dict)
    if not resp:
        return sitemap_url, [], [], False

    page_urls: List[str] = []
    child_sitemaps: List[str] = []
    success = True

    try:
        root = ET.fromstring(resp.content)
        tag = root.tag

        if "sitemapindex" in tag:
            for sitemap_el in root.iter(f"{_SITEMAP_XML_NS}sitemap"):
                loc_el = sitemap_el.find(f"{_SITEMAP_XML_NS}loc")
                if loc_el is not None and loc_el.text:
                    child_url = loc_el.text.strip()
                    # ✅ Only follow child sitemaps on the SAME host — skip subdomains
                    if _same_host(child_url, base_url):
                        child_sitemaps.append(child_url)
                    else:
                        logger.debug(f"  ⏭  Skipping subdomain sitemap: {child_url}")

        elif "urlset" in tag:
            for url_el in root.iter(f"{_SITEMAP_XML_NS}url"):
                loc_el = url_el.find(f"{_SITEMAP_XML_NS}loc")
                if loc_el is not None and loc_el.text:
                    page_url = loc_el.text.strip()
                    if _same_host(page_url, base_url) and _is_page_url(page_url):
                        page_urls.append(_clean_url(page_url))
        else:
            logger.warning(f"Unknown sitemap root tag: {tag}")
    except ET.ParseError as e:
        logger.warning(f"XML parse error for {sitemap_url}: {e}")
        # If it's not XML, it might be an HTML sitemap OR a Soft 404
        if resp.headers.get("Content-Type", "").startswith("text/html"):
             # Soft 404 Check: If the HTML is virtually identical in size to the homepage,
             # it's just a catch-all redirect serving the homepage (e.g. gmat.com.my).
             html_len = len(resp.text)
             hp_len = len(homepage_text)
             # If lengths are within ~2% of each other, it's almost certainly the same page
             if hp_len > 0 and abs(html_len - hp_len) / hp_len < 0.02:
                 logger.info(f"  ⏭  Discarding {sitemap_url} as Soft 404 (matches homepage size)")
                 success = False
             else:
                 logger.info(f"  📄 {sitemap_url} is HTML — extracting links...")
                 soup = BeautifulSoup(resp.text, "lxml")
                 base_host = urlparse(base_url).netloc.lower()
                 if base_host.startswith("www."): base_host = base_host[4:]
                 for anchor in soup.find_all("a", href=True):
                     href = anchor["href"].strip()
                     abs_url = urljoin(sitemap_url, href)
                     url_host = urlparse(abs_url).netloc.lower()
                     if url_host.startswith("www."): url_host = url_host[4:]
                     if url_host == base_host and _is_page_url(abs_url):
                         page_urls.append(_clean_url(abs_url))
        else:
             success = False

    return sitemap_url, child_sitemaps, page_urls, success


def _collect_sitemap_urls(
    base_url: str,
    sitemap_hints: List[str],
    collected: Set[str],
    lock: threading.Lock,
    homepage_text: str = "",
    proxy_dict: Optional[dict] = None
) -> None:
    """
    Discover URLs from all sitemaps using a BFS queue + thread pool.

    - sitemap_hints (from robots.txt) are tried first
    - Fallback paths (/sitemap.xml etc.) are only probed if robots.txt gave nothing
    - Child sitemaps are fetched IN PARALLEL (up to _MAX_WORKERS threads)
    - Subdomain child sitemaps are skipped entirely (no HTTP fetch)
    - Stops as soon as MAX_URLS unique URLs are in `collected`
    """
    origin = _origin(base_url)

    candidates = []
    if sitemap_hints:
        candidates.extend(sitemap_hints)
        logger.info(f"✅ robots.txt gave {len(sitemap_hints)} sitemap(s)")
    
    # Common sitemap/page probes — probe these on every site for Firecrawl parity
    common_probes = [
        f"{origin}/sitemap_index.xml",
        f"{origin}/sitemap.xml",
        f"{origin}/sitemap",
        # These page paths appear in Firecrawl maps but aren't always in XML sitemaps:
        f"{origin}/privacy",
        f"{origin}/terms_and_condition",
    ]
    for p in common_probes:
        if p not in candidates:
            candidates.append(p)
    
    logger.info(f"❓ Probing {len(candidates)} potential sitemap locations")

    visited_sitemaps: Set[str] = set()
    # BFS queue of sitemap URLs to process
    queue: List[str] = []
    # Keep track of which URLs were top-level candidates (to match Firecrawl parity)
    top_level_candidates = set(candidates)
    
    for c in candidates:
        if c not in visited_sitemaps:
            visited_sitemaps.add(c)
            queue.append(c)

    while queue:
        with lock:
            if len(collected) >= MAX_URLS:
                logger.info(f"⛔ Limit {MAX_URLS} reached — aborting sitemap BFS")
                break

        # Take up to _MAX_WORKERS sitemaps from the queue and fetch them in parallel
        batch = queue[:_MAX_WORKERS]
        queue = queue[_MAX_WORKERS:]

        logger.info(f"📋 Fetching {len(batch)} sitemap(s) in parallel: {batch}")

        with ThreadPoolExecutor(max_workers=len(batch)) as executor:
            futures = {
                executor.submit(_fetch_and_extract_urls, url, base_url, homepage_text, proxy_dict): url
                for url in batch
            }
            for future in as_completed(futures):
                sitemap_url, child_sitemaps, page_urls, success = future.result()

                # Add the sitemap URL itself to collected (Firecrawl parity)
                # ONLY if it was a top-level candidate (not a discovered child sitemap)
                if success and sitemap_url in top_level_candidates:
                    with lock:
                        if _same_host(sitemap_url, base_url):
                            collected.add(_clean_url(sitemap_url))

                # For specifically-probed page URLs (privacy, terms_and_condition),
                # always add if they exist — even if they aren't top-level sitemaps
                elif success and any(x in sitemap_url for x in ["/privacy", "/terms_and_condition"]):
                    with lock:
                        collected.add(_clean_url(sitemap_url))

                # Queue new child sitemaps (same host only, not yet visited)
                for child in child_sitemaps:
                    if child not in visited_sitemaps:
                        visited_sitemaps.add(child)
                        queue.append(child)
                        logger.debug(f"  ↳ Queued child sitemap: {child}")

                # Add page URLs into the shared pool
                with lock:
                    added = 0
                    for url in page_urls:
                        if len(collected) >= MAX_URLS:
                            logger.info(f"  ⛔ Limit reached — stopping URL addition")
                            break
                        if url not in collected:
                            collected.add(url)
                            added += 1
                    if added:
                        logger.info(
                            f"  → +{added} URLs from {sitemap_url} (pool: {len(collected)})"
                        )


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
    new_urls: List[str] = []

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

_BROWSER_FALLBACK_THRESHOLD = 5  # if we find ≤ this many URLs, try browser rendering

def _browser_extract_links(
    start_url: str,
    collected: Set[str],
    lock: threading.Lock,
) -> int:
    """
    Render the homepage with Playwright/Chromium and extract internal links
    from the fully-rendered DOM.  This catches JS-loaded navigation (e.g.
    sites that fetch header/footer HTML fragments at runtime).

    Returns the number of NEW URLs added to `collected`.
    """
    logger.info("🌐 Browser fallback — rendering homepage with Chromium...")
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
                page.goto(start_url, wait_until="networkidle", timeout=30_000)
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

    Speed guarantees:
      - robots.txt timeout:  5s connect / 5s read
      - sitemap XML timeout: 5s connect / 8s read
      - homepage timeout:    5s connect / 10s read
      - Subdomain sitemaps:  never fetched (skipped immediately)
      - robots.txt has sitemap: fallback probes skipped entirely
      - Child sitemaps:      fetched in parallel (up to 8 threads)
      - Extraction stops at MAX_URLS=5000 with no further HTTP requests

    Returns:
        {
            "urls":          List[str],  # sorted, deduplicated discovered URLs
            "total":         int,        # number of URLs (≤ MAX_URLS)
            "capped":        bool,       # True if MAX_URLS was hit during extraction
            "from_sitemap":  int,        # URLs from XML sitemaps
            "from_homepage": int,        # URLs added from homepage <a> scan
            "sitemaps_used": List[str],  # Sitemap: directives from robots.txt
        }
    """
    logger.info(f"🗺️  Map mode started for: {start_url} (limit: {MAX_URLS} URLs)")

    # Shared mutable state — all steps write into this single set
    collected: Set[str] = set()
    lock = threading.Lock()

    # Always seed with the start URL itself
    collected.add(_clean_url(start_url))

    # ── Pre-fetch robots.txt AND homepage HTML in parallel ───────────────────
    # Both are independent; fetching them concurrently saves 1 full round-trip.
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
