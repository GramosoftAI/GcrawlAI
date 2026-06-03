"""
Base page crawling setup and extraction processor.
"""

import logging
import json
import os
import re
import random
import time
import io
import base64
from typing import Optional, Dict
from urllib.parse import urlparse
from pathlib import Path
from PIL import Image
from bs4 import BeautifulSoup
from playwright.sync_api import Page
from concurrent.futures import ThreadPoolExecutor

from web_crawler.common.config import CrawlConfig
from web_crawler.crawler.file_manager import FileManager
from web_crawler.crawler.browser_utils import BrowserUtils
from web_crawler.crawler.content_processor import ContentProcessor
from web_crawler.common.utils import normalize_url
from web_crawler.common.redis_events import publish_event
from web_crawler.common.proxy_manager import ProxyManager
from web_crawler.crawler.seo_report import CrawlReportWriter
from web_crawler.crawler.cleanup_html import clean_html_firecrawl_style, clean_html_dynamic

from web_crawler.crawler.page_crawler1 import (
    _store_crawl_artifact,
    browser_manager
)

logger = logging.getLogger(__name__)


class BasePageCrawler:
    """Base configurations and extractors for PageCrawler"""

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

    def _get_filename_from_url(self, url: str) -> str:
        parsed = urlparse(url)
        domain = parsed.netloc
        if domain.startswith("www."):
            domain = domain[4:]
        domain = domain.split('.')[0]
        
        path = parsed.path.strip('/')
        if not path:
            return domain
        
        path = re.sub(r'[^a-zA-Z0-9]+', '_', path)
        return f"{domain}_{path}"

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

        # Removed global BYOP fallback to ensure strict Tier-based isolation as per user request.
        return self.proxy_manager.get_playwright_proxy(tier=proxy_tier, session_id=session_id, target_url=target_url, geo=self.config.proxy_geo)

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
        md_path = None
        html_path = None
        screenshot_path = None
        seo_json_path = None
        seo_md_path = None
        seo_xlsx_path = None
        images_path = None
        
        file_prefix = self._get_filename_from_url(url)
        
        try:
            # Handle popups, cookie banners and overlays BEFORE extracting HTML/Markdown only if screenshots/visuals are enabled
            if enable_ss:
                self._handle_popups_and_overlays(page)

            # Initial content fetch (now clean of popups)
            html = page.content()
            soup = BeautifulSoup(html, "lxml")
            
            # Extract page title for artifact labeling
            try:
                raw_title = page.title() or (soup.title.get_text(strip=True) if soup.title else "")
                if not raw_title or raw_title.lower() in ["no title", "untitled", ""]:
                    domain = urlparse(url).netloc
                    if domain.startswith("www."): 
                        domain = domain[4:]
                    page_title = domain.split('.')[0].capitalize()
                else:
                    page_title = raw_title
            except Exception:
                page_title = "Website"
            
            # Start CPU/IO tasks in parallel while we handle the screenshot
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
                        _store_crawl_artifact(client_id, "seo_json", s_json, page_url=url, title=seo_data.get("title"))
                        _store_crawl_artifact(client_id, "seo_md", s_md, page_url=url, title=seo_data.get("title"))
                        _store_crawl_artifact(client_id, "seo_xlsx", s_xlsx, content_kind="binary", page_url=url, title=seo_data.get("title"))
                        
                        return {"data": seo_data, "json": s_json, "md": s_md, "xlsx": s_xlsx}
                    except Exception as e:
                        logger.error(f"SEO Parallel Task Error: {e}")
                        return None

                # 2. Markdown Processing
                def _do_md():
                    if not enable_md: return None
                    try:
                        md = self.content_processor.convert_to_markdown(html, url, only_main_content=self.config.markdown_clean, ignore_tags=self.config.html_ignore_tags)
                        _store_crawl_artifact(client_id, "markdown", md, page_url=url, title=page_title)
                        return md
                    except Exception as e:
                        logger.error(f"MD Parallel Task Error: {e}")
                        return None

                # 3. Image Extraction
                def _do_images():
                    if not enable_images: return None
                    try:
                        imgs = self.content_processor.extract_image_urls(soup, url)
                        _store_crawl_artifact(client_id, "images", imgs, content_kind="json", page_url=url, title=page_title)
                        return imgs
                    except Exception as e:
                        logger.error(f"Images Parallel Task Error: {e}")
                        return None

                # Submit tasks
                f_seo = executor.submit(_do_seo)
                f_md = executor.submit(_do_md)
                f_imgs = executor.submit(_do_images)
                
                # While those are running in background, we take the screenshot
                screenshot_bytes = None
                screenshot_s3_url = None
                if enable_ss:
                    try:
                        screenshot_bytes = self._capture_robust_screenshot(page)
                        if screenshot_bytes:
                            screenshot_b64 = base64.b64encode(screenshot_bytes).decode("utf-8")
                            _store_crawl_artifact(client_id, "screenshot", screenshot_b64, content_kind="binary", page_url=url, title=page_title)
                            
                            from web_crawler.common.s3_utils import upload_to_s3
                            screenshot_s3_url = upload_to_s3(screenshot_bytes, client_id, f"{file_prefix}.jpg", "image/jpeg")
                    except Exception as e:
                        logger.error(f"Screenshot Error: {e}")

                # Wait for all background tasks to finish
                seo_res = f_seo.result()
                md_content = f_md.result()
                img_urls = f_imgs.result()
                
                # Links extraction
                links = self.content_processor.extract_links(soup, url)

            # Prepare in-memory persistence Payload
            seo = seo_res["data"] if seo_res else {}
            title = seo.get("title") or page_title
            
            seo_json_content = None
            seo_md_content = None
            seo_xlsx_s3_url = None
            
            if seo_res:
                seo_json_content = seo_res["json"]
                seo_md_content = seo_res["md"]
                
                from web_crawler.common.s3_utils import upload_to_s3
                seo_xlsx_s3_url = upload_to_s3(
                    base64.b64decode(seo_res["xlsx"]), 
                    client_id, 
                    f"{file_prefix}_seo.xlsx", 
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                )

            md_content = md_content if md_content else None
            images_json = img_urls if img_urls else None

            html_content = None
            if enable_html:
                html_content = clean_html_dynamic(html, url, self.config)
                _store_crawl_artifact(client_id, "html", html_content, page_url=url, title=page_title)

            # Block detection keywords (instantly parsed from BeautifulSoup RAM instead of slow browser IPC reflow)
            check_content = soup.get_text().lower()[:5000]
            title = seo.get("title") or page_title
            current_url = page.url.lower()
            
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
            
            url_block_patterns = ["sorry-server", "delta_sorry", "access-denied", "/captcha", "/checkpoint"]
            generic_keywords = ["captcha", "blocked", "bot detection", "security check"]
            
            triggered_kw = None
            for kw in block_keywords:
                if kw in title.lower():
                    triggered_kw = kw
                    break
                if kw in check_content:
                    if kw in generic_keywords:
                        if len(check_content.strip()) < 4000 and len(links) < 15:
                            triggered_kw = kw
                            break
                    else:
                        triggered_kw = kw
                        break
            
            is_url_blocked = False
            for pattern in url_block_patterns:
                if pattern in current_url:
                    triggered_kw = f"URL:{pattern}"
                    is_url_blocked = True
                    break

            is_blocked = is_url_blocked or triggered_kw is not None or status_code in [403, 429]
            
            # Blank Page Detection
            if not is_blocked and self.config.js_render:
                content_blank = self._is_page_content_blank(title, check_content, len(links))
                screenshot_blank = False
                if enable_ss and screenshot_bytes:
                    screenshot_blank = self._is_screenshot_blank(screenshot_bytes)
                
                # GROUND TRUTH: If screenshot is NOT blank, the page is NOT blank
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
            
            # Save individual page summary JSON logic moved to database upsert in web_crawler.py
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

    def is_captcha_page(self, page: Page) -> bool:
        """
        Deep check for CAPTCHA pages including iframes and specific bot-challenge elements.
        """
        try:
            # 1. Check Page Title
            title = page.title().lower()
            captcha_title_markers = [
                "just a moment", "access denied", "attention required", 
                "challenge", "not a robot", "pardon our interruption", "bot or not"
            ]
            if any(m in title for m in captcha_title_markers):
                logger.debug(f"CAPTCHA detected via title: {title}")
                return True
            # 2. Check for common CAPTCHA selectors
            existence_selectors = [
                "#sec-if-cpt-container", ".behavioral-content", 
                ".scf-akamai-logo-sec-abc", "#sec-bc-tile-parent",
                "#challenge-form", "#cf-challenge", "#px-captcha", 
                "#distilCaptcha"
            ]
            for selector in existence_selectors:
                try:
                    locator = page.locator(selector)
                    if locator.count() > 0:
                        logger.debug(f"CAPTCHA/Challenge detected via existence selector: {selector}")
                        return True
                except:
                    continue
            # 2b. Selectors that require visibility (like iframes and general widget containers)
            visibility_selectors = [
                "iframe[src*='captcha']", "iframe[src*='recaptcha']", 
                "iframe[src*='hcaptcha']", "iframe[src*='turnstile']",
                ".g-recaptcha", ".h-captcha"
            ]
            for selector in visibility_selectors:
                try:
                    count = page.locator(selector).count()
                    if count > 0:
                        if selector.startswith("iframe"):
                            is_real_captcha = False
                            for i in range(count):
                                elem = page.locator(selector).nth(i)
                                src = elem.get_attribute("src") or ""
                                if "size=invisible" in src:
                                    continue
                                
                                try:
                                    box = elem.bounding_box()
                                    if box and box["width"] > 0 and box["height"] > 0:
                                        is_real_captcha = True
                                        break
                                except:
                                    if elem.is_visible():
                                        is_real_captcha = True
                                        break
                            if is_real_captcha:
                                logger.debug(f"CAPTCHA detected via selector: {selector}")
                                return True
                        else:
                            is_visible = False
                            for i in range(count):
                                elem = page.locator(selector).nth(i)
                                try:
                                    box = elem.bounding_box()
                                    if box and box["width"] > 0 and box["height"] > 0:
                                        is_visible = True
                                        break
                                except:
                                    if elem.is_visible():
                                        is_visible = True
                                        break
                            if is_visible:
                                logger.debug(f"CAPTCHA detected via selector: {selector}")
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
                    logger.debug("CAPTCHA detected via text content.")
                    return True
            
            return False
        except Exception as e:
            logger.debug(f"Captcha detection check failed: {e}")
            return False
