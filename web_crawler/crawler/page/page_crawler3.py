import os
import logging
import random
from typing import Optional, Dict
from playwright.sync_api import Page

# Bypass Playwright font loading check during screenshots to avoid timeout hangs
os.environ["PW_TEST_SCREENSHOT_NO_FONTS_READY"] = "1"

from web_crawler.common.config import CrawlConfig
from web_crawler.crawler.helpers.file_manager import FileManager
from web_crawler.common.redis_events import publish_event
from web_crawler.crawler.page.page_crawler2 import BasePageCrawler
from web_crawler.crawler.page.page_crawler_chromium import ChromiumCrawlerMixin
from web_crawler.crawler.page.page_crawler_camoufox import CamoufoxCrawlerMixin
from web_crawler.crawler.helpers.crawler_popups import handle_popups_and_overlays
from web_crawler.crawler.helpers.crawler_screenshot import capture_robust_screenshot

from web_crawler.crawler.page.page_crawler1 import (
    _record_crawl_error
)

logger = logging.getLogger(__name__)


class PageCrawler(BasePageCrawler, ChromiumCrawlerMixin, CamoufoxCrawlerMixin):
    """PageCrawler orchestrates Chromium and Camoufox crawling with enhanced stealth headers."""
    # High‑security sites list used for header Referer adjustments and warm‑up logic
    HIGH_SEC_SITES = [
        "meesho", "delta.com", "jal.co.jp", "united.com", "wayfair.com",
        "zillow.com", "amazon", "google.com", "myaccount.google.com",
        "gcrawlai.com", "luisaviaroma.com", "oracle.com", "usps.com",
        "nike.com", "adidas.com", "homedepot.com", "southwest.com",
        "expedia.com", "neimanmarcus.com", "nordstrom.com", "skyscanner",
        "lowes.com", "rakuten.com", "footlocker.com", "att.com", "booking.com",
        "chewy.com", "autozone.com", "comcast.com", "indeed.com", "gartner.com"
    ]

    def __init__(self, config, file_manager):
        super().__init__(config, file_manager)
        self.high_sec_sites = self.HIGH_SEC_SITES

    def _load_session_state(self, client_id: str, url: str, context_kwargs: dict, browser_type: str = "chromium"):
        if not client_id:
            return
        try:
            from urllib.parse import urlparse
            from web_crawler.common.redis_events import redis_client
            import json
            
            domain_name = urlparse(url).netloc.lower().replace("www.", "")
            redis_key = f"session:{client_id}:{browser_type}:{domain_name}"
            cached_data = redis_client.get(redis_key)
            if cached_data:
                context_kwargs["storage_state"] = json.loads(cached_data)
                logger.info(f"[Stealth Layer] Session State: Loaded persistent state from Redis key '{redis_key}'")
        except Exception as e:
            logger.warning(f"Failed to load session state from Redis: {e}")

    def _save_session_state(self, client_id: str, url: str, context, result: dict, browser_type: str = "chromium"):
        if not client_id or not result or "error" in result:
            return
        try:
            from urllib.parse import urlparse
            from web_crawler.common.redis_events import redis_client
            import json
            
            domain_name = urlparse(url).netloc.lower().replace("www.", "")
            redis_key = f"session:{client_id}:{browser_type}:{domain_name}"
            state_dict = context.storage_state()
            redis_client.setex(redis_key, 86400, json.dumps(state_dict))
            logger.info(f"[Stealth Layer] Session State: Saved persistent state to Redis key '{redis_key}'")
        except Exception as e:
            logger.warning(f"Failed to save session state to Redis: {e}")

    def crawl_page(
        self,
        url: str,
        count: int,
        enable_md: bool,
        enable_html: bool,
        enable_ss: bool,
        enable_seo: bool,
        enable_images: bool,
        enable_json: bool,
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

        custom_proxy_type = (self.config.proxy_type_custom or "").strip().lower()
        
        if custom_proxy_type == "residential":
            start_tier = 1
            end_tier = 2
        elif custom_proxy_type == "datacenter":
            start_tier = 1
            end_tier = 2
        elif custom_proxy_type == "both":
            start_tier = 1
            end_tier = 3
        else:
            requested_proxy_type = (proxy_type or "auto").strip().lower()
            if requested_proxy_type == "none":
                start_tier = 1
            elif requested_proxy_type == "auto":
                start_tier = self.config.default_tier
            else:
                if requested_proxy_type == "enhanced":
                    start_tier = 1
                elif requested_proxy_type == "bright_data" or requested_proxy_type == "nodemaven":
                    start_tier = 2
                elif requested_proxy_type == "basic":
                    start_tier = 1
                elif requested_proxy_type == "stealth":
                    start_tier = 3
                elif requested_proxy_type == "premium":
                    start_tier = 2
                else:
                    start_tier = 1
            end_tier = 3
            
        current_tier = start_tier
        result = None

        while current_tier <= end_tier:
            logger.info("\n" + "="*30 + f"\nTier {current_tier} - Processing\n" + "="*30)
            
            # Start with Chromium as the primary engine for speed
            result = self.crawl_with_chromium(
                url, count, enable_md, enable_html, enable_ss, enable_seo, enable_images, enable_json, client_id, current_tier
            )
            browser_name = "Chromium"
            
            # FALLBACK: If Chromium fails, fall back to Camoufox on the same tier
            if not result or "error" in result:
                logger.warning(f"Chromium failed on Tier {current_tier} (Error: {result.get('error') if result else 'Unknown'}). Falling back to Camoufox on Tier {current_tier}...")
                result = self.crawl_with_camoufox(
                    url, count, enable_md, enable_html, enable_ss, enable_seo, enable_images, enable_json, client_id, current_tier
                )
                browser_name = "Camoufox (Fallback)"
 
            if result and "error" not in result:
                logger.info("\n" + "="*30 + f"\nTier {current_tier} - Success\n" + "="*30)
                logger.info(f"{browser_name} success with Tier {current_tier}: {url}")
                return result
 
            logger.warning("\n" + "="*30 + f"\nTier {current_tier} - Failed\n" + "="*30)
            if current_tier < end_tier:
                logger.warning(f"{browser_name} failed with Tier {current_tier} (Error: {result.get('error') if result else 'Unknown'}). Escalating to Tier {current_tier + 1}...")
                current_tier += 1
            else:
                break
                
        logger.error(f"All browsers and tiers failed for: {url}")
        
        try:
            from api.core.config_setup import load_config
            import os
            from api.services.email_service import EmailService
            
            admin_email = os.getenv("ADMIN_EMAIL")
            if admin_email:
                config = load_config()
                smtp_config = config.get("email", {})
                email_service = EmailService(smtp_config)
                
                last_error = result.get('error') if result else 'Unknown'
                email_service.send_report_issue_email(
                    to_email=admin_email,
                    url_affected=url,
                    issue_related_to=["Crawler Proxy Exhaustion", "All Tiers Failed"],
                    explanation=f"The crawler failed to process this URL across all available proxy tiers and browsers.\\n\\nLast Error: {last_error}"
                )
        except Exception as e:
            logger.error(f"Failed to send alert email for proxy exhaustion: {e}")
        _record_crawl_error(
            crawl_id=client_id,
            url=url,
            error_source="Crawler Orchestrator",
            reason=f"Exhausted all proxy tiers without success.",
            blocked_message=result.get("error") if result else "All attempts failed with no specific error message."
        )
        
        return result

    def scroll_to_bottom(self, page):
        """
        Incrementally scroll page to trigger lazy loading.
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
            page.wait_for_timeout(3000)
        except Exception as e:
            logger.warning(f"Scroll failed: {e}")

    def _handle_popups_and_overlays(self, page: Page):
        handle_popups_and_overlays(page)

    def _capture_robust_screenshot(self, page: Page) -> bytes:
        return capture_robust_screenshot(page, self.config)
