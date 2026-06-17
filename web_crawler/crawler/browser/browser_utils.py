"""
Browser utilities for stealth and resource management
"""

import logging
from typing import Optional
from playwright.sync_api import Page, Route
from web_crawler.common.config import CrawlConfig

# Import delegates from sub-modules
from web_crawler.crawler.browser.browser_stealth import (
    generate_stealth_profile as _generate_stealth_profile,
    inject_stealth_scripts as _inject_stealth_scripts,
)
from web_crawler.crawler.browser.browser_navigation import (
    wait_for_ready as _wait_for_ready,
    check_cloudflare as _check_cloudflare,
    erratic_scroll as _erratic_scroll,
)
from web_crawler.crawler.browser.browser_resource_routing import (
    make_resource_blocker as _make_resource_blocker,
    setup_resource_routing as _setup_resource_routing,
    block_resources as _block_resources,
)

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
            "skyscanner", "skyscanner.co.in", "skyscanner.net",
            "jal.co.jp", "jal.co", "meesho", "delta.com", "united.com",
            "wayfair.com", "zillow.com", "amazon", "myaccount.google.com",
            "gcrawlai.com", "luisaviaroma.com", "oracle.com", "usps.com",
            "nike.com", "adidas.com", "homedepot.com", "southwest.com",
            "expedia.com", "neimanmarcus.com", "nordstrom.com", "lowes.com",
            "rakuten.com", "footlocker.com", "att.com", "booking.com",
            "chewy.com", "autozone.com", "comcast.com", "indeed.com", "gartner.com"
        ]
        return any(d in url.lower() for d in protected)

    @staticmethod
    def make_resource_blocker(block_images: bool = False, block_css: bool = False):
        return _make_resource_blocker(block_images, block_css)

    @staticmethod
    def setup_resource_routing(page: Page, block_images: bool = False, block_css: bool = False) -> None:
        _setup_resource_routing(page, block_images, block_css)

    @staticmethod
    def block_resources(route: Route) -> None:
        _block_resources(route)

    @staticmethod
    def apply_stealth(page: Page, extra_headers: dict = None) -> None:
        """
        [DEPRECATED] Headers should be set on context. 
        Stealth scripts are now handled by inject_stealth_scripts.
        """
        pass

    @staticmethod
    def wait_for_ready(page: Page, quick: bool = False) -> bool:
        return _wait_for_ready(page, quick)

    @staticmethod
    def check_cloudflare(page: Page, config: CrawlConfig) -> bool:
        return _check_cloudflare(page, config)

    @staticmethod
    def erratic_scroll(page: Page) -> None:
        _erratic_scroll(page)

    @staticmethod
    def generate_stealth_profile(user_agent: str, locale: str = "en-US") -> dict:
        return _generate_stealth_profile(user_agent, locale)

    @staticmethod
    def inject_stealth_scripts(page: Page, locale: str = "en-US", profile: Optional[dict] = None) -> None:
        _inject_stealth_scripts(page, locale, profile)