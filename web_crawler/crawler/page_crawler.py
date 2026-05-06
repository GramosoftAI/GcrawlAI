"""
Individual page crawling logic
"""

import logging
import asyncio
import sys
import json
import os
import re
import random
import yaml

# Monkeypatch yaml for environments where CLoader/CDumper are missing (e.g. Python 3.14 on Mac)
if not hasattr(yaml, "CLoader"):
    yaml.CLoader = yaml.Loader
if not hasattr(yaml, "CDumper"):
    yaml.CDumper = yaml.Dumper

from typing import Optional, Dict
from pathlib import Path
from playwright.sync_api import sync_playwright, Page
import io
from PIL import Image
from bs4 import BeautifulSoup
from web_crawler.crawler.seo_report import CrawlReportWriter
import platform

if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

from web_crawler.common.config import CrawlConfig
from web_crawler.crawler.file_manager import FileManager
from web_crawler.crawler.browser_utils import BrowserUtils
from web_crawler.crawler.content_processor import ContentProcessor
from web_crawler.crawler.websocket_manager import WebSocketManager
from web_crawler.common.utils import normalize_url
from web_crawler.common.redis_events import publish_event
from web_crawler.common.proxy_manager import ProxyManager
from web_crawler.common.artifact_store import upsert_crawl_artifact
import base64
from dotenv import load_dotenv



logger = logging.getLogger(__name__)


def _get_db_conn():
    """
    Open and return a short-lived, standalone psycopg2 connection.
    Reads config.yaml the same way _record_failed_page does.
    Raises on failure — callers should catch.
    """
    import psycopg2
    BASE_DIR = Path(__file__).resolve().parent.parent.parent
    dotenv_path = BASE_DIR / '.env'
    load_dotenv(dotenv_path, override=True)


    config_path = BASE_DIR / "config.yaml"

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


