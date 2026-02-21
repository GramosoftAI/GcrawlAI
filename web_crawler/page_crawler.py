"""
Individual page crawling logic
"""

import logging
import asyncio
import sys
import json
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


logger = logging.getLogger(__name__)


class PageCrawler:
    """Handle individual page crawling"""
    
    def __init__(self, config: CrawlConfig, file_manager: FileManager):
        self.config = config
        self.file_manager = file_manager
        self.browser_utils = BrowserUtils()
        self.content_processor = ContentProcessor()
    
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
            }
            
        except Exception as e:
            logger.error(f"Error processing page {url}: {e}")
            return None
    
    def crawl_with_chromium(
        self,
        url: str,
        count: int,
        enable_md: bool,
        enable_html: bool,
        enable_ss: bool,
        enable_seo: bool,
        client_id: Optional[str]
    ) -> Optional[Dict]:
        """Crawl page using Chromium with stealth"""
        try:
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
                        '--disable-features=IsolateOrigins,site-per-process'
                    ]
                )
                
                context = browser.new_context(
                    viewport={"width": 1920, "height": 1080},
                    user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
                    java_script_enabled=True,
                    ignore_https_errors=True,
                    bypass_csp=True,
                    extra_http_headers={
                        "sec-ch-ua": '"Not A(Brand";v="99", "Google Chrome";v="121", "Chromium";v="121"',
                        "sec-ch-ua-mobile": "?0",
                        "sec-ch-ua-platform": '"Windows"'
                    }
                )
                
                # Apply stealth directly to context via stealth_sync instead of just page
                from playwright_stealth import Stealth
                Stealth().apply_stealth_sync(context)
                
                page = context.new_page()
                text_content = page.evaluate("document.body.innerText")
                if len(text_content.strip()) < 200:
                    if self.config.use_stealth:
                        self.browser_utils.apply_stealth(page)
                    
                    if self.config.use_custom_headers:
                        self.browser_utils.set_custom_headers(page)
                    
                    page.route("**/*", self.browser_utils.block_resources)
                    # Note: checking cloudflare on about:blank will do nothing, but let's keep it as before
                    self.browser_utils.check_cloudflare(page, self.config)
                    if not self.browser_utils.wait_for_ready(page):
                        page.unroute("**/*")
                        raise Exception("Page not ready")
                
                try:
                    response = page.goto(url, wait_until="domcontentloaded", timeout=60_0000)
                    
                    if not response or response.status != 200:
                        raise Exception(f"HTTP {response.status if response else 'None'}")
                    
                    # Check for cloudflare again after page loads
                    self.browser_utils.check_cloudflare(page, self.config)
                    
                    # Validate content
                    text_content = page.evaluate("document.body.innerText")
                    if len(text_content.strip()) < 200:
                        raise Exception(f"Content too short ({len(text_content.strip())} chars)")
                    
                    result = self.process_page(page, url, count, enable_md, enable_html, enable_ss, enable_seo, client_id)
                    return result
                
                finally:
                    # Clean up routes before closing browser to prevent async TargetClosedError tracebacks
                    try:
                        page.unroute("**/*")
                    except Exception:
                        pass
                    browser.close()
                
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
        client_id: Optional[str]
    ) -> Optional[Dict]:
        """Fallback crawl using Camoufox"""
        if not self.config.camoufox_path:
            logger.warning("Camoufox path not configured")
            return None
        
        try:
            with sync_playwright() as p:
                if platform.system() == "Windows":
                    browser = p.firefox.launch(
                        executable_path=self.config.camoufox_path,
                        headless=self.config.headless
                    )
                elif platform.system() == "Linux":
                    browser = p.firefox.launch(
                        headless=self.config.headless
                    )
                
                try:
                    context = browser.new_context()
                    page = context.new_page()
                    
                    response = page.goto(url, wait_until="domcontentloaded", timeout=60_0000)
                    
                    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                    page.wait_for_timeout(4000)
                    
                    if not response or response.status != 200:
                        return None
                    
                    if not self.browser_utils.wait_for_ready(page):
                        return None
                    
                    result = self.process_page(page, url, count, enable_md, enable_html, enable_ss, enable_seo, client_id)
                    return result
                finally:
                    browser.close()
                
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
        websocket_manager
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
        result = self.crawl_with_chromium(url, count, enable_md, enable_html, enable_ss, enable_seo, client_id)
        
        if result:
            logger.info(f"Chromium success: {url}")
            return result
    
        # Fallback to Camoufox
        logger.info(f"Trying Camoufox fallback for: {url}")
        result = self.crawl_with_camoufox(url, count, enable_md, enable_html, enable_ss, enable_seo, client_id)
        
        if result:
            logger.info(f"Camoufox success: {url}")
        else:
            logger.error(f"All browsers failed for: {url}")
        
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
