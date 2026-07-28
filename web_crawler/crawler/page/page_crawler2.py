"""
Base page crawling setup and extraction processor.
"""

import logging
import json
import base64
import random
import time
from typing import Optional, Dict
from bs4 import BeautifulSoup
from playwright.sync_api import Page
from concurrent.futures import ThreadPoolExecutor

from web_crawler.common.config import CrawlConfig

from web_crawler.crawler.helpers.content_processor import ContentProcessor
from web_crawler.common.utils import normalize_url
from web_crawler.common.redis_events import publish_event
from web_crawler.common.proxy_manager import ProxyManager
from web_crawler.crawler.helpers.seo_report import CrawlReportWriter
from web_crawler.crawler.helpers.cleanup_html import clean_html_dynamic



# Import delegates
from web_crawler.crawler.helpers.crawler_helpers import (
    get_filename_from_url,
    is_screenshot_blank,
    is_page_content_blank,
    is_likely_proxy_failure,
)
from web_crawler.crawler.helpers.crawler_captcha import is_captcha_page

logger = logging.getLogger(__name__)


class BasePageCrawler:
    """Base configurations and extractors for PageCrawler"""

    def __init__(self, config: CrawlConfig):
        """Init."""
        self.config = config
        self.content_processor = ContentProcessor()
        self.proxy_manager = ProxyManager()


    def _get_filename_from_url(self, url: str) -> str:
        """Return filename from url."""
        return get_filename_from_url(url)

    def _is_screenshot_blank(self, screenshot_bytes: bytes) -> bool:
        """Return True if screenshot blank."""
        return is_screenshot_blank(screenshot_bytes)

    def _is_page_content_blank(self, title: str, text_content: str, links_count: int) -> bool:
        """Return True if page content blank."""
        return is_page_content_blank(title, text_content, links_count)

    def _is_likely_proxy_failure(self, result: Optional[Dict]) -> bool:
        """Return True if likely proxy failure."""
        return is_likely_proxy_failure(result)

    def _resolve_playwright_proxy(self, target_url: str, provider: str = "nodemaven", use_high_speed: bool = True) -> Optional[Dict]:
        """Resolve playwright proxy."""
        proxy_geo = getattr(self.config, "proxy_geo", None)
        return self.proxy_manager.get_playwright_proxy(target_url=target_url, provider=provider, use_high_speed=use_high_speed, proxy_geo=proxy_geo)

    def is_captcha_page(self, page: Page) -> bool:
        """Return True if captcha page."""
        return is_captcha_page(page)

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
        enable_json: bool,
        client_id: Optional[str],
        status_code: int = 200
    ) -> Optional[Dict]:
        """Process loaded page and extract data"""
        file_prefix = self._get_filename_from_url(url)
        
        try:
            try:
                # Handle popups, cookie banners and overlays BEFORE extracting HTML/Markdown
                if enable_ss or self.config.html_clean or self.config.markdown_clean:
                    self._handle_popups_and_overlays(page)
            except Exception as popup_err:
                logger.warning(f"Failed to handle popups and overlays: {popup_err}")

            # Initial content fetch
            html = page.content()
            soup = BeautifulSoup(html, "lxml")
            check_content = soup.get_text().lower()[:5000]
            links = self.content_processor.extract_links(soup, url)
            
            # Extract page title for artifact labeling
            try:
                raw_title = page.title() or (soup.title.get_text(strip=True) if soup.title else "")
                if not raw_title or raw_title.lower() in ["no title", "untitled", ""]:
                    from urllib.parse import urlparse
                    domain = urlparse(url).netloc
                    if domain.startswith("www."): 
                        domain = domain[4:]
                    page_title = domain.split('.')[0].capitalize()
                else:
                    page_title = raw_title
            except Exception:
                page_title = "Website"

            # Adaptive DOM Polling for dynamic SPA/React page loading if status is 200 OK
            if status_code == 200:
                poll_start = time.time()
                max_poll_time = 10.0
                poll_interval = 0.3
                
                check_content = soup.get_text().lower()[:5000]
                links = self.content_processor.extract_links(soup, url)
                content_blank = self._is_page_content_blank(page_title, check_content, len(links))
                is_initially_sparse = (len(check_content.strip()) < 150 and len(links) < 5)
                
                # Check for clear CAPTCHA/Block keywords so we don't waste time polling
                is_clear_block = False
                block_keywords_fast = ["access denied", "captcha", "security check", "verify your identity", "robot check", "bot check"]
                if any(kw in page_title.lower() or kw in check_content for kw in block_keywords_fast) or self.is_captcha_page(page):
                    is_clear_block = True
                
                if (content_blank or is_initially_sparse) and not is_clear_block:
                    logger.info(f"Initial DOM content blank/sparse for {url} (text: {len(check_content.strip())} chars, links: {len(links)}). Starting adaptive polling (up to {max_poll_time}s)...")
                    while time.time() - poll_start < max_poll_time:
                        page.wait_for_timeout(int(poll_interval * 1000))
                        html = page.content()
                        soup = BeautifulSoup(html, "lxml")
                        check_content = soup.get_text().lower()[:5000]
                        links = self.content_processor.extract_links(soup, url)
                        
                        if any(kw in page_title.lower() or kw in check_content for kw in block_keywords_fast) or self.is_captcha_page(page):
                            logger.info("CAPTCHA or block page detected during polling. Breaking early.")
                            break
                            
                        content_blank = self._is_page_content_blank(page_title, check_content, len(links))
                        is_sparse = (len(check_content.strip()) < 150 and len(links) < 5)
                        if not content_blank and not is_sparse:
                            logger.info(f"DOM content populated successfully after {time.time() - poll_start:.2f}s!")
                            break
            


            # ----------------------------------------------------
            # ----------------------------------------------------
            # CAPTCHA / BLOCK DETECTION
            # ----------------------------------------------------
            current_url = page.url.lower()
            
            # Check URL block patterns (redirects to captcha/checkpoint/access-denied pages)
            url_block_patterns = ["sorry-server", "delta_sorry", "access-denied", "/captcha", "/checkpoint", "/errors/validatecaptcha"]
            is_url_blocked = any(pattern in current_url for pattern in url_block_patterns)
            triggered_reason = f"URL pattern matched" if is_url_blocked else None

            # Check if status code indicates block
            is_status_blocked = status_code in [401, 403, 429]
            if is_status_blocked and not triggered_reason:
                triggered_reason = f"HTTP status code {status_code}"

            # Check for sparse/blank content
            is_sparse_block = False
            stripped_content = check_content.strip()
            if not triggered_reason and len(stripped_content) < 150 and len(links) < 5:
                # Exclude legitimate forms/login pages or pages with a valid title and some text content (>= 20 chars)
                has_inputs = bool(soup.find("input"))
                block_title_keywords = ["access denied", "captcha", "security check", "verify your identity", "robot check", "bot check", "just a moment", "cloudflare", "forbidden", "blocked"]
                is_block_title = any(kw in page_title.lower() for kw in block_title_keywords)
                
                if (has_inputs or not is_block_title) and len(stripped_content) >= 20:
                    # Legitimate sparse page (e.g. login/register form or simple landing page)
                    pass
                else:
                    is_valid_json = False
                    if enable_json:
                        try:
                            json.loads(stripped_content)
                            is_valid_json = True
                        except Exception:
                            pass
                    if not is_valid_json:
                        is_sparse_block = True
                        triggered_reason = f"Blank/Sparse Content ({len(stripped_content)} chars)"

            # Check DOM-level CAPTCHA and block challenges
            is_dom_captcha = self.is_captcha_page(page)
            if is_dom_captcha and not triggered_reason:
                triggered_reason = "CAPTCHA/Challenge detected in DOM"

            is_blocked = is_url_blocked or is_status_blocked or is_sparse_block or is_dom_captcha

            if is_blocked:
                logger.warning(f"Block page detected for {url} (Trigger: {triggered_reason}, Title: {page_title}). Marking as failure for tier rotation.")
                return {"error": f"Block page detected ({triggered_reason})", "status_code": 403}

            # Take screenshot first before CPU/IO/Network tasks block the GIL
            screenshot_bytes = None
            if enable_ss:
                try:
                    screenshot_bytes = self._capture_robust_screenshot(page)
                except Exception as e:
                    logger.error(f"Screenshot Error: {e}")

            # Start CPU/IO/S3 tasks in parallel
            with ThreadPoolExecutor(max_workers=5) as executor:
                # 1. SEO Processing
                def _do_seo():
                    """Do seo."""
                    if not enable_seo: return None
                    try:
                        seo_data = self.content_processor.extract_seo(soup, url)
                        writer = CrawlReportWriter(self.config.output_dir)
                        
                        s_json = writer.render_single_json(seo_data)
                        s_md = writer.render_single_markdown(seo_data)
                        s_xlsx = writer.render_single_excel_base64(seo_data)
                        
                        
                        from web_crawler.common.s3_utils import upload_to_s3
                        seo_xlsx_s3_url = upload_to_s3(
                            base64.b64decode(s_xlsx), 
                            client_id, 
                            f"{file_prefix}_seo.xlsx", 
                            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                        )
                        
                        return {"data": seo_data, "json": s_json, "md": s_md, "xlsx_url": seo_xlsx_s3_url}
                    except Exception as e:
                        logger.error(f"SEO Parallel Task Error: {e}")
                        return None

                # 2. Markdown Processing
                def _do_md():
                    """Do md."""
                    if not enable_md: return None
                    try:
                        md = self.content_processor.convert_to_markdown(html, url, only_main_content=self.config.markdown_clean, ignore_tags=self.config.html_ignore_tags)
                        return md
                    except Exception as e:
                        logger.error(f"MD Parallel Task Error: {e}")
                        return None

                # 3. Image Extraction
                def _do_images():
                    """Do images."""
                    if not enable_images: return None
                    try:
                        imgs = self.content_processor.extract_image_urls(soup, url)
                        return imgs
                    except Exception as e:
                        logger.error(f"Images Parallel Task Error: {e}")
                        return None

                # 4. Screenshot upload to S3 / Artifact storage
                def _do_screenshot_upload():
                    """Do screenshot upload."""
                    if not (enable_ss and screenshot_bytes): return None
                    try:
                        screenshot_b64 = base64.b64encode(screenshot_bytes).decode("utf-8")
                        
                        
                        from web_crawler.common.s3_utils import upload_to_s3
                        fmt = self.config.screenshot_format.lower()
                        ext = "png" if fmt == "png" else "jpg"
                        content_type = "image/png" if fmt == "png" else "image/jpeg"
                        s3_url = upload_to_s3(screenshot_bytes, client_id, f"{file_prefix}.{ext}", content_type)
                        return s3_url
                    except Exception as e:
                        logger.error(f"Screenshot Upload Error: {e}")
                        return None

                # Submit tasks
                f_seo = executor.submit(_do_seo)
                f_md = executor.submit(_do_md)
                f_imgs = executor.submit(_do_images)
                f_ss_upload = executor.submit(_do_screenshot_upload)
                
                seo_res = f_seo.result()
                md_content = f_md.result()
                img_urls = f_imgs.result()
                screenshot_s3_url = f_ss_upload.result()

            seo = seo_res["data"] if seo_res else {}
            title = seo.get("title") or page_title
            
            seo_json_content = None
            seo_md_content = None
            seo_xlsx_s3_url = None
            
            if seo_res:
                seo_json_content = seo_res["json"]
                seo_md_content = seo_res["md"]
                seo_xlsx_s3_url = seo_res.get("xlsx_url")

            md_content = md_content if md_content else None
            images_json = img_urls if img_urls else None

            html_content = None
            if enable_html:
                html_content = clean_html_dynamic(html, url, self.config)

            # Blank Page Detection
            content_blank = self._is_page_content_blank(title, check_content, len(links))

            if content_blank:
                logger.warning(f"Blank content detected for {url}. Escalating tier.")
                return {"error": "Blank page detected", "status_code": 403}

            if client_id:
                publish_event(
                    crawl_id=client_id,
                    payload={
                        "type": "page_processed",
                        "page": count,
                        "url": url,
                        "title": title,
                        "markdown_content": bool(md_content),
                        "html_content": bool(html_content),
                        "screenshot_s3_url": screenshot_s3_url,
                        "seo_json": bool(seo_json_content),
                        "seo_md": bool(seo_md_content),
                        "seo_xlsx_s3_url": seo_xlsx_s3_url,
                        "images": bool(images_json),
                    }
                )

            logger.info(f"Successfully processed: {url}")
            
            page_result = {
                "url": url,
                "canonical": normalize_url(seo.get("canonical") or url),
                "seo": seo,
                "html_content": html_content,
                "screenshot_s3_url": screenshot_s3_url,
                "markdown_content": md_content,
                "seo_json": seo_json_content,
                "seo_md": seo_md_content,
                "seo_xlsx_s3_url": seo_xlsx_s3_url,
                "images_json": images_json,
                "links": links,
                "status_code": page.evaluate("() => window.performance.getEntries()[0].responseStatus") or 200,
            }
            
            return page_result
            
        except Exception as e:
            err_msg = str(e)
            status_code = 500
            if "Timeout" in err_msg:
                status_code = 0
            elif "NS_ERROR_PROXY_BAD_GATEWAY" in err_msg or "ERR_PROXY_CONNECTION_FAILED" in err_msg:
                status_code = 502
            
            logger.error(f"Error processing page {url}: {err_msg}")
            return {"url": url, "error": err_msg, "status_code": status_code}
