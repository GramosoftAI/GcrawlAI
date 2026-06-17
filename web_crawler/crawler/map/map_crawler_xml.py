import logging
import threading
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Optional, Set, Tuple
from urllib.parse import urlparse, urljoin
from bs4 import BeautifulSoup

from web_crawler.crawler.map.map_crawler_utils import (
    _get,
    _origin,
    _same_host,
    _clean_url,
    _is_page_url,
    _ROBOTS_TIMEOUT,
    _SITEMAP_TIMEOUT,
    _SITEMAP_XML_NS,
    MAX_URLS,
    _MAX_WORKERS,
)

logger = logging.getLogger(__name__)


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
