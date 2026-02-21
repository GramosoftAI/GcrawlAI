"""
Browser utilities for stealth and resource management
"""

import time
import logging
from playwright.sync_api import Page, Route
from web_crawler.config import CrawlConfig

logger = logging.getLogger(__name__)


class BrowserUtils:
    """Browser configuration and stealth utilities"""
    
    @staticmethod
    def block_resources(route: Route) -> None:
        """Block unnecessary resources for faster loading"""
        try:
            resource_type = route.request.resource_type
            url = route.request.url.lower()
            
            # Block fonts and media
            if resource_type in ("font", "media"):
                route.abort()
                return
            
            # Block analytics and tracking
            blocked_domains = [
                "google-analytics", "gtag", "doubleclick",
                "facebook.com/tr", "hotjar", "clarity",
                "segment", "mixpanel"
            ]
            
            if any(domain in url for domain in blocked_domains):
                route.abort()
                return
            
            route.continue_()
        except Exception as e:
            # Ignore errors such as TargetClosedError when the page is closed
            # during request interception.
            try:
                route.continue_()
            except Exception:
                pass

    @staticmethod
    def apply_stealth(page: Page) -> None:
        """
        Apply production-grade stealth settings using playwright-stealth
        """
        try:
            from playwright_stealth import Stealth
            Stealth().apply_stealth_sync(page)

            # HTTP headers must match browser reality
            page.set_extra_http_headers({
                "Accept-Language": "en-US,en;q=0.9",
                "Accept-Encoding": "gzip, deflate, br",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
                "Upgrade-Insecure-Requests": "1",
                "Sec-Fetch-Dest": "document",
                "Sec-Fetch-Mode": "navigate",
                "Sec-Fetch-Site": "none",
                "Sec-Fetch-User": "?1"
            })

        except Exception as e:
            logger.warning(f"Failed to apply stealth settings: {e}")

    
    @staticmethod
    def set_custom_headers(page: Page) -> None:
        """Set custom HTTP headers"""
        try:
            page.set_extra_http_headers({
                'Accept-Language': 'en-US,en;q=0.9',
                'Accept-Encoding': 'gzip, deflate, br',
                'Referer': 'https://www.google.com/',
                'Upgrade-Insecure-Requests': '1'
            })
        except Exception as e:
            logger.warning(f"Failed to set custom headers: {e}")
    
    @staticmethod
    def wait_for_ready(page: Page) -> bool:
        """Wait for page to be ready"""
        try:
            page.wait_for_load_state("networkidle", timeout=3000)
            return True
        except Exception:
            try:
                page.wait_for_load_state("domcontentloaded", timeout=10_000)
                return True
            except Exception:
                return False
    
    @staticmethod
    def check_cloudflare(page: Page, config: CrawlConfig) -> bool:
        """Check and attempt to bypass Cloudflare"""
        if not config.bypass_cloudflare:
            return True
        
        try:
            content = page.content().lower()
            if "cloudflare" not in content and "ray id" not in content:
                return True
            
            logger.info("Cloudflare detected, waiting...")
            
            if config.simulate_human:
                for _ in range(2):
                    page.mouse.move(100, 100)
                    time.sleep(0.2)
                    page.mouse.move(200, 200)
                    time.sleep(0.2)
            
            time.sleep(3)
            return True
            
        except Exception as e:
            logger.warning(f"Cloudflare check failed: {e}")
            return False