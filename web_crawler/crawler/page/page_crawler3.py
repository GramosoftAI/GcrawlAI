import os
import logging
import random
from typing import Optional, Dict
from playwright.sync_api import Page

# Bypass Playwright font loading check during screenshots to avoid timeout hangs
os.environ["PW_TEST_SCREENSHOT_NO_FONTS_READY"] = "1"

from web_crawler.common.redis_events import publish_event
from web_crawler.crawler.page.page_crawler2 import BasePageCrawler
from web_crawler.crawler.page.page_crawler_cloak import CloakCrawlerMixin
from web_crawler.crawler.helpers.crawler_popups import handle_popups_and_overlays
from web_crawler.crawler.helpers.crawler_screenshot import capture_robust_screenshot

from web_crawler.crawler.page.page_crawler1 import (
    _record_crawl_error
)

logger = logging.getLogger(__name__)


class PageCrawler(BasePageCrawler, CloakCrawlerMixin):
    """PageCrawler orchestrates CloakBrowser crawling with Nodemaven -> Evomi fallback."""
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

    def __init__(self, config):
        """Init."""
        super().__init__(config)
        self.high_sec_sites = self.HIGH_SEC_SITES

    def _load_session_state(self, client_id: str, url: str, context_kwargs: dict, browser_type: str = "cloak"):
        """Load session state."""
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

    def _save_session_state(self, client_id: str, url: str, context, result: dict, browser_type: str = "cloak"):
        """Save session state."""
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
        """Crawl a single page using Evomi Premium -> Nodemaven -> Evomi Core loop"""
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

        # Load attempt order from environment with default fallback values
        attempt_1 = os.getenv("ATTEMPT_1", "evomi_premium").strip().lower()
        attempt_2 = os.getenv("ATTEMPT_2", "nodemaven").strip().lower()
        attempt_3 = os.getenv("ATTEMPT_3", "evomi_core").strip().lower()

        provider_names = {
            "evomi_premium": "Evomi Premium",
            "nodemaven": "Nodemaven",
            "evomi_core": "Evomi Core"
        }

        # Normalize configured providers from environment
        configured_pids = []
        for pid in [attempt_1, attempt_2, attempt_3]:
            if pid and pid in provider_names:
                configured_pids.append(pid)
        if not configured_pids:
            configured_pids = ["evomi_premium", "nodemaven", "evomi_core"]

        providers = []
        for pid in configured_pids:
            p_name = provider_names[pid]
            providers.append((p_name, pid))

        result = None
        proxy_attempt_count = 0
        proxy_attempts = []
        bandwidth_usage = {}

        for idx, (provider_name, provider_id) in enumerate(providers):
            attempt = idx + 1
            logger.info("\n" + "="*30 + f"\nAttempt {attempt}/3 - Provider: {provider_name}\n" + "="*30)
            
            # Enable high-speed ISP targeting for high-speed supporting providers
            use_high_speed = (provider_id in {"nodemaven", "evomi_premium"})
            if not use_high_speed:
                logger.info(f"Disabling high-speed ISP targeting for provider {provider_name}.")
            
            # Resolve proxy settings for recording
            proxy_geo = getattr(self.config, "proxy_geo", None)
            proxy_settings = self.proxy_manager.get_playwright_proxy(
                target_url=url,
                provider=provider_id,
                use_high_speed=use_high_speed,
                proxy_geo=proxy_geo
            )
            if proxy_settings:
                proxy_attempts.append({
                    "provider": provider_name,
                    "server": proxy_settings.get("server", ""),
                    "username": proxy_settings.get("username", ""),
                    "password": proxy_settings.get("password", "")
                })
            else:
                proxy_attempts.append({
                    "provider": "Direct Connection",
                    "server": "direct",
                    "username": "",
                    "password": ""
                })

            result = self.crawl_with_cloakbrowser(
                url, count, enable_md, enable_html, enable_ss, enable_seo, enable_images, enable_json, client_id, provider_id,
                use_high_speed=use_high_speed
            )
            if result:
                bandwidth_usage[provider_id] = result.pop("bandwidth_bytes", 0)
                result["proxy_usage"] = bandwidth_usage
 
            if result and "error" not in result:
                logger.info("\n" + "="*30 + f"\nAttempt {attempt}/3 - Success\n" + "="*30)
                logger.info(f"CloakBrowser ({provider_name}) success for: {url}")
                return result
 
            logger.warning("\n" + "="*30 + f"\nAttempt {attempt}/3 - Failed\n" + "="*30)
            if attempt < len(providers):
                logger.warning(f"CloakBrowser ({provider_name}) failed (Error: {result.get('error') if result else 'Unknown'}). Escalating...")
            else:
                break
                
        logger.error(f"All providers exhausted for: {url}")
        
        try:
            from api.core.config_setup import load_config
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
                    issue_related_to=["Crawler Proxy Exhaustion", "All Providers Failed"],
                    explanation=f"The crawler failed to process this URL across both Nodemaven and Evomi.\\n\\nLast Error: {last_error}"
                )
        except Exception as e:
            logger.error(f"Failed to send alert email for proxy exhaustion: {e}")
            
        # Retrieve the original dynamic request payload from the config if available
        request_params = getattr(self.config, "raw_payload", None)
        if not request_params:
            request_params = {
                "url": url,
                "proxy": {
                    "geo": self.config.proxy_geo if self.config.proxy_geo else "IN"
                },
                "markdown": {
                    "enabled": enable_md,
                    "clean": getattr(self.config, "markdown_clean", True)
                },
                "html": {
                    "enabled": enable_html,
                    "clean": getattr(self.config, "html_clean", True),
                    "remove_external_links": getattr(self.config, "html_remove_external_links", False),
                    "relative_to_absolute_links": getattr(self.config, "html_relative_to_absolute_links", True),
                    "remove_data_images": getattr(self.config, "html_remove_data_images", False),
                    "ignore_tags": getattr(self.config, "html_ignore_tags", [])
                },
                "screenshot": {
                    "enabled": enable_ss,
                    "full_page": getattr(self.config, "screenshot_full_page", True),
                    "format": getattr(self.config, "screenshot_format", "png"),
                    "quality": getattr(self.config, "screenshot_quality", 90),
                    "js_render": getattr(self.config, "js_render", True),
                    "render_timeout": getattr(self.config, "render_timeout", 30000),
                    "auto_scroll": getattr(self.config, "auto_scroll", True),
                    "scroll_delay": getattr(self.config, "scroll_delay", 500),
                    "max_scrolls": getattr(self.config, "max_scrolls", 10)
                },
                "seo": {
                    "enabled": enable_seo
                },
                "images": {
                    "enabled": enable_images
                }
            }

        _record_crawl_error(
            crawl_id=client_id,
            url=url,
            error_source="Crawler Orchestrator",
            reason=f"Exhausted all proxy providers without success.",
            blocked_message=result.get("error") if result else "All attempts failed with no specific error message.",
            proxy_attempts=proxy_attempts,
            request_params=request_params
        )
        if result:
            result["proxy_usage"] = bandwidth_usage
        return result


    def _handle_popups_and_overlays(self, page: Page):
        """Handle popups and overlays."""
        handle_popups_and_overlays(page)

    def _capture_robust_screenshot(self, page: Page) -> bytes:
        """Capture robust screenshot."""
        return capture_robust_screenshot(page, self.config)
