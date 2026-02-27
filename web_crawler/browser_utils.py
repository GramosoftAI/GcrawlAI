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
    def is_protected_domain(url: str) -> bool:
        """
        Returns True for domains known to use loaded resources (fonts, scripts, etc.)
        as part of their bot-detection / fingerprinting pipeline.
        Resource-blocking on these domains reveals the browser as a bot.
        """
        protected = [
            "google.com", "googleapis.com", "gstatic.com",
            "bing.com", "yahoo.com", "yandex.com",
        ]
        return any(d in url.lower() for d in protected)

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
                try: 
                    route.abort()
                except Exception:
                    pass
                return
            
            # Don't block essential resources for protected domains
            protected_resources = [
                "google.com", "gstatic.com", "googleapis.com"
            ]
            if any(domain in url for domain in protected_resources):
                try:
                    route.continue_()
                except Exception:
                    pass
                return
            
            try:
                route.continue_()
            except Exception:
                pass
        except Exception as e:
            # Ignore errors such as TargetClosedError or CancelledError
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
                'Upgrade-Insecure-Requests': '1',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7'
            })
        except Exception as e:
            logger.warning(f"Failed to set custom headers: {e}")
    
    @staticmethod
    def wait_for_ready(page: Page) -> bool:
        """Wait for page to be ready"""
        try:
            page.wait_for_load_state("networkidle", timeout=5000)
            return True
        except Exception:
            try:
                page.wait_for_load_state("domcontentloaded", timeout=15000)
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