def _move_human(page: Page, x: int, y: int):
    """
    Simulate human-like mouse movement to target coordinates.
    Uses Playwright's built-in interpolation for basic realism.
    """
    try:
        # Move mouse in human-like steps
        steps = random.randint(5, 15)
        page.mouse.move(x, y, steps=steps)
    except Exception:
        pass


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
        
        # Trigger email notification for total failure
        _send_crawl_error_notification(
            crawl_id=crawl_id,
            url=url,
            error_source="crawler_total_failure",
            reason=f"All tiers/browsers failed for this URL (Mode: {crawl_mode})",
            blocked_message=None
        )
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
    images: Optional[str] = None,
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
                     seo_json, seo_md, seo_xlsx, images)
                VALUES (%s, 'page_processed', %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (crawl_id, url, title,
                 markdown_file, html_file, screenshot,
                 seo_json, seo_md, seo_xlsx, images),
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
                    seo_xlsx      = %s,
                    images        = %s
                WHERE crawl_id = %s AND url = %s
                """,
                (title, markdown_file, html_file, screenshot,
                 seo_json, seo_md, seo_xlsx, images,
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


def _store_crawl_artifact(
    crawl_id: Optional[str],
    artifact_type: str,
    content,
    *,
    content_kind: str = "text",
    page_url: Optional[str] = None,
    title: Optional[str] = None,
) -> Optional[str]:
    """
    Helper to store a crawl artifact in the database via the common artifact store.
    Returns the artifact ref (artifact://UUID) or None on failure.
    """
    if not crawl_id or content is None:
        return None

    conn = None
    try:
        conn = _get_db_conn()
        artifact_ref = upsert_crawl_artifact(
            conn,
            crawl_id=crawl_id,
            page_url=page_url,
            artifact_type=artifact_type,
            content=content,
            content_kind=content_kind,
            title=title,
        )
        conn.commit()
        return artifact_ref
    except Exception as db_err:
        logger.warning(
            f"⚠ Could not persist crawl artifact '{artifact_type}' for {page_url or crawl_id}: {db_err}"
        )
        return None
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass


def _record_crawl_error(
    crawl_id: Optional[str],
    url: str,
    error_source: str,
    reason: str,
    blocked_message: Optional[str] = None,
) -> None:
    """
    Insert a row into crawl_errors table.
    """
    if not crawl_id:
        return
    conn = None
    try:
        conn = _get_db_conn()
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO crawl_errors (crawl_id, url, error_source, reason, blocked_message)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (crawl_id, url, error_source, reason, blocked_message),
        )
        conn.commit()
        cur.close()
        logger.info(f"✓ Crawl error ({error_source}) recorded in DB for: {url}")
        
        # Also trigger email notification
        _send_crawl_error_notification(crawl_id, url, error_source, reason, blocked_message)
        
    except Exception as db_err:
        logger.warning(f"⚠ Could not record crawl error in DB for {url}: {db_err}")
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass

# List of admin emails to notify on crawl errors
ADMIN_EMAILS = ['jeevae@gramosoft.in']


def _send_crawl_error_notification(
    crawl_id: str,
    url: str,
    error_source: str,
    reason: str,
    blocked_message: Optional[str] = None,
) -> None:
    """
    Send an email notification for a crawl error.
    """
    try:
        from api.email_service import EmailService
        
        # Load config to get SMTP settings and admin email
        BASE_DIR = Path(__file__).resolve().parent.parent.parent
        config_path = BASE_DIR / "config.yaml"
        
        def _substitute(data):
            if isinstance(data, dict):
                return {k: _substitute(v) for k, v in data.items()}
            if isinstance(data, str):
                def _rep(m):
                    return os.getenv(m.group(1), m.group(2) or "")
                return re.sub(r'\$\{([^:}]+)(?::([^}]*))?\}', _rep, data)
            return data

        if not config_path.exists():
            logger.warning(f"Configuration file not found: {config_path}")
            return

        with open(config_path, "r") as f:
            cfg = _substitute(yaml.safe_load(f))
            
        smtp_cfg = cfg.get("email", {})
        
        # Ensure .env is loaded to get latest ADMIN_EMAIL
        BASE_DIR = Path(__file__).resolve().parent.parent.parent
        load_dotenv(BASE_DIR / ".env", override=True)
        
        # Get recipients from env or fallback to hardcoded list
        env_admin_email = os.getenv("ADMIN_EMAIL")
        if env_admin_email:
            # Handle possible list-like string format from .env: ['a', 'b'] -> a, b
            cleaned = env_admin_email.strip().strip("[]").replace("'", "").replace('"', "")
            recipients = [e.strip() for e in cleaned.split(",") if e.strip()]
        else:
            recipients = ADMIN_EMAILS

        
        if not smtp_cfg:
            logger.warning("Email configuration not found in config.yaml")
            return

        email_service = EmailService(smtp_cfg)
        for recipient in recipients:
            logger.info(f"Sending crawl error notification to {recipient}...")
            email_service.send_crawl_error_email(
                to_email=recipient,
                crawl_id=crawl_id,
                url=url,
                error_source=error_source,
                reason=reason,
                blocked_message=blocked_message
            )

    except Exception as e:
        logger.warning(f"⚠ Could not send crawl error email: {e}")


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
            stealth_proxies=config.stealth_proxies,
            enhanced_proxies=config.enhanced_proxies,
        )

    def _is_likely_proxy_failure(self, result: Optional[Dict]) -> bool:
        """Detect if the failure was likely due to a proxy block or network error."""
        if not result:
            return True

        status_code = result.get("status_code")
        if status_code in {401, 403, 407, 429, 502, 503, 504}:
            return True

        err = str(result.get("error", "")).lower()
        proxy_markers = [
            "proxy",
            "forbidden",
            "access denied",
            "too many requests",
            "captcha",
            "rate limit",
            "cloudflare",
        ]
        return any(marker in err for marker in proxy_markers)

    def _resolve_playwright_proxy(self, proxy_tier: int = 1) -> Optional[Dict]:
        """
        Resolve proxy settings for Playwright contexts.
        Priority:
        1) Firecrawl-style BYOP env proxy (PROXY_SERVER/USERNAME/PASSWORD)
        2) Requested Tier (1-7) from ProxyManager
        """
        if proxy_tier == 1:
            return None # Tier 1 is Direct

        byop_proxy = self.config.get_playwright_proxy()
        if byop_proxy:
            return byop_proxy

        return self.proxy_manager.get_playwright_proxy(tier=proxy_tier)
    
    def process_page(
        self,
        page: Page,
        url: str,
        count: int,
        enable_md: bool,
        enable_html: bool,
        enable_ss: bool,
        enable_seo: bool,
        enable_images: bool,
        client_id: Optional[str]
    ) -> Optional[Dict]:
        """Process loaded page and extract data"""
        md_path = None
        html_path = None
        screenshot_path = None
        seo_json_path = None
        seo_md_path = None
        seo_xlsx_path = None
        images_path = None
        
        try:
            # Scroll to load dynamic content
            self.scroll_to_bottom(page)
            
            html = page.content()
            soup = BeautifulSoup(html, "lxml")
            seo = self.content_processor.extract_seo(soup, url)
            
            canonical_url = seo.get("canonical")
            canonical = normalize_url(canonical_url if canonical_url else url)
            
            title = seo.get("title")
            
            if enable_seo:
                try:
                    writer = CrawlReportWriter(self.config.output_dir)
                    
                    seo_json_content = writer.render_single_json(seo)
                    seo_json_path_artifact = _store_crawl_artifact(
                        client_id,
                        "seo_json",
                        seo_json_content,
                        content_kind="text",
                        page_url=url,
                        title=title,
                    )
                    
                    seo_md_content = writer.render_single_markdown(seo)
                    seo_md_path_artifact = _store_crawl_artifact(
                        client_id,
                        "seo_md",
                        seo_md_content,
                        content_kind="text",
                        page_url=url,
                        title=title,
                    )
                    
                    seo_xlsx_content = writer.render_single_excel_base64(seo)
                    seo_xlsx_path_artifact = _store_crawl_artifact(
                        client_id,
                        "seo_xlsx",
                        seo_xlsx_content,
                        content_kind="binary",
                        page_url=url,
                        title=title,
                    )
                    
                    os.makedirs(self.config.seo_dir, exist_ok=True)
                    
                    local_seo_json = self.config.seo_dir / f"seo_{count}.json"
                    with open(local_seo_json, "w", encoding="utf-8") as f:
                        f.write(seo_json_content)
                    seo_json_path = str(local_seo_json)
                    
                    local_seo_md = self.config.seo_dir / f"seo_{count}.md"
                    with open(local_seo_md, "w", encoding="utf-8") as f:
                        f.write(seo_md_content)
                    seo_md_path = str(local_seo_md)
                    
                    local_seo_xlsx = self.config.seo_dir / f"seo_{count}.xlsx"
                    with open(local_seo_xlsx, "wb") as f:
                        f.write(base64.b64decode(seo_xlsx_content))
                    seo_xlsx_path = str(local_seo_xlsx)
                    
                except Exception as e:
                    logger.error(f"Failed to save per-page SEO report for {url}: {e}")
                    _record_crawl_error(client_id, url, "seo", "SEO report generation failed", str(e))
            
            # Save HTML
            if enable_html:
                try:
                    html_path_artifact = _store_crawl_artifact(
                        client_id,
                        "html",
                        html,
                        content_kind="text",
                        page_url=url,
                        title=title,
                    )
                    
                    

                    os.makedirs(self.config.html_dir, exist_ok=True)
                    local_html_path = self.config.html_dir / f"page_{count}.html"
                    with open(local_html_path, "w", encoding="utf-8") as f:
                        f.write(html)
                    html_path = str(local_html_path)
                except Exception as e:
                    logger.error(f"Failed to save HTML for {url}: {e}")
                    _record_crawl_error(client_id, url, "html", "Failed to save HTML", str(e))
            
            # Save markdown (per page file)
            if enable_md:
                try:
                    markdown = self.content_processor.convert_to_markdown(html, url)
                    md_path_artifact = _store_crawl_artifact(
                        client_id,
                        "markdown",
                        markdown,
                        content_kind="text",
                        page_url=url,
                        title=title,
                    )
                    
                    os.makedirs(self.config.md_dir, exist_ok=True)
                    local_md_path = self.config.md_dir / f"page_{count}.md"
                    with open(local_md_path, "w", encoding="utf-8") as f:
                        f.write(markdown)
                    md_path = str(local_md_path)
                except Exception as e:
                    logger.error(f"Failed to save markdown for {url}: {e}")
                    _record_crawl_error(client_id, url, "markdown", "Failed to save markdown", str(e))
            
            # Save screenshot
            if enable_ss:
                try:
                    screenshot_bytes = self._capture_robust_screenshot(page)
                    if not screenshot_bytes:
                        raise ValueError("Screenshot data is empty")
                    screenshot_b64 = base64.b64encode(screenshot_bytes).decode("utf-8")
                    
                    screenshot_path_artifact = _store_crawl_artifact(
                        client_id,
                        "screenshot",
                        screenshot_b64,
                        content_kind="binary",
                        page_url=url,
                        title=title,
                    )
                    
                    os.makedirs(self.config.screenshot_dir, exist_ok=True)
                    local_ss_path = self.config.screenshot_dir / f"page_{count}.png"
                    with open(local_ss_path, "wb") as f:
                        f.write(screenshot_bytes)
                    screenshot_path = str(local_ss_path)
                except Exception as e:
                    logger.error(f"Failed to save screenshot for {url}: {e}")
                    _record_crawl_error(client_id, url, "screenshot", "Screenshot not generated", str(e))

            # Save Images JSON
            if enable_images:
                try:
                    image_urls = self.content_processor.extract_image_urls(soup, url)
                    images_path_artifact = _store_crawl_artifact(
                        client_id,
                        "images",
                        image_urls,
                        content_kind="json",
                        page_url=url,
                        title=title,
                    )
                    
                    
                    local_images_path = Path(self.config.output_dir) / f"images_{count}.json"
                    with open(local_images_path, "w", encoding="utf-8") as f:
                        json.dump(image_urls, f, indent=2)
                    images_path = str(local_images_path)
                except Exception as e:
                    logger.error(f"Failed to save images JSON for {url}: {e}")
                    _record_crawl_error(client_id, url, "image", "Failed to extract images", str(e))

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
                        "images": images_path,
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
                    images=images_path,
                )

            
            try:
                links = self.content_processor.extract_links(soup, url)
            except Exception as e:
                logger.error(f"Failed to extract links for {url}: {e}")
                _record_crawl_error(client_id, url, "links", "Link extraction failed", str(e))
                links = []
            
            logger.info(f"Successfully processed: {url}")
            
            return {
                "url": url,
                "canonical": canonical,
                "seo": seo,
                "html_file": html_path,
                "screenshot": screenshot_path,
                "markdown_file": str(md_path) if md_path else None,
                "seo_json": seo_json_path,
                "seo_md": seo_md_path,
                "seo_xlsx": seo_xlsx_path,
                "images": images_path,
                "links": links,
                "status_code": page.evaluate("() => window.performance.getEntries()[0].responseStatus") or 200,
            }
            
        except Exception as e:
            err_msg = str(e)
            status_code = 500
            if "Timeout" in err_msg:
                status_code = 0
            elif "NS_ERROR_PROXY_BAD_GATEWAY" in err_msg or "ERR_PROXY_CONNECTION_FAILED" in err_msg:
                status_code = 502
            
            logger.error(f"Error processing page {url}: {err_msg}")
            return {"url": url, "error": err_msg, "status_code": status_code}

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
        enable_images: bool,
        client_id: Optional[str],
        proxy_tier: int = 2
    ) -> Optional[Dict]:
        """Crawl page using Chromium with stealth"""
        try:
            proxy_settings = self._resolve_playwright_proxy(proxy_tier)
            with sync_playwright() as p:
                browser = p.chromium.launch(
                    headless=self.config.headless,
                    proxy={"server": "http://per-context"} if proxy_settings else None,
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

                # Define nav_timeout and search mobile persona
                nav_timeout = 90_000 if proxy_tier > 2 else 60_000
                if "google.com/search" in url and proxy_tier > 2:
                    mobile_ua = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Mobile/15E148 Safari/604.1"
                    context_kwargs["user_agent"] = mobile_ua
                    context_kwargs["viewport"] = {"width": 390, "height": 844}
                    context_kwargs["is_mobile"] = True
                    context_kwargs["has_touch"] = True

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
                    response = page.goto(url, wait_until="domcontentloaded", timeout=nav_timeout)
                    logger.info(f"Response status: {response.status if response else 'None'}")
                    
                    if not response:
                        return {"url": url, "error": "No response", "status_code": 0}
                    
                    if not (200 <= response.status < 300):
                        return {"url": url, "error": f"HTTP {response.status}", "status_code": response.status}
                    
                    # For high-sec sites, perform human activity loop
                    high_sec_sites = ["meesho", "expedia", "zillow", "axs", "southwest", "delta"]
                    if any(s in url.lower() for s in high_sec_sites):
                        logger.info(f"High-security site detected, performing extended 15s human activity loop (Chromium)...")
                        for _ in range(3):
                            tx, ty = random.randint(200, 1000), random.randint(200, 800)
                            _move_human(page, tx, ty)
                            if random.random() > 0.7:
                                page.mouse.wheel(0, random.randint(100, 300))
                            page.wait_for_timeout(random.randint(3000, 5000))
                    
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
                    
                    result = self.process_page(page, url, count, enable_md, enable_html, enable_ss, enable_seo, enable_images, client_id)
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
        enable_images: bool,
        client_id: Optional[str],
        proxy_tier: int = 2
    ) -> Optional[Dict]:
        """Fallback crawl using Camoufox"""
        if not self.config.camoufox_path:
            logger.warning("Camoufox path not configured")
            return None
        
        try:
            proxy_settings = self._resolve_playwright_proxy(proxy_tier)
            
            # POC PARITY: Exact Stealth Site Lists
            high_sec_sites = [
                "meesho", "delta.com", "jal.co.jp", "united.com", "saint-gobain", 
                "jobrapido", "mister-auto", "ubaldi", "mansueto", "seloger",
                "oracle.com", "expedia.com", "luisaviaroma.com", "lufthansa.com",
                "emirates.com", "citigroup.com", "wellsfargo.com", "homedepot.com",
                "lowes.com", "rakuten.com", "footlocker.com", "att.com", "booking.com",
                "chewy.com", "autozone.com", "comcast.com", "creditagricole.fr",
                "cvs.com", "indeed.com", "jdsports.com", "jimmyjazz.com",
                "kohls.com", "laredoute.fr", "letseat.at", "neimanmarcus.com",
                "palace-skateboards.com", "rakuten.fr", "size.co.uk",
                "supremenewyork.com", "wayfair.com", "zillow.com"
            ]
            
            mobile_target_sites = [
                "expedia.com", "luisaviaroma.com", "oracle.com", "chewy.com",
                "autozone.com", "indeed.com", "zillow.com", "wayfair.com"
            ]
            
            use_mobile = any(site in url.lower() for site in mobile_target_sites) and proxy_tier >= 3
            is_high_sec = any(site in url.lower() for site in high_sec_sites)
            
            with sync_playwright() as p:
                logger.info(f"Setting up Camoufox (sync) for: {url}")
                from camoufox.sync_api import NewBrowser
                
                browser = NewBrowser(
                    p,
                    headless=self.config.headless,
                    os="windows",
                    block_webrtc=True,
                )
                
                try:
                    # POC Parity: Dynamic Geo/TZ/Locale
                    target_tz = "America/New_York"
                    target_locale = "en-US"
                    target_geo = {"latitude": 40.7128, "longitude": -74.0060} 
                    
                    if proxy_tier in [3, 5, 7]:
                        target_tz = "Asia/Kolkata"
                        target_geo = {"latitude": 19.0760, "longitude": 72.8777} # Mumbai
                    
                    logger.info(f"[Stealth Layer] Engine initialization: Camoufox fingerprint evasion active.")
                    logger.info(f"[Stealth Layer] Browser Identity: Platform={'Mobile' if use_mobile else 'Desktop'}, Viewport={'390x844' if use_mobile else '1920x1080'}, Locale={target_locale}, TZ={target_tz}")

                    context_kwargs = dict(
                        viewport={"width": 1920, "height": 1080} if not use_mobile else {"width": 390, "height": 844},
                        locale=target_locale,
                        timezone_id=target_tz,
                        geolocation=target_geo,
                        permissions=["geolocation", "notifications"],
                        java_script_enabled=True,
                        ignore_https_errors=True,
                        bypass_csp=True,
                        color_scheme="light"
                    )
                    
                    if use_mobile:
                        context_kwargs["user_agent"] = "Mozilla/5.0 (iPhone; CPU iPhone OS 15_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/15.0 Mobile/15E148 Safari/604.1"
                    
                    if proxy_settings:
                        context_kwargs["proxy"] = proxy_settings

                    context = browser.new_context(**context_kwargs)
                    
                    # POC Parity: Referer Spoofing
                    extra_headers = {}
                    if is_high_sec:
                        domain_name = next((s for s in high_sec_sites if s in url.lower()), "site")
                        extra_headers["Referer"] = f"https://www.google.com/search?q={domain_name}+official+store&oq={domain_name}"
                        logger.info(f"[Stealth Layer] Network Identity: Applying deep referer spoofing and Sec-Fetch headers.")
                    else:
                        extra_headers["Referer"] = "https://www.google.com/"
                    
                    context.set_extra_http_headers(extra_headers)
                    
                    page = context.new_page()
                    
                    # POC Parity: Initial Mouse Movement
                    import random
                    import time
                    logger.info("[Stealth Layer] Behavioral Simulation: Executing initial human-like mouse trajectories.")
                    page.mouse.move(random.randint(100, 500), random.randint(100, 500))
                    
                    # POC Parity: Warm-up Navigation
                    if is_high_sec:
                        from urllib.parse import urlparse
                        parsed = urlparse(url)
                        warmup_url = f"{parsed.scheme}://{parsed.netloc}/"
                        logger.info(f"Warm-up navigation (Cookie Seeding) for: {warmup_url}")
                        logger.info("[Stealth Layer] Cookie/Session Validation: Initiating request to generate security tokens.")
                        try:
                            page.goto(warmup_url, wait_until="domcontentloaded", timeout=25000)
                            time.sleep(random.uniform(4, 8))
                            # Log cookie status
                            cookies = context.cookies()
                            abck = [c for c in cookies if c['name'] == '_abck']
                            logger.info(f"[COOKIE CHECK] _abck={'FOUND len:' + str(len(abck[0]['value'])) if abck else 'MISSING'}")
                        except Exception as e:
                            logger.debug(f"Warm-up failed: {e}")

                    # Target Navigation
                    logger.info(f"Navigating to target URL: {url} (Tier {proxy_tier})")
                    response = page.goto(url, wait_until="domcontentloaded", timeout=60000)
                    status_code = response.status if response else 0
                    logger.info(f"Navigation completed. Status: {status_code}")
                    
                    # POC Parity: 15s Human Activity Loop
                    if is_high_sec or status_code in [403, 429]:
                        logger.info(f"High-sec site detected, performing human activity loop (15s)...")
                        for _ in range(3):
                            page.mouse.move(random.randint(200, 1000), random.randint(200, 800))
                            if random.random() > 0.7:
                                page.mouse.wheel(0, random.randint(50, 150))
                            time.sleep(random.uniform(3, 5))
                    
                    # POC Parity: Block Detection (Partial Content)
                    html_content = page.content()
                    check_content = html_content[:5000].lower()
                    title = page.title().lower()
                    
                    block_keywords = [
                        "access denied", "blocked", "captcha", "security check", 
                        "bot detection", "robot check", "verify your identity",
                        "human side", "distil networks", "incapsula", "perimeterx",
                        "fw_error_www", "bot or not", "proxy authentication required",
                        "refusing connections", "pardon our interruption"
                    ]
                    
                    is_blocked = any(kw in title for kw in block_keywords) or \
                                 any(kw in check_content for kw in block_keywords) or \
                                 (status_code in [403, 429])
                    
                    if is_blocked:
                         logger.warning(f"[Stealth Layer] Block page detected (Title: {page.title()}, Status: {status_code}).")
                         return {"url": url, "error": f"HTTP {status_code} - Blocked", "status_code": status_code}
                    
                    logger.info("[Stealth Layer] JS Rendering: Stabilizing dynamic elements before extraction.")
                    result = self.process_page(page, url, count, enable_md, enable_html, enable_ss, enable_seo, enable_images, client_id)
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
                        browser.close() # Playwright browser instance uses .close()
                    except Exception:
                        pass
                
        except Exception as e:
            logger.error(f"Camoufox failed for {url}: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return None
    
    def crawl_page(
        self,
        url: str,
        count: int,
        enable_md: bool,
        enable_html: bool,
        enable_ss: bool,
        enable_seo: bool,
        enable_images: bool,
        client_id: Optional[str],
        websocket_manager,
        crawl_mode: str = "all",
        proxy_type: str = "basic",
    ) -> Optional[Dict]:
        """Crawl a single page with fallback browsers"""
        logger.info(f"Crawling [{count}]: {url}")
        
        if client_id:
            publish_event(
                crawl_id=client_id,
                payload={
                    "type": "progress",
                    "status": "starting",
                    "url": url,
                    "count": count
                }
            )

        
        # Legacy mapping for API compatibility
        requested_proxy_type = (proxy_type or "auto").strip().lower()
        
        # Start from Tier 1 (No Proxy) by default for sequential escalation
        # unless specifically requested otherwise.
        if requested_proxy_type == "none":
            start_tier = 1
        elif requested_proxy_type == "auto":
            start_tier = 1
        else:
            # If they picked basic/stealth/etc, start from there
            if requested_proxy_type == "basic":
                start_tier = 2
            elif requested_proxy_type == "stealth":
                start_tier = 3
            elif requested_proxy_type == "enhanced":
                start_tier = 4
            else:
                start_tier = 1
            
        is_auto = True # Force escalation for all modes to ensure success

        # Multi-Tier browser orchestration (Camoufox for Tiers 1-5, Chromium for Tiers 6-7)
        current_tier = start_tier
        result = None
        failure_recorded = False

        while current_tier <= 7:
            logger.info("\n" + "="*30 + f"\nTier {current_tier} - Processing\n" + "="*30)
            
            if current_tier < 6:
                result = self.crawl_with_camoufox(
                    url, count, enable_md, enable_html, enable_ss, enable_seo, enable_images, client_id, current_tier
                )
                browser_name = "Camoufox"
            else:
                result = self.crawl_with_chromium(
                    url, count, enable_md, enable_html, enable_ss, enable_seo, enable_images, client_id, current_tier
                )
                browser_name = "Chromium"

            if result and "error" not in result:
                logger.info("\n" + "="*30 + f"\nTier {current_tier} - Success\n" + "="*30)
                logger.info(f"{browser_name} success with Tier {current_tier}: {url}")
                return result

            # If it failed, try the next tier (always escalating up to 7 for max success)
            logger.warning("\n" + "="*30 + f"\nTier {current_tier} - Failed\n" + "="*30)
            if current_tier < 7:
                logger.warning(f"{browser_name} failed with Tier {current_tier} (Error: {result.get('error') if result else 'Unknown'}). Escalating to Tier {current_tier + 1}...")
                current_tier += 1
            else:
                break
                
        logger.error(f"All browsers and tiers failed for: {url}")
        _record_failed_page(
            url=url,
            crawl_id=client_id,
            crawl_mode=crawl_mode,
            page_number=count,
        )
        
        return result

    def scroll_to_bottom(self, page):
        """
        Incrementally scroll page to trigger lazy loading.
        Uses a slow auto-scroll technique to ensure all content is loaded.
        """
        try:
            logger.info("Starting slow auto-scroll to load dynamic content...")
            page.evaluate("""
                async () => {
                    await new Promise((resolve) => {
                        let totalHeight = 0;
                        let distance = 500; 
                        let timer = setInterval(() => {
                            let scrollHeight = document.body.scrollHeight;
                            // Adding small random jitter to look more human
                            let jitter = Math.floor(Math.random() * 20);
                            window.scrollBy(0, distance + jitter);
                            totalHeight += distance;

                            if(totalHeight >= scrollHeight || totalHeight > 15000){
                                clearInterval(timer);
                                resolve();
                            }
                        }, 200); 
                    });
                }
            """)
            # Give Southwest and other heavy sites significant time to load images
            page.wait_for_timeout(3000)
        except Exception as e:
            logger.warning(f"Scroll failed: {e}")

    def _handle_popups_and_overlays(self, page: Page):
        """Hide common popups and cookie banners using a non-destructive stealth approach."""
        try:
            # 1. Wait for skeleton loaders to disappear
            try:
                page.wait_for_function("""
                    () => {
                        const skeletons = document.querySelectorAll('[class*="skeleton"], [class*="loading-shimmer"], .shimmer');
                        return skeletons.length === 0;
                    }
                """, timeout=5000)
            except Exception:
                pass 

            # 2. Hide common sticky overlays without clicking anything
            page.evaluate("""
                () => {
                    const selectorsToHide = [
                        '#onetrust-banner-sdk', '.ot-sdk-container', '#didomi-notice', 
                        '#cookie-banner', '.cookie-banner', '[id*="cookie"]', '[class*="cookie"]',
                        '.modal-backdrop', '.modal-open', '.fade.in',
                        '.bx-row-submit-button', '#newsletter-popup',
                        '[id^="sp_message_container"]', '.sp_veil'
                    ];
                    
                    selectorsToHide.forEach(s => {
                        document.querySelectorAll(s).forEach(el => {
                            // SAFETY: Don't hide the main content wrappers, headers, or navs
                            if (['BODY', 'HTML', 'HEADER', 'NAV'].includes(el.tagName)) return;
                            if (['app', 'root', 'main-content', 'header', 'nav'].includes(el.id)) return;
                            
                            // Hide via opacity/display to be non-destructive
                            el.style.display = 'none';
                        });
                    });
                }
            """)
            page.wait_for_timeout(500)
            
        except Exception as e:
            logger.debug(f"Popup handling failed: {e}")

    def _capture_robust_screenshot(self, page: Page) -> bytes:
        """
        Capture full page screenshot using a robust merging technique to avoid blank areas.
        Falls back to native full_page screenshot if the page is reasonably short.
        """
        try:
            # 1. Hide Overlays and cookie banners
            self._handle_popups_and_overlays(page)
            
            # 2. Get viewport and total height
            viewport = page.viewport_size
            current_width = viewport["width"] if viewport else 1920
            current_height = viewport["height"] if viewport else 1080
            
            # Ensure we are at the top to measure and capture correctly
            page.evaluate("window.scrollTo(0, 0)")
            total_height = page.evaluate("Math.max(document.scrollingElement.scrollHeight, document.body.scrollHeight, 1000)")
            
            # 3. If short page, just do native full_page
            if total_height < current_height * 2:
                page.evaluate("window.scrollTo(0, 0)")
                page.wait_for_timeout(1000)
                return page.screenshot(full_page=True)

            # 4. Ultra-Stealth: Expand Viewport to force React/Vue rendering
            target_height = min(total_height, 12000) 
            page.set_viewport_size({"width": current_width, "height": target_height})
            
            # 5. Trigger Resize/Scroll events and eagerly load all images
            page.evaluate("""
                async () => {
                    window.dispatchEvent(new Event('resize'));
                    window.scrollBy(0, 10);
                    await new Promise(r => setTimeout(r, 100));
                    window.scrollBy(0, -10);
                    
                    // Force eager loading for all images
                    document.querySelectorAll('img').forEach(img => {
                        img.setAttribute('loading', 'eager');
                        // Handle data-src/lazy-src common attributes
                        const lazyAttr = img.getAttribute('data-src') || img.getAttribute('lazy-src') || img.getAttribute('data-lazy');
                        if (lazyAttr && !img.src.includes(lazyAttr)) {
                            img.src = lazyAttr;
                        }
                    });
                    
                    // Wait for images to load (max 10s as in POC)
                    const images = Array.from(document.querySelectorAll('img'));
                    await Promise.all(images.map(img => {
                        if (img.complete) return Promise.resolve();
                        return new Promise(resolve => {
                            img.onload = resolve;
                            img.onerror = resolve;
                            setTimeout(resolve, 10000); 
                        });
                    }));
                }
            """)
            
            logger.info("Waiting 10s for dynamic catalog stabilization (POC logic)...")
            page.wait_for_timeout(10000) # Stabilization wait as in POC line 584
            
            # 6. Move mouse away to clear hover states/mega-menus
            try:
                page.mouse.move(0, 0)
                page.wait_for_timeout(1000)
            except:
                pass
            
            # 7. Final Height Adjustment to eliminate white space
            final_height = page.evaluate("Math.max(document.scrollingElement.scrollHeight, document.body.scrollHeight, 1000)")
            capture_height = min(final_height, 15000) 
            page.set_viewport_size({"width": current_width, "height": capture_height})
            
            # Final top-alignment guarantee
            page.evaluate("window.scrollTo(0, 0)")
            page.wait_for_timeout(1000)
                
            # 8. Take the screenshot. We use full_page=True now that we've stabilized 
            # but we keep the viewport expanded to ensure React components are mounted.
            page.evaluate("window.scrollTo(0, 0)")
            page.wait_for_timeout(1000)
            chunk_bytes = page.screenshot(full_page=True, animations="disabled")
            
            # 9. Restore viewport
            page.set_viewport_size({"width": current_width, "height": current_height})
            
            return chunk_bytes
            
        except Exception as e:
            logger.warning(f"Ultra-Stealth screenshot failed, falling back to basic: {e}")
            try:
                page.set_viewport_size({"width": current_width, "height": current_height})
            except:
                pass
            page.evaluate("window.scrollTo(0, 0)")
            return page.screenshot(full_page=True)
