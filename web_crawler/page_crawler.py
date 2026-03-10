"""
Individual page crawling logic
"""

import logging
import asyncio
import sys
import json
import os
import re
import yaml
from typing import Optional, Dict
from pathlib import Path
from playwright.sync_api import sync_playwright, Page
from bs4 import BeautifulSoup
from web_crawler.seo_report import CrawlReportWriter
import platform

if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

from web_crawler.config import CrawlConfig
from web_crawler.file_manager import FileManager
from web_crawler.browser_utils import BrowserUtils
from web_crawler.content_processor import ContentProcessor
from web_crawler.websocket_manager import WebSocketManager
from web_crawler.utils import normalize_url
from web_crawler.redis_events import publish_event
from web_crawler.proxy_manager import ProxyManager


logger = logging.getLogger(__name__)


def _get_db_conn():
    """
    Open and return a short-lived, standalone psycopg2 connection.
    Reads config.yaml the same way _record_failed_page does.
    Raises on failure — callers should catch.
    """
    import psycopg2
    from dotenv import load_dotenv
    load_dotenv(override=True)

    config_path = Path(__file__).resolve().parent.parent / "config.yaml"

    def _substitute(data):
        if isinstance(data, dict):
            return {k: _substitute(v) for k, v in data.items()}
        if isinstance(data, str):
            def _rep(m):
                return os.getenv(m.group(1), m.group(2) or "")
            return re.sub(r'\$\{([^:}]+)(?::([^}]*))?\}', _rep, data)
        return data

    with open(config_path, "r") as f:
        cfg = _substitute(yaml.safe_load(f))

    db = cfg.get("postgres", {})
    return psycopg2.connect(
        host=db.get("host", "localhost"),
        port=db.get("port", 5432),
        database=db.get("database", "crawlerdb"),
        user=db.get("user", "postgres"),
        password=db.get("password", ""),
    )


def _record_failed_page(
    url: str,
    crawl_id: Optional[str],
    crawl_mode: str,
    page_number: int,
) -> None:
    """
    Insert a row into failed_crawl_pages when all browsers fail for a URL.
    Uses a short-lived, standalone psycopg2 connection so it is safe to call
    from background threads that do not share the main API connection pool.
    Silently logs and ignores any DB error to avoid masking the original failure.
    """
    conn = None
    try:
        conn = _get_db_conn()
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO failed_crawl_pages (crawl_id, url, crawl_mode, page_number)
            VALUES (%s, %s, %s, %s)
            """,
            (crawl_id, url, crawl_mode, page_number),
        )
        conn.commit()
        cur.close()
        logger.info(f"✓ Failure recorded in DB for: {url} (crawl_id={crawl_id})")
    except Exception as db_err:
        logger.warning(f"⚠ Could not record failed page in DB for {url}: {db_err}")
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass


def _persist_crawl_event(
    crawl_id: Optional[str],
    url: str,
    title: Optional[str],
    markdown_file: Optional[str],
    html_file: Optional[str],
    screenshot: Optional[str],
    seo_json: Optional[str],
    seo_md: Optional[str],
    seo_xlsx: Optional[str],
) -> None:
    """
    Persist a page_processed event directly into crawl_events.

    This is the source-of-truth write path for crawl events — it runs inside
    the crawler worker itself (not via the WebSocket handler) so events are
    always stored even when the frontend WebSocket connects after the crawl
    finishes (e.g. Celery all-mode crawls).

    Uses a short-lived standalone connection safe for background threads.
    Errors are logged and silently ignored so crawl output is never affected.
    """
    if not crawl_id:
        return
    conn = None
    try:
        conn = _get_db_conn()
        cur = conn.cursor()
        try:
            # Try INSERT first
            cur.execute(
                """
                INSERT INTO crawl_events
                    (crawl_id, event_type, url, title,
                     markdown_file, html_file, screenshot,
                     seo_json, seo_md, seo_xlsx)
                VALUES (%s, 'page_processed', %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (crawl_id, url, title,
                 markdown_file, html_file, screenshot,
                 seo_json, seo_md, seo_xlsx),
            )
            conn.commit()
        except Exception:
            # Row already exists — UPDATE the file paths instead
            conn.rollback()
            cur.execute(
                """
                UPDATE crawl_events SET
                    title         = %s,
                    markdown_file = %s,
                    html_file     = %s,
                    screenshot    = %s,
                    seo_json      = %s,
                    seo_md        = %s,
                    seo_xlsx      = %s
                WHERE crawl_id = %s AND url = %s
                """,
                (title, markdown_file, html_file, screenshot,
                 seo_json, seo_md, seo_xlsx,
                 crawl_id, url),
            )
            conn.commit()
        cur.close()
        logger.info(f"✓ crawl_events persisted for: {url} (crawl_id={crawl_id})")
    except Exception as db_err:
        logger.warning(f"⚠ Could not persist crawl event for {url}: {db_err}")
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass

class PageCrawler:
    """Handle individual page crawling"""
    
    def __init__(self, config: CrawlConfig, file_manager: FileManager):
        self.config = config
        self.file_manager = file_manager
        self.browser_utils = BrowserUtils()
        self.content_processor = ContentProcessor()
        self.proxy_manager = ProxyManager(
            proxies=config.proxy,
            basic_proxies=config.basic_proxies,
            stealth_proxies=config.stealth_proxies
        )

    def _resolve_playwright_proxy(self, proxy_type: str = "basic") -> Optional[Dict]:
        """
        Resolve proxy settings for Playwright contexts.
        Priority:
        1) Firecrawl-style BYOP env proxy (PROXY_SERVER/USERNAME/PASSWORD)
        2) Requested proxy type from rotating manager
        """
        byop_proxy = self.config.get_playwright_proxy()
        if byop_proxy:
            return byop_proxy

        return self.proxy_manager.get_playwright_proxy(proxy_type)
    
    def process_page(
        self,
        page: Page,
        url: str,
        count: int,
        enable_md: bool,
        enable_html: bool,
        enable_ss: bool,
        enable_seo: bool,
        client_id: Optional[str]
    ) -> Optional[Dict]:
        """Process loaded page and extract data"""
        md_path = None
        html_path = None
        screenshot_path = None
        seo_json_path = None
        seo_md_path = None
        seo_xlsx_path = None
        
        try:
            # Scroll to load dynamic content
            self.scroll_to_bottom(page)
            
            html = page.content()
            soup = BeautifulSoup(html, "lxml")
            seo = self.content_processor.extract_seo(soup, url)
            
            canonical_url = seo.get("canonical")
            canonical = normalize_url(canonical_url if canonical_url else url)
            
            title = seo.get("title")
            title_safe = self.file_manager.safe_filename(title if title else "page")
            prefix = f"{count}_{title_safe}"

            if enable_seo:
                try:
                    writer = CrawlReportWriter(self.config.output_dir)
                    seo_json_path = writer.save_single_json(prefix, seo)
                    seo_md_path = writer.save_single_markdown(prefix, seo)
                    seo_xlsx_path = writer.save_single_excel(prefix, seo)
                except Exception as e:
                    logger.error(f"Failed to save per-page SEO report for {url}: {e}")
            
            # Save HTML
            if enable_html:
                html_path = str(self.config.html_dir / f"{prefix}.html")
                try:
                    with open(html_path, "w", encoding="utf-8") as f:
                        f.write(html)
                except Exception as e:
                    logger.error(f"Failed to save HTML for {url}: {e}")
            
            # Save screenshot
            if enable_ss:
                screenshot_path = str(self.config.screenshot_dir / f"{prefix}.png")
                try:
                    page.screenshot(path=screenshot_path, full_page=True)
                except Exception as e:
                    logger.error(f"Failed to save screenshot for {url}: {e}")
            
            # Save markdown (per page file)
            if enable_md:
                try:
                    markdown = self.content_processor.convert_to_markdown(html, url)
                    # md_filename = f"{count}_{title_safe}.md"
                    # md_path = Path(self.config.output_dir) / md_filename
                    md_path = str(self.config.md_dir / f"{prefix}.md")
                    
                    with open(md_path, "w", encoding="utf-8") as f:
                        f.write(markdown)
                except Exception as e:
                    logger.error(f"Failed to save markdown for {url}: {e}")

            if client_id:
                publish_event(
                    crawl_id=client_id,
                    payload={
                        "type": "page_processed",
                        "page": count,
                        "url": url,
                        "title": seo.get("title", "No Title"),
                        "markdown_file": str(md_path) if md_path else None,
                        "html_file": html_path,
                        "screenshot": screenshot_path,
                        "seo_json": seo_json_path,
                        "seo_md": seo_md_path,
                        "seo_xlsx": seo_xlsx_path,
                    }
                )
                # Also persist directly to DB so /crawler/paths/ works even
                # when the WebSocket is not connected (e.g. Celery all-mode).
                _persist_crawl_event(
                    crawl_id=client_id,
                    url=url,
                    title=seo.get("title"),
                    markdown_file=str(md_path) if md_path else None,
                    html_file=html_path,
                    screenshot=screenshot_path,
                    seo_json=seo_json_path,
                    seo_md=seo_md_path,
                    seo_xlsx=seo_xlsx_path,
                )

            
            links = self.content_processor.extract_links(soup, url)
            
            logger.info(f"Successfully processed: {url}")
            
            return {
                "url": url,
                "canonical": canonical,
                "seo": seo,
                "html_file": html_path,
                "screenshot": screenshot_path,
                "markdown_file": str(md_path) if md_path else None,
                "links": links,
                "status_code": page.evaluate("() => window.performance.getEntries()[0].responseStatus") or 200,
            }
            
        except Exception as e:
            logger.error(f"Error processing page {url}: {e}")
            return {"url": url, "error": str(e), "status_code": 500}

    def is_captcha_page(self, text_content: str) -> bool:
        """Check if the page is a Google/Cloudflare CAPTCHA page"""
        if not text_content:
            return False
            
        text_lower = text_content.lower()
        captcha_markers = [
            "our systems have detected unusual traffic from your computer network",
            "please show you're not a robot",
            "to continue, please type the characters below",
            "about this page",
            "i'm not a robot",
            "pardon our interruption"
        ]
        
        if len(text_content.strip()) < 1500 and any(marker in text_lower for marker in captcha_markers):
            logger.warning("CAPTCHA detected on page content.")
            return True
        return False
    
    def crawl_with_chromium(
        self,
        url: str,
        count: int,
        enable_md: bool,
        enable_html: bool,
        enable_ss: bool,
        enable_seo: bool,
        client_id: Optional[str],
        proxy_type: str = "basic"
    ) -> Optional[Dict]:
        """Crawl page using Chromium with stealth"""
        try:
            proxy_settings = self._resolve_playwright_proxy()
            with sync_playwright() as p:
                browser = p.chromium.launch(
                    headless=self.config.headless,
                    args=[
                        '--no-sandbox',
                        '--disable-setuid-sandbox',
                        '--disable-infobars',
                        '--ignore-certificate-errors',
                        '--window-position=0,0',
                        '--window-size=1920,1080',
                        '--disable-blink-features=AutomationControlled',
                        '--disable-web-security',
                        '--disable-features=IsolateOrigins,site-per-process',
                        '--disable-dev-shm-usage',
                        '--disable-gpu',
                        '--disable-extensions',
                        '--disable-background-networking'
                    ]
                )
                
                context_kwargs = dict(
                    viewport={"width": 1920, "height": 1080},
                    locale='en-US',
                    # Fix 1: Updated to current Chrome version (133, Feb 2026)
                    user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36',
                    java_script_enabled=True,
                    ignore_https_errors=True,
                    bypass_csp=True,
                    extra_http_headers={
                        "sec-ch-ua": '"Not(A:Brand";v="99", "Google Chrome";v="133", "Chromium";v="133"',
                        "sec-ch-ua-mobile": "?0",
                        "sec-ch-ua-platform": '"Windows"'
                    }
                )
                if proxy_settings:
                    context_kwargs["proxy"] = proxy_settings

                context = browser.new_context(**context_kwargs)
                
                # Apply stealth at context level only (Fix 3: removed duplicate page-level stealth)
                from playwright_stealth import Stealth
                Stealth().apply_stealth_sync(context)
                
                page = context.new_page()
                self.browser_utils.inject_stealth_scripts(page)
                # Fix 3: stealth already applied at context level above — do NOT re-apply to page

                if self.config.use_custom_headers:
                    self.browser_utils.set_custom_headers(page)
                
                # Fix 2: Skip resource-blocking on protected domains (Google uses resources to fingerprint)
                if not self.browser_utils.is_protected_domain(url):
                    page.route("**/*", self.browser_utils.block_resources)
                
                try:
                    logger.info(f"Navigating to {url} (Chromium)...")
                    response = page.goto(url, wait_until="domcontentloaded", timeout=60_000)
                    logger.info(f"Response status: {response.status if response else 'None'}")
                    
                    if not response:
                        return {"url": url, "error": "No response", "status_code": 0}
                    
                    if not (200 <= response.status < 300):
                        return {"url": url, "error": f"HTTP {response.status}", "status_code": response.status}
                    
                    # Note: check_cloudflare needs a loaded page to work correctly
                    # self.browser_utils.check_cloudflare(page, self.config)
                    if not self.browser_utils.wait_for_ready(page):
                        return {"url": url, "error": "Page not ready", "status_code": 504}
                        
                    # Validate content
                    text_content = page.evaluate("document.body.innerText")
                    if self.is_captcha_page(text_content):
                        return {"url": url, "error": "CAPTCHA detected", "status_code": 403}
                        
                    if len(text_content.strip()) < 200:
                        return {"url": url, "error": f"Content too short ({len(text_content.strip())} chars)", "status_code": 422}
                    
                    result = self.process_page(page, url, count, enable_md, enable_html, enable_ss, enable_seo, client_id)
                    return result
                
                finally:
                    # Clean up routes before closing browser to prevent async TargetClosedError/CancelledError tracebacks
                    try:
                        if not self.browser_utils.is_protected_domain(url):
                            page.unroute("**/*")
                    except Exception:
                        pass
                    # Small wait to let pending routes settle before closing context
                    try:
                        page.wait_for_timeout(100)
                    except Exception:
                        pass
                        
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
            logger.warning(f"Chromium failed for {url}: {e}")
            return None
    
    def crawl_with_camoufox(
        self,
        url: str,
        count: int,
        enable_md: bool,
        enable_html: bool,
        enable_ss: bool,
        enable_seo: bool,
        client_id: Optional[str],
        proxy_type: str = "basic"
    ) -> Optional[Dict]:
        """Fallback crawl using Camoufox"""
        if not self.config.camoufox_path:
            logger.warning("Camoufox path not configured")
            return None
        
        try:
            proxy_settings = self._resolve_playwright_proxy()
            with sync_playwright() as p:
                if platform.system() == "Windows":
                    browser = p.firefox.launch(
                        executable_path=self.config.camoufox_path,
                        headless=self.config.headless
                    )
                else:
                    browser = p.firefox.launch(
                        headless=self.config.headless
                    )
                
                try:
                    context_kwargs = dict(
                        viewport={"width": 1920, "height": 1080},
                        locale='en-US',
                        # Fix 4: No user_agent override — let Camoufox (Firefox) present its native UA.
                        # Overriding with Chrome UA on a Firefox binary creates a contradictory fingerprint.
                        java_script_enabled=True,
                        ignore_https_errors=True,
                        bypass_csp=True
                    )
                    if proxy_settings:
                        context_kwargs["proxy"] = proxy_settings

                    context = browser.new_context(**context_kwargs)
                    
                    # Apply stealth at context level only (Fix 3: removed duplicate page-level stealth)
                    from playwright_stealth import Stealth
                    Stealth().apply_stealth_sync(context)
                    
                    page = context.new_page()
                    self.browser_utils.inject_stealth_scripts(page)
                    # Fix 3: stealth already applied at context level — do NOT re-apply to page

                    if self.config.use_custom_headers:
                        self.browser_utils.set_custom_headers(page)
                    
                    # Fix 2: Skip resource-blocking on protected domains (Google uses resources to fingerprint)
                    if not self.browser_utils.is_protected_domain(url):
                        page.route("**/*", self.browser_utils.block_resources)
                    
                    logger.info(f"Navigating to {url} (Camoufox)...")
                    response = page.goto(url, wait_until="domcontentloaded", timeout=60_000)
                    logger.info(f"Response status: {response.status if response else 'None'}")
                    
                    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                    page.wait_for_timeout(4000)
                    
                    if not response:
                        return {"url": url, "error": "No response", "status_code": 0}

                    if not (200 <= response.status < 300):
                        return {"url": url, "error": f"HTTP {response.status}", "status_code": response.status}
                    
                    if not self.browser_utils.wait_for_ready(page):
                        return {"url": url, "error": "Page not ready", "status_code": 504}
                        
                    text_content = page.evaluate("document.body.innerText")
                    if self.is_captcha_page(text_content):
                        logger.warning(f"Camoufox also hit CAPTCHA for {url}")
                        return {"url": url, "error": "CAPTCHA detected", "status_code": 403}
                    
                    result = self.process_page(page, url, count, enable_md, enable_html, enable_ss, enable_seo, client_id)
                    return result
                finally:
                    try:
                        if not self.browser_utils.is_protected_domain(url):
                            page.unroute("**/*")
                    except Exception:
                        pass
                    try:
                        page.wait_for_timeout(100)
                    except Exception:
                        pass
                        
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
            logger.error(f"Camoufox failed for {url}: {e}")
            return None
    
    def crawl_page(
        self,
        url: str,
        count: int,
        enable_md: bool,
        enable_html: bool,
        enable_ss: bool,
        enable_seo: bool,
        client_id: Optional[str],
        websocket_manager,
        crawl_mode: str = "all",
        proxy_type: str = "basic",
    ) -> Optional[Dict]:
        """Crawl a single page with fallback browsers"""
        logger.info(f"Crawling [{count}]: {url}")
        
        WebSocketManager.send_update(client_id, websocket_manager, {
            "type": "progress",
            "status": "starting",
            "url": url,
            "count": count
        })
        
        # Try Chromium first
        result = self.crawl_with_chromium(url, count, enable_md, enable_html, enable_ss, enable_seo, client_id, proxy_type)
        
        if result:
            logger.info(f"Chromium success: {url}")
            return result
    
        # Fallback to Camoufox
        logger.info(f"Trying Camoufox fallback for: {url}")
        result = self.crawl_with_camoufox(url, count, enable_md, enable_html, enable_ss, enable_seo, client_id, proxy_type)
        
        if result:
            logger.info(f"Camoufox success: {url}")
        else:
            logger.error(f"All browsers failed for: {url}")
            # Record the failure in the DB so operators can review it
            _record_failed_page(
                url=url,
                crawl_id=client_id,
                crawl_mode=crawl_mode,
                page_number=count,
            )
        
        return result

    def scroll_to_bottom(self, page, max_scrolls=10, wait_time=500):
        """
        Incrementally scroll page to trigger lazy loading
        """
        try:
            prev_height = -1
            for _ in range(max_scrolls):
                # Scroll in chunks
                page.mouse.wheel(0, 1000)
                page.wait_for_timeout(200)
                
                # Check if height changed
                curr_height = page.evaluate("document.body.scrollHeight")
                if curr_height == prev_height:
                    break
                prev_height = curr_height
                
                # Small wait between major chunks
                page.wait_for_timeout(wait_time)
                
            # Final ensure bottom
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            page.wait_for_timeout(wait_time)
            
        except Exception as e:
            logger.warning(f"Scroll failed: {e}")
