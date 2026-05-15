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
import time
import yaml
from typing import Optional, Dict
from urllib.parse import urlparse
from pathlib import Path
from playwright.sync_api import sync_playwright, Page
import io
from PIL import Image
from bs4 import BeautifulSoup
from web_crawler.crawler.seo_report import CrawlReportWriter
import platform
from concurrent.futures import ThreadPoolExecutor
import threading

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


logger = logging.getLogger(__name__)


def _get_db_conn():
    """
    Open and return a short-lived, standalone psycopg2 connection.
    Reads config.yaml the same way _record_failed_page does.
    Raises on failure — callers should catch.
    """
    import psycopg2
    from dotenv import load_dotenv
    
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
        admin_email = os.getenv("ADMIN_EMAIL", "ganesha@gramosoft.in")
        
        if not smtp_cfg:
            logger.warning("Email configuration not found in config.yaml")
            return

        email_service = EmailService(smtp_cfg)
        email_service.send_crawl_error_email(
            to_email=admin_email,
            crawl_id=crawl_id,
            url=url,
            error_source=error_source,
            reason=reason,
            blocked_message=blocked_message
        )
    except Exception as e:
        logger.warning(f"⚠ Could not send crawl error email: {e}")


class BrowserManager:
    """Thread-safe Singleton to manage warm browser instances (Pooling)"""
    _instance = None
    _lock = threading.Lock()
    _local = threading.local()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(BrowserManager, cls).__new__(cls)
            return cls._instance

    def _get_local_data(self):
        if not hasattr(self._local, 'playwright'):
            self._local.playwright = None
            self._local.chromium_browser = None
            self._local.camoufox_browser = None
        return self._local

    def get_playwright(self):
        local = self._get_local_data()
        if not local.playwright:
            local.playwright = sync_playwright().start()
        return local.playwright

    def get_chromium(self, config):
        local = self._get_local_data()
        p = self.get_playwright()
        
        # Check if browser is still connected
        is_connected = False
        if local.chromium_browser:
            try:
                is_connected = local.chromium_browser.is_connected()
            except:
                is_connected = False

        if not local.chromium_browser or not is_connected:
            with self._lock: # Thread-safe launch
                logger.info(f"🚀 Launching WARM Chromium instance (Thread {threading.get_ident()})...")
                local.chromium_browser = p.chromium.launch(
                    headless=config.headless,
                    proxy={"server": "http://127.0.0.1:0"},
                    args=[
                        '--no-sandbox', '--disable-setuid-sandbox', '--disable-infobars',
                        '--ignore-certificate-errors', '--disable-blink-features=AutomationControlled',
                        '--disable-dev-shm-usage', '--disable-gpu', '--disable-http2'
                    ]
                )
        return local.chromium_browser

    def get_camoufox(self, config):
        local = self._get_local_data()
        p = self.get_playwright()
        
        is_connected = False
        if local.camoufox_browser:
            try:
                is_connected = local.camoufox_browser.is_connected()
            except:
                is_connected = False

        if not local.camoufox_browser or not is_connected:
            with self._lock: # Thread-safe launch
                logger.info(f"🚀 Launching WARM Camoufox instance (Thread {threading.get_ident()})...")
                from camoufox.sync_api import NewBrowser
                local.camoufox_browser = NewBrowser(
                    p,
                    headless=config.headless,
                    os="windows",
                    block_webrtc=True,
                )
        return local.camoufox_browser

    def shutdown(self):
        local = self._get_local_data()
        try:
            if local.chromium_browser: local.chromium_browser.close()
            if local.camoufox_browser: local.camoufox_browser.close()
            if local.playwright: local.playwright.stop()
        except: pass


