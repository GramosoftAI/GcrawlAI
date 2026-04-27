"""
Simple Markdown Scrape API
POST /scrape  — Give a URL, get back Markdown content. No DB, no artifacts, no WebSocket.
"""

import logging
import socket
from pathlib import Path
from typing import List, Literal, Optional
from urllib.parse import urlparse, urljoin

from fastapi import APIRouter, HTTPException
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/scrape", tags=["Scrape"])


# ─────────────────────────── Pydantic models ─────────────────────────

class ScrapedPage(BaseModel):
    url: str
    markdown: str


class ScrapeRequest(BaseModel):
    url: str = Field(..., description="Website URL to scrape")
    type: Literal["single", "all"] = Field(
        ...,
        description="single = 1 page, all = up to 10 pages"
    )
    proxymode: Literal["basic", "stealth", "enhanced"] = Field(
        "basic",
        description="Proxy tier: basic | stealth | enhanced"
    )


class ScrapeResponse(BaseModel):
    status: str = "success"
    url: str
    type: str
    proxymode: str
    pages_scraped: int
    data: List[ScrapedPage]


# ─────────────────────────── Core scrape logic ───────────────────────

def _scrape_single_page(url: str, proxy_settings: Optional[dict]) -> Optional[str]:
    """
    Open URL in a headless Chromium with stealth, grab HTML,
    convert to Markdown. Returns markdown text or None on failure.
    No DB, no artifacts, no Redis — pure in-memory.
    """
    from playwright.sync_api import sync_playwright
    from playwright_stealth import Stealth
    from web_crawler.crawler.content_processor import ContentProcessor

    processor = ContentProcessor()

    try:
        with sync_playwright() as p:
            launch_args = [
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
                "--disable-gpu",
            ]
            browser = p.chromium.launch(headless=True, args=launch_args)

            context_kwargs = dict(
                viewport={"width": 1920, "height": 1080},
                locale="en-US",
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/133.0.0.0 Safari/537.36"
                ),
                java_script_enabled=True,
                ignore_https_errors=True,
                bypass_csp=True,
                extra_http_headers={
                    "sec-ch-ua": '"Not(A:Brand";v="99", "Google Chrome";v="133"',
                    "sec-ch-ua-mobile": "?0",
                    "sec-ch-ua-platform": '"Windows"',
                },
            )
            if proxy_settings:
                context_kwargs["proxy"] = proxy_settings

            context = browser.new_context(**context_kwargs)

            # Apply stealth to avoid bot detection
            Stealth().apply_stealth_sync(context)

            page = context.new_page()

            try:
                response = page.goto(url, wait_until="domcontentloaded", timeout=60_000)

                if not response or response.status >= 400:
                    status = response.status if response else 0
                    logger.warning(f"HTTP {status} for {url}")
                    return None

                # Wait for dynamic content to load
                try:
                    page.wait_for_load_state("networkidle", timeout=10_000)
                except Exception:
                    pass  # networkidle is nice-to-have, not required

                # Scroll to trigger lazy-loading
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                page.wait_for_timeout(1500)

                html = page.content()

                # Convert HTML → Markdown (no DB, pure text)
                markdown = processor.convert_to_markdown(html, url)
                return markdown if markdown and len(markdown.strip()) > 100 else None

            finally:
                try:
                    page.close()
                except Exception:
                    pass
                try:
                    context.close()
                except Exception:
                    pass
                try:
                    browser.close()
                except Exception:
                    pass

    except Exception as e:
        logger.error(f"Browser scrape failed for {url}: {e}")
        return None


def _get_proxy_settings(proxymode: str) -> Optional[dict]:
    """
    Build Playwright proxy config from ENV vars based on proxy mode.
    Returns None if no proxy is configured.
    """
    import os
    from dotenv import load_dotenv
    from pathlib import Path as _Path

    load_dotenv(_Path(__file__).resolve().parent.parent / ".env", override=True)

    server = os.getenv("PROXY_SERVER") or os.getenv("EVOMI_PROXY_SERVER")
    username = os.getenv("PROXY_USERNAME") or os.getenv("EVOMI_PROXY_USERNAME")
    password = os.getenv("PROXY_PASSWORD") or os.getenv("EVOMI_PROXY_PASSWORD")

    if proxymode == "stealth":
        password = os.getenv("EVOMI_PROXY_PASSWORD_INDIA", password)
    elif proxymode == "enhanced":
        pw_us = os.getenv("PROXY_PASSWORD_US")
        if not pw_us and password:
            pw_us = f"{password}_country-US"
        password = pw_us or password

    if not server:
        return None

    proxy: dict = {"server": server}
    if username:
        proxy["username"] = username
    if password:
        proxy["password"] = password
    return proxy


def _collect_internal_links(html: str, base_url: str, max_links: int = 15) -> List[str]:
    """Extract unique internal links from an HTML page."""
    from bs4 import BeautifulSoup

    parsed_base = urlparse(base_url)
    base_host = parsed_base.netloc.lower()
    soup = BeautifulSoup(html, "lxml")
    seen = set()
    links = []

    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if not href or href.startswith(("#", "mailto:", "javascript:", "tel:")):
            continue
        full = urljoin(base_url, href)
        p = urlparse(full)
        if p.netloc.lower() != base_host:
            continue
        clean = f"{p.scheme}://{p.netloc}{p.path.rstrip('/') or '/'}"
        if clean not in seen:
            seen.add(clean)
            links.append(clean)
        if len(links) >= max_links:
            break

    return links


