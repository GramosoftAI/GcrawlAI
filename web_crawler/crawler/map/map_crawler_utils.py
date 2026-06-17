import logging
from typing import Tuple, Optional, Any
from urllib.parse import urlparse
import primp

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
)

_SITEMAP_XML_NS = "{http://www.sitemaps.org/schemas/sitemap/0.9}"


# ── Internal helpers ─────────────────────────────────────────────────────────

def _get(
    url: str, 
    timeout: Tuple[int, int] = _SITEMAP_TIMEOUT,
    proxy_dict: Optional[dict] = None
) -> Optional[Any]:
    """Safe HTTP GET; returns None on any error."""
    try:
        proxy_url = None
        if proxy_dict:
            if "https" in proxy_dict:
                proxy_url = proxy_dict["https"]
            elif "http" in proxy_dict:
                proxy_url = proxy_dict["http"]

        # Parse connect and read timeouts
        conn_timeout = float(timeout[0]) if isinstance(timeout, (tuple, list)) else float(timeout)
        read_timeout = float(timeout[1]) if isinstance(timeout, (tuple, list)) else float(timeout)

        client = primp.Client(
            impersonate="chrome",
            proxy=proxy_url,
            connect_timeout=conn_timeout,
            read_timeout=read_timeout,
            verify=False
        )
        resp = client.get(url)
        if resp.status_code == 200:
            return resp
        logger.debug(f"HTTP {resp.status_code} for {url}")
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