# Global browser manager
browser_manager = BrowserManager()


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

    def _move_human(self, page, x, y):
        """Helper for human-like mouse movement with variable velocity and jitter"""
        # Faster movement for high-latency proxies
        page.mouse.move(x, y, steps=random.randint(1, 5))

    def _is_screenshot_blank(self, screenshot_bytes: bytes) -> bool:
        """
        Heuristic to detect if a screenshot is blank (mostly white or a single color).
        Uses PIL to calculate image entropy or standard deviation.
        """
        if not screenshot_bytes:
            return True
        try:
            img = Image.open(io.BytesIO(screenshot_bytes)).convert("L") # Grayscale
            # Get pixel data statistics
            from PIL import ImageStat
            stat = ImageStat.Stat(img)
            # If standard deviation is extremely low, the image is likely a solid color
            if stat.stddev[0] < 1.0:
                return True
            return False
        except Exception as e:
            logger.error(f"Error validating screenshot blankness: {e}")
            return False

    def _is_page_content_blank(self, title: str, text_content: str, links_count: int) -> bool:
        """
        Check if the page content seems blank or stuck on a loader.
        """
        # Lowered thresholds: very few sites have < 100 chars of actual text if loaded correctly
        if len(text_content.strip()) < 100 and links_count == 0:
            return True
        # Title being empty and content is extremely sparse
        if not title and len(text_content.strip()) < 200:
            return True
        return False

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

    def _resolve_playwright_proxy(self, proxy_tier: int = 1, session_id: Optional[str] = None, target_url: Optional[str] = None) -> Optional[Dict]:
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

        return self.proxy_manager.get_playwright_proxy(tier=proxy_tier, session_id=session_id, target_url=target_url)
    
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
        client_id: Optional[str],
        status_code: int = 200
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
            # Initial content fetch
            html = page.content()
            soup = BeautifulSoup(html, "lxml")
            
            # Start CPU/IO tasks in parallel while we handle the screenshot
            # Note: Playwright sync calls MUST stay on the main thread
            results_bag = {}
            tasks = []
            
            with ThreadPoolExecutor(max_workers=5) as executor:
                # 1. SEO Processing
                def _do_seo():
                    if not enable_seo: return None
                    try:
                        seo_data = self.content_processor.extract_seo(soup, url)
                        writer = CrawlReportWriter(self.config.output_dir)
                        
                        s_json = writer.render_single_json(seo_data)
                        s_md = writer.render_single_markdown(seo_data)
                        s_xlsx = writer.render_single_excel_base64(seo_data)
                        
                        # Artifact storage (IO)
                        j_art = _store_crawl_artifact(client_id, "seo_json", s_json, page_url=url, title=seo_data.get("title"))
                        m_art = _store_crawl_artifact(client_id, "seo_md", s_md, page_url=url, title=seo_data.get("title"))
                        x_art = _store_crawl_artifact(client_id, "seo_xlsx", s_xlsx, content_kind="binary", page_url=url, title=seo_data.get("title"))
                        
                        return {"data": seo_data, "json": s_json, "md": s_md, "xlsx": s_xlsx}
                    except Exception as e:
                        logger.error(f"SEO Parallel Task Error: {e}")
                        return None

                # 2. Markdown Processing
                def _do_md():
                    if not enable_md: return None
                    try:
                        md = self.content_processor.convert_to_markdown(html, url)
                        _store_crawl_artifact(client_id, "markdown", md, page_url=url)
                        return md
                    except Exception as e:
                        logger.error(f"MD Parallel Task Error: {e}")
                        return None

                # 3. Image Extraction
                def _do_images():
                    if not enable_images: return None
                    try:
                        imgs = self.content_processor.extract_image_urls(soup, url)
                        _store_crawl_artifact(client_id, "images", imgs, content_kind="json", page_url=url)
                        return imgs
                    except Exception as e:
                        logger.error(f"Images Parallel Task Error: {e}")
                        return None

                # Submit tasks
                f_seo = executor.submit(_do_seo)
                f_md = executor.submit(_do_md)
                f_imgs = executor.submit(_do_images)
                
                # While those are running in background, we take the screenshot (Main Thread)
                screenshot_bytes = None
                screenshot_path = None
                if enable_ss:
                    try:
                        screenshot_bytes = self._capture_robust_screenshot(page)
                        if screenshot_bytes:
                            screenshot_b64 = base64.b64encode(screenshot_bytes).decode("utf-8")
                            _store_crawl_artifact(client_id, "screenshot", screenshot_b64, content_kind="binary", page_url=url)
                            
                            os.makedirs(self.config.screenshot_dir, exist_ok=True)
                            local_ss_path = self.config.screenshot_dir / f"page_{count}.png"
                            with open(local_ss_path, "wb") as f:
                                f.write(screenshot_bytes)
                            screenshot_path = str(local_ss_path)
                    except Exception as e:
                        logger.error(f"Screenshot Error: {e}")

                # Wait for all background tasks to finish
                seo_res = f_seo.result()
                md_content = f_md.result()
                img_urls = f_imgs.result()
                
                # Links extraction (Main thread as it's fast)
                links = self.content_processor.extract_links(soup, url)

            # Local File Persistence (IO) - can stay sequential or moved to tasks if many
            seo = seo_res["data"] if seo_res else {}
            title = seo.get("title", "No Title")
            
            # (Mapping paths for local files as before)
            seo_json_path = None
            seo_md_path = None
            seo_xlsx_path = None
            if seo_res:
                os.makedirs(self.config.seo_dir, exist_ok=True)
                sj_p = self.config.seo_dir / f"seo_{count}.json"
                with open(sj_p, "w", encoding="utf-8") as f: f.write(seo_res["json"])
                seo_json_path = str(sj_p)
                
                sm_p = self.config.seo_dir / f"seo_{count}.md"
                with open(sm_p, "w", encoding="utf-8") as f: f.write(seo_res["md"])
                seo_md_path = str(sm_p)
                
                sx_p = self.config.seo_dir / f"seo_{count}.xlsx"
                with open(sx_p, "wb") as f: f.write(base64.b64decode(seo_res["xlsx"]))
                seo_xlsx_path = str(sx_p)

            md_path = None
            if md_content:
                os.makedirs(self.config.md_dir, exist_ok=True)
                m_p = self.config.md_dir / f"page_{count}.md"
                with open(m_p, "w", encoding="utf-8") as f: f.write(md_content)
                md_path = str(m_p)

            images_path = None
            if img_urls:
                i_p = Path(self.config.output_dir) / f"images_{count}.json"
                with open(i_p, "w", encoding="utf-8") as f: json.dump(img_urls, f, indent=2)
                images_path = str(i_p)

            # HTML Persistence
            html_path = None
            if enable_html:
                _store_crawl_artifact(client_id, "html", html, page_url=url, title=title)
                os.makedirs(self.config.html_dir, exist_ok=True)
                h_p = self.config.html_dir / f"page_{count}.html"
                with open(h_p, "w", encoding="utf-8") as f: f.write(html)
                html_path = str(h_p)

            # Block detection keywords (POC Parity)
            check_content = page.evaluate("document.body.innerText").lower()[:5000]
            title = seo.get("title", "No Title")
            current_url = page.url.lower()
            
            is_google_site = "google.com" in url.lower() or "google" in url.lower()
            
            block_keywords = [
                "i am not a robot", "access denied", "blocked", "captcha",
                "security check", "verify your identity", "human side",
                "bot detection", "robot check", "distil networks", "incapsula",
                "perimeterx", "fw_error_www", "bot or not", "pardon our interruption",
                "unusual traffic", "challenge-form", "cf-challenge",
                "proxy authentication required", "refusing connections", 
                "press & hold", "press and hold",
                "sorry-server", "delta_sorry", "access-denied", "ip blocked", 
                "security challenge", "bot-check"
            ]
            
            # URL-based block detection (Detects redirects to 'Sorry' pages)
            url_block_patterns = ["sorry-server", "delta_sorry", "access-denied", "/captcha", "/checkpoint"]
            
            triggered_kw = None
            for kw in block_keywords:
                if kw in title.lower() or kw in check_content:
                    triggered_kw = kw
                    break
            
            is_url_blocked = False
            for pattern in url_block_patterns:
                if pattern in current_url:
                    triggered_kw = f"URL:{pattern}"
                    is_url_blocked = True
                    break

            is_blocked = is_url_blocked or triggered_kw is not None or status_code in [403, 429]
            
            # 4. Blank Page Detection (New)
            if not is_blocked:
                content_blank = self._is_page_content_blank(title, check_content, len(links))
                screenshot_blank = False
                if enable_ss and screenshot_bytes:
                    screenshot_blank = self._is_screenshot_blank(screenshot_bytes)
                
                # GROUND TRUTH: If screenshot is NOT blank, the page is NOT blank (even if sparse text)
                if content_blank and not screenshot_blank and enable_ss:
                    logger.info(f"Page has sparse text but valid screenshot for {url}. Proceeding.")
                    content_blank = False

                if content_blank or screenshot_blank:
                    reason = "Blank content" if content_blank else "Blank screenshot"
                    logger.warning(f"{reason} detected for {url}. Escalating tier.")
                    return {"error": "Blank page detected", "status_code": 403}
            
            if is_blocked:
                logger.warning(f"Block page detected for {url} (Trigger: {triggered_kw}, Title: {title}). Marking as failure for tier rotation.")
                return {"error": f"Block page detected ({triggered_kw})", "status_code": 403}

            if client_id:
                publish_event(
                    crawl_id=client_id,
                    payload={
                        "type": "page_processed",
                        "page": count,
                        "url": url,
                        "title": title,
                        "markdown_file": md_path,
                        "html_file": html_path,
                        "screenshot": screenshot_path,
                        "seo_json": seo_json_path,
                        "seo_md": seo_md_path,
                        "seo_xlsx": seo_xlsx_path,
                        "images": images_path,
                    }
                )
                _persist_crawl_event(
                    crawl_id=client_id,
                    url=url,
                    title=title,
                    markdown_file=md_path,
                    html_file=html_path,
                    screenshot=screenshot_path,
                    seo_json=seo_json_path,
                    seo_md=seo_md_path,
                    seo_xlsx=seo_xlsx_path,
                    images=images_path,
                )

            logger.info(f"Successfully processed: {url}")
            
            return {
                "url": url,
                "canonical": normalize_url(seo.get("canonical") or url),
                "seo": seo,
                "html_file": html_path,
                "screenshot": screenshot_path,
                "markdown_file": md_path,
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

    def is_captcha_page(self, page: Page) -> bool:
        """
        Deep check for CAPTCHA pages including iframes and specific bot-challenge elements.
        """
        try:
            # 1. Check Page Title
            title = page.title().lower()
            captcha_title_markers = [
                "just a moment", "access denied", "attention required", 
                "challenge", "robot", "pardon our interruption", "bot or not"
            ]
            if any(m in title for m in captcha_title_markers):
                logger.warning(f"CAPTCHA detected via title: {title}")
                return True

            # 2. Check for common CAPTCHA selectors
            selectors = [
                "iframe[src*='captcha']", "iframe[src*='recaptcha']", 
                "iframe[src*='hcaptcha']", "iframe[src*='turnstile']",
                "#challenge-form", "#cf-challenge", ".g-recaptcha",
                ".h-captcha", "#px-captcha", "#distilCaptcha"
            ]
            for selector in selectors:
                try:
                    if page.locator(selector).count() > 0:
                        logger.warning(f"CAPTCHA detected via selector: {selector}")
                        return True
                except: continue

            # 3. Check Page Text
            text_content = page.evaluate("document.body.innerText")
            if text_content:
                text_lower = text_content.lower()
                captcha_markers = [
                    "our systems have detected unusual traffic",
                    "please show you're not a robot",
                    "i'm not a robot",
                    "i am not a robot",
                    "verify you are human",
                    "checking if the site connection is secure",
                    "enable cookies and javascript",
                    "bot detection",
                    "one more step"
                ]
                if len(text_content.strip()) < 4000 and any(marker in text_lower for marker in captcha_markers):
                    logger.warning("CAPTCHA detected via text content.")
                    return True
            
            return False
        except Exception as e:
            logger.debug(f"Captcha detection check failed: {e}")
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
        """Crawl page using Chromium with stealth (Pooled)"""
        context = None
        page = None
        try:
            session_id = "".join(random.choices("0123456789abcdef", k=8))
            proxy_settings = self._resolve_playwright_proxy(proxy_tier, session_id=session_id, target_url=url)
            browser = browser_manager.get_chromium(self.config)
            
            is_japan = "jal.co.jp" in url.lower()
            target_tz = "Asia/Tokyo" if is_japan else "America/New_York"
            target_locale = "ja-JP" if is_japan else "en-US"
            target_geo = {"latitude": 35.6762, "longitude": 139.6503} if is_japan else {"latitude": 40.7128, "longitude": -74.0060}

            context_kwargs = dict(
                viewport={"width": 1920, "height": 1080},
                locale=target_locale,
                timezone_id=target_tz,
                geolocation=target_geo,
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
            nav_timeout = 90_000 if proxy_tier > 1 else 60_000
            if "google.com/search" in url and proxy_tier > 1:
                mobile_ua = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Mobile/15E148 Safari/604.1"
                context_kwargs["user_agent"] = mobile_ua
                context_kwargs["viewport"] = {"width": 390, "height": 844}
                context_kwargs["is_mobile"] = True
                context_kwargs["has_touch"] = True

            context = browser.new_context(**context_kwargs)
            
            logger.info(f"Chromium browser (windows) initialized successfully with evasion flags")
            logger.info(f"[Stealth Layer] Engine initialization: Hardened TLS fingerprinting and browser fingerprint evasion active.")
            logger.info(f"[Stealth Layer] Browser Fingerprinting: Platform=Desktop, Viewport={context_kwargs['viewport']['width']}x{context_kwargs['viewport']['height']}, Locale={context_kwargs['locale']}")
            logger.info(f"[Stealth Layer] Network Identity: Applying organic Chrome headers and Referer spoofing.")

            from urllib.parse import urlparse
            
            high_sec_sites = [
                "meesho", "delta.com", "jal.co.jp", "united.com", "wayfair.com", 
                "zillow.com", "amazon", "google.com", "myaccount.google.com", 
                "gcrawlai.com", "luisaviaroma.com", "oracle.com", "usps.com", 
                "nike.com", "adidas.com", "homedepot.com", "southwest.com",
                "expedia.com", "neimanmarcus.com", "nordstrom.com", "skyscanner",
                "lowes.com", "rakuten.com", "footlocker.com", "att.com", "booking.com",
                "chewy.com", "autozone.com", "comcast.com", "indeed.com"
            ]
            extreme_high_sec = ["expedia.com", "zillow.com", "wayfair.com", "oracle.com"]
            mobile_target_sites = [
                "expedia.com", "luisaviaroma.com", "oracle.com", "chewy.com",
                "autozone.com", "indeed.com", "zillow.com", "wayfair.com", "nordstrom.com", "jal.co.jp"
            ]
            is_high_sec = any(s in url.lower() for s in high_sec_sites)
            is_extreme = any(s in url.lower() for s in extreme_high_sec)
            
            # POC Parity: Force Desktop for Extreme sites
            use_mobile = any(site in url.lower() for site in mobile_target_sites) and proxy_tier >= 3
            if is_extreme: use_mobile = False
            is_skyscanner = "skyscanner" in url.lower()

            custom_headers = {
                "Sec-Fetch-Site": "cross-site",
                "Sec-Fetch-Mode": "navigate",
                "Sec-Fetch-Dest": "document"
            }
            
            # POC Parity: Referral logic
            if is_high_sec:
                domain_name = next((s for s in high_sec_sites if s in url.lower()), "site")
                query_name = domain_name.split('.')[0]
                custom_headers["Referer"] = f"https://www.google.com/search?q={query_name}+official+store&oq={query_name}"
                if is_skyscanner:
                    custom_headers["Referer"] = "https://www.google.com/"
            else:
                custom_headers["Referer"] = "https://www.google.com/"

            context.set_extra_http_headers(custom_headers)
            
            page = context.new_page()
            # POC Parity: Initial mouse move before navigation
            self._move_human(page, random.randint(300, 800), random.randint(300, 600))
            
            self.browser_utils.inject_stealth_scripts(page)
            
            # Additional high-sec keywords for consistency
            extra_high_sec = ["expedia", "axs", "southwest", "skyscanner", "neimanmarcus"]
            if any(s in url.lower() for s in extra_high_sec):
                is_high_sec = True
            
            if is_high_sec:
                domain_name = next((s for s in high_sec_sites if s in url.lower()), "site")
                # POC Parity: Referral spoofing for high-sec
                referer = f"https://www.google.com/search?q={domain_name}+official+store&oq={domain_name}"
                if "skyscanner" in url.lower():
                    referer = "https://www.google.com/"
            
            # Warm-up Navigation (Smart Waiting)
            if is_high_sec and not is_japan:
                from urllib.parse import urlparse
                parsed = urlparse(url)
                # Domain Warmup: Visit root domain first to seed security cookies (_abck, bm_sz)
                warmup_url = f"{parsed.scheme}://{parsed.netloc}/"
                logger.info(f"Domain Warmup (Cookie Seeding) for: {warmup_url}")
                try:
                    # POC Parity: Use 'load' instead of 'networkidle' to prevent hangs on heavy sites
                    page.goto(warmup_url, wait_until="load", timeout=40000)
                    
                    # Wait and move on warmup page to trigger sensor
                    for _ in range(2):
                        page.wait_for_timeout(random.randint(500, 1500))
                        self._move_human(page, random.randint(100, 1000), random.randint(100, 800))
                    
                    # Log Akamai cookie status
                    cookies = context.cookies()
                    abck = [c for c in cookies if c['name'] == '_abck']
                    logger.info(f"[Stealth Layer] Identity Token Seeding: _abck={'FOUND' if abck else 'MISSING'}")
                    
                    if not abck:
                        # Extra desperate wait for sensor
                        logger.warning("Cookie still missing, extra 3s settlement...")
                        page.wait_for_timeout(3000)
                except Exception as e:
                    logger.debug(f"Domain warmup failed (proceeding): {e}")
            
            try:
                logger.info(f"Navigating to target URL: {url} (Chromium)")
                # POC Parity: Use 'load' for more stability and less hangs
                is_skyscanner = "skyscanner" in url.lower()
                wait_mode = "load" if (is_high_sec or is_skyscanner) else "domcontentloaded"
                
                try:
                    response = page.goto(url, wait_until=wait_mode, timeout=nav_timeout)
                except Exception as e:
                    if "ERR_EMPTY_RESPONSE" in str(e) or "reset" in str(e).lower() or "interrupted" in str(e).lower():
                        logger.warning(f"Chromium network error for {url}. Waiting 5s and retrying with 'domcontentloaded'...")
                        page.wait_for_timeout(5000)
                        response = page.goto(url, wait_until="domcontentloaded", timeout=nav_timeout + 10000)
                    else:
                        raise e
                
                logger.info(f"Navigation completed. Status: {response.status if response else 'No Response'}")
                
                if not response: return {"url": url, "error": "No response", "status_code": 0}
                
                status_code = response.status if response else 0
                
                # IMMEDIATE CAPTCHA CHECK: Bail out early to next tier without wasting time on simulation
                if self.is_captcha_page(page):
                    logger.warning(f"CAPTCHA detected IMMEDIATELY for {url}. Skipping simulation and bailing to next tier.")
                    return {"url": url, "error": "CAPTCHA detected", "status_code": 403}

                # POC Parity: Handle blank page / challenge settlement
                # Wait for page to actually render before status check
                try:
                    # Shorter stabilization for ordinary sites
                    stab_timeout = 15000 if is_high_sec else 5000
                    page.wait_for_load_state("load", timeout=stab_timeout)
                    page.wait_for_selector("body", state="visible", timeout=5000)
                except:
                    pass
                
                status_code = response.status if response else 0
                title = page.title()
                
                # Removed immediate bail out on 403 to allow challenge settlement
                if status_code in [401, 407]:
                    logger.warning(f"Bailing out due to status {status_code} before behavioral simulation.")
                    return {"url": url, "error": f"Block/Auth error: {status_code}", "status_code": status_code}

                if (not title and status_code == 200) or is_skyscanner or is_high_sec:
                    # Removed 10s fixed wait as per user request
                    title = page.title()

                # Behavioral Loop shortened with strict 2s limit
                if is_high_sec or is_skyscanner:
                    logger.info(f"[Stealth Layer] JavaScript Challenges: Executing fast behavioral signals.")
                    try:
                        sim_start = time.time()
                        for _ in range(2): 
                            if time.time() - sim_start > 2: break
                            self._move_human(page, random.randint(200, 1000), random.randint(200, 800))
                            page.wait_for_timeout(random.uniform(200, 500))
                        logger.info("Human activity simulation completed")
                    except Exception as sim_err:
                        logger.debug(f"Behavioral simulation interrupted: {sim_err}")

                # Human-like erratic scroll for all sites to ensure lazy loading and stabilization
                logger.info("[Stealth Layer] JS Rendering: Stabilizing dynamic DOM elements and triggering lazy-loaded assets before extraction.")
                logger.info("Performing human-like irregular scroll...")
                self.browser_utils.erratic_scroll(page)
                
                if not self.browser_utils.wait_for_ready(page): 
                    logger.warning(f"Page stabilization timed out for {url}, proceeding anyway.")
                
                if self.is_captcha_page(page): 
                    return {"url": url, "error": "CAPTCHA detected", "status_code": 403}
                    
                return self.process_page(page, url, count, enable_md, enable_html, enable_ss, enable_seo, enable_images, client_id, status_code=status_code)
            finally:
                try:
                    if page: page.close()
                    if context: context.close()
                except:
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
        """Fallback crawl using Camoufox (Pooled)"""
        context = None
        page = None
        try:
            session_id = "".join(random.choices("0123456789abcdef", k=8))
            proxy_settings = self._resolve_playwright_proxy(proxy_tier, session_id=session_id, target_url=url)
            browser = browser_manager.get_camoufox(self.config)
            
            high_sec_sites = [
                "meesho", "delta.com", "jal.co.jp", "united.com", "wayfair.com", 
                "zillow.com", "amazon", "google.com", "myaccount.google.com", 
                "gcrawlai.com", "luisaviaroma.com", "oracle.com", "usps.com", 
                "nike.com", "adidas.com", "homedepot.com", "southwest.com",
                "expedia.com", "neimanmarcus.com", "nordstrom.com", "skyscanner",
                "lowes.com", "rakuten.com", "footlocker.com", "att.com", "booking.com",
                "chewy.com", "autozone.com", "comcast.com", "indeed.com"
            ]
            extreme_high_sec = ["expedia.com", "zillow.com", "wayfair.com", "oracle.com"]
            mobile_target_sites = [
                "expedia.com", "luisaviaroma.com", "oracle.com", "chewy.com",
                "autozone.com", "indeed.com", "zillow.com", "wayfair.com", "nordstrom.com", "jal.co.jp"
            ]
            is_high_sec = any(site in url.lower() for site in high_sec_sites)
            is_extreme = any(site in url.lower() for site in extreme_high_sec)
            
            # POC Parity: Force Desktop for Extreme sites
            use_mobile = any(site in url.lower() for site in mobile_target_sites) and proxy_tier >= 3
            if is_extreme: use_mobile = False

            is_meesho = "meesho" in url.lower()
            is_google = "google.com" in url.lower()
            is_japan = "jal.co.jp" in url.lower()
            
            target_tz = "Asia/Tokyo" if is_japan else ("Asia/Kolkata" if (proxy_tier in [4, 6, 8] or is_meesho) else "America/New_York")
            target_locale = "ja-JP" if is_japan else "en-US"
            target_geo = {"latitude": 35.6762, "longitude": 139.6503} if is_japan else ({"latitude": 19.0760, "longitude": 72.8777} if (proxy_tier in [4, 6, 8] or is_meesho) else {"latitude": 40.7128, "longitude": -74.0060})

            context_kwargs = dict(
                viewport={"width": 1920, "height": 1080} if not use_mobile else {"width": 390, "height": 844},
                locale=target_locale, timezone_id=target_tz, geolocation=target_geo,
                permissions=["geolocation", "notifications"], java_script_enabled=True,
                ignore_https_errors=True, bypass_csp=True, color_scheme="light"
            )
            if proxy_settings: context_kwargs["proxy"] = proxy_settings
            if use_mobile: context_kwargs["user_agent"] = "Mozilla/5.0 (iPhone; CPU iPhone OS 15_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/15.0 Mobile/15E148 Safari/604.1"

            logger.info(f"Camoufox browser (windows) initialized successfully with evasion flags")
            logger.info(f"[Stealth Layer] Engine initialization: Hardened TLS fingerprinting and browser fingerprint evasion active.")
            logger.info(f"[Stealth Layer] Browser Fingerprinting: Platform=Desktop, Viewport={context_kwargs['viewport']['width']}x{context_kwargs['viewport']['height']}, Locale={context_kwargs['locale']}, Timezone={context_kwargs['timezone_id']}")
            logger.info(f"[Stealth Layer] Network Identity: Applying deep referer spoofing and Sec-Fetch headers to mimic organic traffic.")
            
            context = browser.new_context(**context_kwargs)
            from urllib.parse import urlparse
            
            # Additional high-sec keywords for consistency
            extra_high_sec = ["expedia", "axs", "southwest", "skyscanner", "neimanmarcus"]
            if any(s in url.lower() for s in extra_high_sec):
                is_high_sec = True
            is_skyscanner = "skyscanner" in url.lower()

            # POC Parity: Only set Referer on Camoufox; let the engine handle its own headers 
            custom_headers = {}
            if is_high_sec:
                # Clean domain name for search query (remove .com, .co.uk etc)
                domain_name = next((s for s in high_sec_sites if s in url.lower()), "site")
                query_name = domain_name.split('.')[0] 
                custom_headers["Referer"] = f"https://www.google.com/search?q={query_name}+official+store&oq={query_name}"
                if is_skyscanner:
                    custom_headers["Referer"] = "https://www.google.com/"
            else:
                custom_headers["Referer"] = "https://www.google.com/"
            
            # POC Parity: Set headers on CONTEXT before page creation
            context.set_extra_http_headers(custom_headers)
            
            page = context.new_page()
            # POC Parity: Initial mouse move before navigation
            self._move_human(page, random.randint(300, 800), random.randint(300, 600))
            
            # Domain Warmup (Cookie Seeding)
            if is_high_sec and not is_japan:
                parsed = urlparse(url)
                warmup_url = f"{parsed.scheme}://{parsed.netloc}/"
                logger.info(f"Domain Warmup (Cookie Seeding) for: {warmup_url}")
                try:
                    page.goto(warmup_url, wait_until="load", timeout=40000)
                    page.wait_for_timeout(random.randint(1000, 2000))
                except Exception as e:
                    logger.debug(f"Domain warmup failed (proceeding): {e}")

            logger.info(f"Navigating to target URL: {url} (Camoufox)")
            # POC Parity: Dynamic wait mode. Use 'domcontentloaded' for speed on ordinary sites.
            wait_mode = "load" if is_high_sec else "domcontentloaded"
            
            # Internal retry logic for network instability with FRESH CONTEXT fallback
            try:
                response = page.goto(url, wait_until=wait_mode, timeout=60000)
            except Exception as e:
                if "NS_ERROR_NET_INTERRUPT" in str(e) or "interrupted" in str(e).lower():
                    logger.warning(f"Network interruption detected for {url}. Creating FRESH context and retrying with Mobile identity...")
                    try:
                        if page: page.close()
                        if context: context.close()
                        
                        # Create a fresh context with Mobile headers forced for retry
                        retry_kwargs = context_kwargs.copy()
                        retry_kwargs["user_agent"] = "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1"
                        retry_kwargs["viewport"] = {"width": 390, "height": 844}
                        
                        context = browser.new_context(**retry_kwargs)
                        page = context.new_page()
                        self.browser_utils.inject_stealth_scripts(page)
                        
                        page.wait_for_timeout(3000)
                        response = page.goto(url, wait_until="domcontentloaded", timeout=70000)
                    except Exception as retry_e:
                        logger.error(f"Fresh context retry failed: {retry_e}")
                        raise e
                else:
                    raise e
                    
            status_code = response.status if response else 0
            logger.info(f"Navigation completed. Status: {status_code}")
            
            # IMMEDIATE CAPTCHA CHECK: Bail out early to next tier
            if self.is_captcha_page(page):
                logger.warning(f"CAPTCHA detected IMMEDIATELY for {url}. Skipping simulation and bailing to next tier.")
                return {"url": url, "error": "CAPTCHA detected", "status_code": 403}
            
            # POC Parity: Handle blank page / challenge settlement
            # Wait for page to actually render before status check
            try:
                # Shorter stabilization for ordinary sites
                stab_timeout = 15000 if is_high_sec else 5000
                page.wait_for_load_state("load", timeout=stab_timeout)
                page.wait_for_selector("body", state="visible", timeout=5000)
            except:
                pass

            status_code = response.status if response else 0
            title = page.title()

            # Removed immediate bail out on 403 to allow challenge settlement
            if status_code in [401, 407]:
                logger.warning(f"Bailing out due to status {status_code} before behavioral simulation.")
                return {"url": url, "error": f"Block/Auth error: {status_code}", "status_code": status_code}

            is_skyscanner = "skyscanner" in url.lower()
            if (not title and status_code == 200) or is_skyscanner or is_high_sec:
                # Removed 10s fixed wait as per user request
                title = page.title()
            
            # Behavioral Loop shortened with strict 2s limit
            if is_high_sec or is_skyscanner or (response and response.status in [403, 429]):
                logger.info(f"[Stealth Layer] JavaScript Challenges: Executing fast behavioral signals.")
                try:
                    sim_start = time.time()
                    for _ in range(2):
                        if time.time() - sim_start > 2: break
                        self._move_human(page, random.randint(200, 1000), random.randint(200, 800))
                        page.wait_for_timeout(random.uniform(200, 500))
                    logger.info("Human activity simulation completed")
                except Exception as sim_err:
                    logger.debug(f"Behavioral simulation interrupted: {sim_err}")

            # Human-like erratic scroll for all sites to ensure lazy loading and stabilization
            logger.info("[Stealth Layer] JS Rendering: Stabilizing dynamic DOM elements and triggering lazy-loaded assets before extraction.")
            logger.info("Performing human-like irregular scroll...")
            self.browser_utils.erratic_scroll(page)
            
            if self.is_captcha_page(page):
                return {"url": url, "error": "CAPTCHA detected", "status_code": 403}
                
            result = self.process_page(page, url, count, enable_md, enable_html, enable_ss, enable_seo, enable_images, client_id, status_code=status_code)
            return result
        except Exception as e:
            err_msg = str(e)
            if "NS_ERROR_NET_INTERRUPT" in err_msg or "connection was closed" in err_msg.lower():
                logger.warning(f"Network interruption detected for {url} (Akamai block). Escalating...")
                return {"url": url, "error": "Network Interruption", "status_code": 403}
            
            logger.error(f"Camoufox failed: {e}")
            return None
        finally:
            # Safety cleanup to prevent TargetClosedError
            try:
                if page: page.close()
                if context: context.close()
            except:
                pass
    
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
            start_tier = self.config.default_tier
        else:
            # If they picked basic/stealth/etc, start from there
            if requested_proxy_type == "mobile":
                start_tier = 2
            elif requested_proxy_type == "bright_data":
                start_tier = 3
            elif requested_proxy_type == "basic":
                start_tier = 4
            elif requested_proxy_type == "stealth":
                start_tier = 6
            elif requested_proxy_type == "enhanced":
                start_tier = 8
            else:
                start_tier = 1
            
        is_auto = True # Force escalation for all modes to ensure success

        # Multi-Tier browser orchestration (Camoufox for Tiers 1-6, Chromium for Tiers 7-8)
        current_tier = start_tier
        result = None
        failure_recorded = False

        while current_tier <= 9:
            logger.info("\n" + "="*30 + f"\nTier {current_tier} - Processing\n" + "="*30)
            
            if current_tier < 8:
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

            # If it failed, try the next tier (always escalating up to 8 for max success)
            logger.warning("\n" + "="*30 + f"\nTier {current_tier} - Failed\n" + "="*30)
            if current_tier < 8:
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
        """
        Hide common popups and cookie banners using an aggressive non-destructive stealth approach.
        Includes auto-clicking for common 'Accept' buttons and CSS hiding for overlays.
        """
        try:
            # 1. Wait for skeleton loaders to disappear
            try:
                page.wait_for_function("""
                    () => {
                        const skeletons = document.querySelectorAll('[class*="skeleton"], [class*="loading-shimmer"], .shimmer');
                        return skeletons.length === 0;
                    }
                """, timeout=3000)
            except: pass 

            # 2. Aggressive Auto-Click for Cookie Consent (POC style)
            page.evaluate("""
                () => {
                    const buttons = Array.from(document.querySelectorAll('button, a, span'));
                    const acceptKeywords = [
                        'accept all', 'allow all', 'accept cookies', 'agree', 'got it', 
                        'accept and close', 'confirm', 'allow cookies', 'agree & closed'
                    ];
                    
                    for (const btn of buttons) {
                        const text = btn.innerText.toLowerCase().trim();
                        if (acceptKeywords.some(kw => text === kw || text.includes(kw))) {
                            // Only click if it's likely a cookie button (not too large, fixed/absolute or high z-index)
                            const style = window.getComputedStyle(btn);
                            if (style.position === 'fixed' || style.position === 'absolute' || parseInt(style.zIndex) > 10) {
                                try { btn.click(); } catch(e) {}
                            }
                        }
                    }
                }
            """)
            page.wait_for_timeout(1000)

            # 3. Deep-Hide common sticky overlays
            page.evaluate("""
                () => {
                    const selectorsToHide = [
                        '#onetrust-banner-sdk', '.ot-sdk-container', '#didomi-notice', 
                        '#cookie-banner', '.cookie-banner', '[id*="cookie"]', '[class*="cookie"]',
                        '[class*="consent"]', '[id*="consent"]', '[class*="privacy"]',
                        '.modal-backdrop', '.modal-open', '.fade.in',
                        '.bx-row-submit-button', '#newsletter-popup', '[id*="newsletter"]',
                        '[id^="sp_message_container"]', '.sp_veil', '.evidon-banner',
                        '#consent-banner', '.gdpr-consent', '.overlay', '.fixed-overlay',
                        '[class*="NewsletterPopup"]', '[class*="PromotionPopup"]',
                        '[id*="pop-up"]', '[class*="pop-up"]', '[id*="modal"]'
                    ];
                    
                    selectorsToHide.forEach(s => {
                        document.querySelectorAll(s).forEach(el => {
                            if (['BODY', 'HTML', 'HEADER', 'NAV'].includes(el.tagName)) return;
                            if (['app', 'root', 'main-content', 'header', 'nav'].includes(el.id)) return;
                            el.style.setProperty('display', 'none', 'important');
                        });
                    });
                    
                    // Force allow scrolling (some sites disable it when modal is open)
                    document.body.style.setProperty('overflow', 'auto', 'important');
                    document.documentElement.style.setProperty('overflow', 'auto', 'important');
                    
                    // Hide extremely high z-index elements that might be popups
                    document.querySelectorAll('*').forEach(el => {
                        const style = window.getComputedStyle(el);
                        if (parseInt(style.zIndex) > 100 && !['HEADER', 'NAV', 'BODY', 'HTML'].includes(el.tagName)) {
                            // If it's fixed/absolute and has high z-index, hide it
                            if (style.position === 'fixed' || style.position === 'absolute') {
                                el.style.setProperty('opacity', '0', 'important');
                                el.style.setProperty('pointer-events', 'none', 'important');
                                el.style.setProperty('display', 'none', 'important');
                            }
                        }
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
                    
                    // POC Parity: Force expand all potential scroll containers
                    document.querySelectorAll('*').forEach(el => {
                        const style = window.getComputedStyle(el);
                        if (style.overflowY === 'auto' || style.overflowY === 'scroll' || style.overflow === 'auto' || style.overflow === 'scroll') {
                            el.style.setProperty('height', 'auto', 'important');
                            el.style.setProperty('overflow', 'visible', 'important');
                            el.style.setProperty('overflow-y', 'visible', 'important');
                        }
                        if (style.position === 'fixed' || style.position === 'sticky') {
                            // Don't hide headers/navs, but hide other floating elements that might block view
                            if (!['HEADER', 'NAV'].includes(el.tagName)) {
                                // el.style.setProperty('display', 'none', 'important');
                            }
                        }
                    });

                    // Force eager loading for all images
                    document.querySelectorAll('img').forEach(img => {
                        img.setAttribute('loading', 'eager');
                        const lazyAttr = img.getAttribute('data-src') || img.getAttribute('lazy-src') || img.getAttribute('data-lazy') || img.getAttribute('srcset');
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
            
            # Removed 10s fixed wait; using dynamic ready check instead
            # page.wait_for_timeout(10000) 
            self.browser_utils.wait_for_ready(page)
            
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
            
            page.evaluate("window.scrollTo(0, 0)")
            page.wait_for_timeout(200)
                
            # 8. Take the screenshot. We use full_page=True now that we've stabilized 
            # but we keep the viewport expanded to ensure React components are mounted.
            page.evaluate("window.scrollTo(0, 0)")
            page.wait_for_timeout(200)
            logger.info(f"Taking full-page screenshot...")
            logger.info(f"Setting final viewport height to {capture_height}px for full page screenshot")
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
