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
    def make_resource_blocker(block_images: bool = False, block_css: bool = False):
        """
        Factory that returns a route handler with configurable blocking.
        
        Args:
            block_images: Block image resource types (safe when screenshots are disabled)
            block_css: Block CSS stylesheets (safe when screenshots are disabled)
        """
        def _block_resources(route: Route) -> None:
            try:
                resource_type = route.request.resource_type
                url = route.request.url.lower()
                
                # Always block fonts and media
                if resource_type in ("font", "media"):
                    route.abort()
                    return
                
                # Conditionally block images
                if block_images and resource_type == "image":
                    route.abort()
                    return
                
                # Conditionally block CSS
                if block_css and resource_type == "stylesheet":
                    route.abort()
                    return
                
                # Block analytics, tracking, and ad networks
                blocked_domains = [
                    "google-analytics", "gtag", "doubleclick",
                    "facebook.com/tr", "hotjar", "clarity",
                    "segment", "mixpanel",
                    "optimizely", "intercom", "crisp.chat",
                    "drift.com", "tawk.to", "zendesk",
                    "hubspot", "pardot", "marketo",
                    "outbrain", "taboola", "adroll",
                    "quantserve", "scorecardresearch", "comscore",
                    "newrelic", "datadoghq", "sentry.io",
                ]
                
                if any(domain in url for domain in blocked_domains):
                    try: 
                        route.abort()
                    except Exception:
                        pass
                    return
                
                try:
                    route.continue_()
                except Exception:
                    pass
            except Exception:
                # Ignore errors such as TargetClosedError or CancelledError
                pass
        
        return _block_resources

    @staticmethod
    def block_resources(route: Route) -> None:
        """Legacy static method — blocks fonts, media, and trackers only."""
        try:
            resource_type = route.request.resource_type
            url = route.request.url.lower()
            
            if resource_type in ("font", "media"):
                route.abort()
                return
            
            blocked_domains = [
                "google-analytics", "gtag", "doubleclick",
                "facebook.com/tr", "hotjar", "clarity",
                "segment", "mixpanel",
                "optimizely", "intercom", "crisp.chat",
                "drift.com", "tawk.to", "zendesk",
                "hubspot", "pardot", "marketo",
                "outbrain", "taboola", "adroll",
                "quantserve", "scorecardresearch", "comscore",
                "newrelic", "datadoghq", "sentry.io",
            ]
            
            if any(domain in url for domain in blocked_domains):
                try: 
                    route.abort()
                except Exception:
                    pass
                return
            
            try:
                route.continue_()
            except Exception:
                pass
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
                "Sec-Fetch-User": "?1",
                "sec-ch-ua-platform": '"Windows"'
            })

        except Exception as e:
            logger.warning(f"Failed to apply stealth settings: {e}")

    
    @staticmethod
    def set_custom_headers(page: Page) -> None:
        """Set custom HTTP headers"""
        try:
            page.set_extra_http_headers({
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
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

    @staticmethod
    def inject_stealth_scripts(page: Page) -> None:
        """
        Inject additional JS-level anti-detection patches.
        These complement playwright-stealth and cover edge cases:
        - navigator.webdriver = undefined
        - window.chrome runtime presence
        - consistent navigator.plugins (non-empty)
        """
        try:
            page.add_init_script("""
                // Mask navigator.webdriver
                Object.defineProperty(navigator, 'webdriver', {
                    get: () => undefined,
                    configurable: true
                });

                // Fake window.chrome (expected by many bot-detectors)
                if (!window.chrome) {
                    window.chrome = {
                        runtime: {
                            onConnect: null,
                            onMessage: null
                        }
                    };
                }

                // Non-empty plugins list (headless Chrome has 0 plugins)
                if (navigator.plugins.length === 0) {
                    Object.defineProperty(navigator, 'plugins', {
                        get: () => [1, 2, 3, 4, 5],
                        configurable: true
                    });
                }

                // Non-empty languages
                Object.defineProperty(navigator, 'languages', {
                    get: () => ['en-US', 'en'],
                    configurable: true
                });

                // Prevent Notification.permission from revealing headless
                if (window.Notification) {
                    Object.defineProperty(Notification, 'permission', {
                        get: () => 'default',
                        configurable: true
                    });
                }
            """)
        except Exception as e:
            logger.warning(f"Failed to inject stealth scripts: {e}")