def _run_scrape_all(url: str, proxymode: str) -> List[ScrapedPage]:
    """
    Crawl up to 10 pages starting from `url`.
    Returns list of ScrapedPage objects with markdown text.
    """
    from playwright.sync_api import sync_playwright
    from playwright_stealth import Stealth
    from web_crawler.crawler.content_processor import ContentProcessor

    processor = ContentProcessor()
    proxy_settings = _get_proxy_settings(proxymode)
    MAX_PAGES = 10

    queue = [url]
    visited: set = set()
    results: List[ScrapedPage] = []

    while queue and len(results) < MAX_PAGES:
        current_url = queue.pop(0)
        if current_url in visited:
            continue
        visited.add(current_url)

        logger.info(f"Scraping [{len(results)+1}/{MAX_PAGES}]: {current_url}")

        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(
                    headless=True,
                    args=[
                        "--no-sandbox",
                        "--disable-setuid-sandbox",
                        "--disable-blink-features=AutomationControlled",
                        "--disable-dev-shm-usage",
                        "--disable-gpu",
                    ],
                )
                context_kwargs = dict(
                    viewport={"width": 1920, "height": 1080},
                    locale="en-US",
                    user_agent=(
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/133.0.0.0 Safari/537.36"
                    ),
                    java_script_enabled=True,
                    ignore_https_errors=True,
                    bypass_csp=True,
                )
                if proxy_settings:
                    context_kwargs["proxy"] = proxy_settings

                context = browser.new_context(**context_kwargs)
                Stealth().apply_stealth_sync(context)
                page = context.new_page()

                try:
                    response = page.goto(current_url, wait_until="domcontentloaded", timeout=60_000)
                    if not response or response.status >= 400:
                        continue

                    try:
                        page.wait_for_load_state("networkidle", timeout=8_000)
                    except Exception:
                        pass

                    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                    page.wait_for_timeout(1200)

                    html = page.content()
                    markdown = processor.convert_to_markdown(html, current_url)

                    if markdown and len(markdown.strip()) > 100:
                        results.append(ScrapedPage(url=current_url, markdown=markdown))

                        # Discover new links to crawl (only from first page to speed up)
                        if len(results) == 1:
                            new_links = _collect_internal_links(html, current_url)
                            for lnk in new_links:
                                if lnk not in visited:
                                    queue.append(lnk)

                finally:
                    try:
                        page.close()
                    except Exception:
                        pass
                    try:
                        context.close()
                    except Exception:
                        pass
                    try:
                        browser.close()
                    except Exception:
                        pass

        except Exception as e:
            logger.warning(f"Failed scraping {current_url}: {e}")
            continue

    return results


def _run_scrape_single(url: str, proxymode: str) -> List[ScrapedPage]:
    """Scrape one page and return a list with one ScrapedPage."""
    proxy_settings = _get_proxy_settings(proxymode)
    markdown = _scrape_single_page(url, proxy_settings)
    if markdown:
        return [ScrapedPage(url=url, markdown=markdown)]
    return []


# ─────────────────────────── Endpoint ────────────────────────────────

@router.post("", response_model=ScrapeResponse)
async def scrape_markdown(payload: ScrapeRequest):
    """
    Scrape a website and get the content as Markdown — no DB, no artifacts.

    | param | values | description |
    |-------|--------|-------------|
    | url | any URL | Website to scrape |
    | type | `single` / `all` | Single page or up to 10 pages |
    | proxymode | `basic` / `stealth` / `enhanced` | Proxy tier |
    """

    # ── 1. DNS check ──────────────────────────────────────────────────
    try:
        hostname = urlparse(
            payload.url if "://" in payload.url else f"https://{payload.url}"
        ).hostname
        if hostname:
            socket.gethostbyname(hostname)
    except socket.gaierror:
        raise HTTPException(
            status_code=400,
            detail=f"DNS lookup failed for '{hostname}'. Verify the URL is correct.",
        )

    # ── 2. Run scraper in thread (sync Playwright must not run in async) ──
    logger.info(f"Scrape request | url={payload.url} type={payload.type} proxy={payload.proxymode}")

    try:
        if payload.type == "single":
            scraped: List[ScrapedPage] = await run_in_threadpool(
                _run_scrape_single,
                url=payload.url,
                proxymode=payload.proxymode,
            )
        else:
            scraped = await run_in_threadpool(
                _run_scrape_all,
                url=payload.url,
                proxymode=payload.proxymode,
            )
    except Exception as e:
        logger.exception("Scrape endpoint error")
        raise HTTPException(status_code=500, detail=f"Scraping error: {str(e)}")

    # ── 3. Return result ──────────────────────────────────────────────
    if not scraped:
        raise HTTPException(
            status_code=422,
            detail=(
                "No markdown could be extracted from the page. "
                "The site likely uses bot protection (Akamai / Cloudflare). "
                f"Try proxymode='enhanced' (current: '{payload.proxymode}')."
            ),
        )

    return ScrapeResponse(
        status="success",
        url=payload.url,
        type=payload.type,
        proxymode=payload.proxymode,
        pages_scraped=len(scraped),
        data=scraped,
    )
