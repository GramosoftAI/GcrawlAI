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
        except Exception:
            route.continue_()
    
    @staticmethod
    def apply_stealth(page: Page) -> None:
        """
        Apply production-grade stealth settings:
        - Headless-safe fingerprinting
        - Akamai / BotManager resistant
        - Stable (non-random) fingerprints
        """
        try:
            # ⚠️ IMPORTANT: add_init_script runs BEFORE any site JS
            page.add_init_script("""
    (() => {
        const define = Object.defineProperty;

        /* ===================== BASIC AUTOMATION HIDING ===================== */

        define(navigator, 'webdriver', { get: () => undefined, configurable: true });

        define(navigator, 'languages', {
            get: () => ['en-US', 'en'],
            configurable: true
        });

        define(navigator, 'platform', {
            get: () => 'Win32',
            configurable: true
        });

        define(navigator, 'vendor', {
            get: () => 'Google Inc.',
            configurable: true
        });

        define(navigator, 'hardwareConcurrency', {
            get: () => 8,
            configurable: true
        });

        define(navigator, 'deviceMemory', {
            get: () => 8,
            configurable: true
        });

        /* ===================== USER AGENT SANITIZATION ===================== */

        define(navigator, 'userAgent', {
            get: () => navigator.userAgent.replace(/HeadlessChrome/gi, 'Chrome'),
            configurable: true
        });

        define(navigator, 'appVersion', {
            get: () => navigator.appVersion.replace(/HeadlessChrome/gi, 'Chrome'),
            configurable: true
        });

        /* ===================== PLUGINS (Akamai-safe) ===================== */

        const fakePlugins = [
            { name: 'Chrome PDF Plugin', filename: 'internal-pdf-viewer' },
            { name: 'Chrome PDF Viewer', filename: 'mhjfbmdgcfjbbpaeojofohoefgiehjai' },
            { name: 'Native Client', filename: 'internal-nacl-plugin' }
        ];

        define(navigator, 'plugins', {
            get: () => Object.setPrototypeOf(fakePlugins, PluginArray.prototype),
            configurable: true
        });

        /* ===================== CHROME OBJECT ===================== */

        if (!window.chrome) {
            window.chrome = { runtime: {} };
        }

        /* ===================== PERMISSIONS API ===================== */

        const originalQuery = navigator.permissions.query;
        navigator.permissions.query = (parameters) => (
            parameters.name === 'notifications'
                ? Promise.resolve({ state: Notification.permission })
                : originalQuery(parameters)
        );

        /* ===================== HEADLESS-SAFE WINDOW METRICS ===================== */

        define(window, 'outerWidth', {
            get: () => window.innerWidth,
            configurable: true
        });

        define(window, 'outerHeight', {
            get: () => window.innerHeight,
            configurable: true
        });

        define(screen, 'availWidth', {
            get: () => 1920,
            configurable: true
        });

        define(screen, 'availHeight', {
            get: () => 1080,
            configurable: true
        });

        define(screen, 'colorDepth', {
            get: () => 24,
            configurable: true
        });

        /* ===================== WEBGL (STABLE, NOT RANDOM) ===================== */

        const WEBGL_VENDOR = 'Intel Inc.';
        const WEBGL_RENDERER = 'Intel Iris OpenGL Engine';

        const getParameter = WebGLRenderingContext.prototype.getParameter;
        WebGLRenderingContext.prototype.getParameter = function(param) {
            if (param === 37445) return WEBGL_VENDOR;   // UNMASKED_VENDOR_WEBGL
            if (param === 37446) return WEBGL_RENDERER; // UNMASKED_RENDERER_WEBGL
            return getParameter.apply(this, arguments);
        };

        /* ===================== CANVAS (ANTI-FINGERPRINT) ===================== */

        const originalToDataURL = HTMLCanvasElement.prototype.toDataURL;
        HTMLCanvasElement.prototype.toDataURL = function() {
            const ctx = this.getContext('2d');
            if (ctx && this.width === 220 && this.height === 30) {
                ctx.fillStyle = 'rgb(255,255,255)';
                ctx.fillRect(0, 0, this.width, this.height);
            }
            return originalToDataURL.apply(this, arguments);
        };

        /* ===================== BATTERY API ===================== */

        if (navigator.getBattery) {
            navigator.getBattery = async () => ({
                charging: true,
                chargingTime: 0,
                dischargingTime: Infinity,
                level: 1.0
            });
        }

        /* ===================== NETWORK INFO ===================== */

        if (navigator.connection) {
            define(navigator.connection, 'rtt', { get: () => 50, configurable: true });
            define(navigator.connection, 'effectiveType', { get: () => '4g', configurable: true });
        }

    })();
            """)

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