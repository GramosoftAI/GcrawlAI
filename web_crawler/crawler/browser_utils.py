"""
Browser utilities for stealth and resource management
"""

import time
import random
import logging
from playwright.sync_api import Page, Route
from web_crawler.common.config import CrawlConfig

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
            "skyscanner", "skyscanner.co.in", "skyscanner.net"
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
    def apply_stealth(page: Page, extra_headers: dict = None) -> None:
        """
        [DEPRECATED] Headers should be set on context. 
        Stealth scripts are now handled by inject_stealth_scripts.
        """
        pass

    @staticmethod
    def wait_for_ready(page: Page) -> bool:
        """Wait for page to be ready"""
        try:
            # Use networkidle to ensure background images and pricing data load
            page.wait_for_load_state("networkidle", timeout=8000)
            return True
        except Exception:
            try:
                # Fallback to domcontentloaded if network stays busy (common on ad-heavy sites)
                page.wait_for_load_state("domcontentloaded", timeout=12000)
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
    def erratic_scroll(page: Page) -> None:
        """
        POC Parity: Perform human-like irregular scroll to trigger lazy loading 
        and generate behavioral telemetry. Enhanced with mouse jiggling.
        """
        try:
            logger.info("[Stealth Layer] Behavioral Simulation: Executing erratic scroll sequence.")
            
            # Initial random mouse move
            page.mouse.move(random.randint(100, 800), random.randint(100, 600))
            
            # POC Parity: Handle both window and nested div scrolling
            page.evaluate("""
                async () => {
                    const getTallestScrollable = () => {
                        const elements = document.querySelectorAll('*');
                        let tallest = document.scrollingElement || document.documentElement;
                        let maxH = tallest.scrollHeight;
                        
                        for (const el of elements) {
                            const h = el.scrollHeight;
                            if (h > maxH && getComputedStyle(el).overflowY !== 'hidden') {
                                maxH = h;
                                tallest = el;
                            }
                        }
                        return tallest;
                    };

                    const scrollTarget = getTallestScrollable();
                    let currentY = 0;
                    const maxScroll = 15000;
                    
                    while (currentY < maxScroll) {
                        const scrollHeight = scrollTarget.scrollHeight;
                        const step = Math.floor(Math.random() * 800) + 200;
                        
                        if (scrollTarget === window || scrollTarget === document.documentElement || scrollTarget === document.body) {
                            window.scrollBy({ top: step, behavior: 'auto' });
                        } else {
                            scrollTarget.scrollBy({ top: step, behavior: 'auto' });
                        }
                        
                        currentY += step;
                        if (currentY >= scrollHeight) break;
                        
                        const delay = Math.floor(Math.random() * 100) + 50;
                        await new Promise(r => setTimeout(r, delay));
                    }
                    
                    // Final jump to bottom to ensure everything is triggered
                    if (scrollTarget.scrollTo) scrollTarget.scrollTo(0, scrollTarget.scrollHeight);
                }
            """)
            
            # Short wait for any late lazy-loading
            page.wait_for_timeout(1500)
            
            # Post-scroll jiggle removed for speed
            page.wait_for_timeout(200)
        except Exception as e:
            logger.debug(f"Erratic scroll failed (ignoring): {e}")

    @staticmethod
    def inject_stealth_scripts(page: Page) -> None:
        """
        Inject additional JS-level anti-detection patches.
        """
        try:
            page.add_init_script("""
                // Mask navigator.webdriver
                Object.defineProperty(navigator, 'webdriver', {
                    get: () => undefined,
                    configurable: true
                });

                // Fake window.chrome
                if (!window.chrome) {
                    window.chrome = {
                        runtime: {
                            onConnect: null,
                            onMessage: null
                        }
                    };
                }

                // POC Parity: Real Desktop Plugins
                const mockPlugin = { name: 'PDF Viewer', filename: 'internal-pdf-viewer', description: 'Portable Document Format' };
                Object.defineProperty(navigator, 'plugins', {
                    get: () => [mockPlugin],
                    configurable: true
                });

                // POC Parity: 0 for Desktop
                Object.defineProperty(navigator, 'maxTouchPoints', {
                    get: () => 0,
                    configurable: true
                });

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