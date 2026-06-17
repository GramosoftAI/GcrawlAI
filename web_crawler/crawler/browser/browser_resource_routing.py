import logging
import re
from playwright.sync_api import Page, Route

logger = logging.getLogger(__name__)


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
            
            # Always block media (fonts are kept to avoid page-loading event issues)
            if resource_type == "media":
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
            
            # Block ad-serving networks and pure trackers matching Firecrawl
            blocked_domains = [
                "doubleclick", "adservice.google.com", "googlesyndication.com",
                "googletagservices.com", "googletagmanager.com", "google-analytics.com",
                "adsystem.com", "adservice.com", "adnxs.com", "ads-twitter.com",
                "facebook.net", "fbcdn.net", "amazon-adsystem.com"
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


def setup_resource_routing(page: Page, block_images: bool = False, block_css: bool = False) -> None:
    """
    Register specific, regex-based native routes in Playwright for fonts, media, 
    ads, and tracking domains, and conditionally images/CSS. This prevents Node-to-Python 
    IPC overhead for other requests.
    """
    # 1. Always block media
    font_media_pattern = re.compile(
        r"\.(mp3|mp4|webm|ogg|wav|flac|avi|mkv|mov|wmv|3gp|m4a)$", 
        re.IGNORECASE
    )
    try:
        page.route(font_media_pattern, lambda route: route.abort())
    except Exception:
        pass

    # 2. Block ad and analytics domains
    trackers_pattern = re.compile(
        r"(doubleclick|adservice\.google\.com|googlesyndication\.com|googletagservices\.com|"
        r"googletagmanager\.com|google-analytics\.com|adsystem\.com|adservice\.com|adnxs\.com|"
        r"ads-twitter\.com|facebook\.net|fbcdn\.net|amazon-adsystem\.com)",
        re.IGNORECASE
    )
    try:
        page.route(trackers_pattern, lambda route: route.abort())
    except Exception:
        pass

    # 3. Conditionally block CSS
    if block_css:
        css_pattern = re.compile(r"\.css(\?.*)?$", re.IGNORECASE)
        try:
            page.route(css_pattern, lambda route: route.abort())
        except Exception:
            pass

    # 4. Conditionally block images
    if block_images:
        image_pattern = re.compile(r"\.(png|jpg|jpeg|gif|svg|webp|ico|bmp|tiff)(\?.*)?$", re.IGNORECASE)
        try:
            page.route(image_pattern, lambda route: route.abort())
        except Exception:
            pass


def block_resources(route: Route) -> None:
    """Legacy static method — blocks fonts, media, and trackers only."""
    try:
        resource_type = route.request.resource_type
        url = route.request.url.lower()
        
        if resource_type == "media":
            route.abort()
            return
        
        blocked_domains = [
            "doubleclick", "adservice.google.com", "googlesyndication.com",
            "googletagservices.com", "googletagmanager.com", "google-analytics.com",
            "adsystem.com", "adservice.com", "adnxs.com", "ads-twitter.com",
            "facebook.net", "fbcdn.net", "amazon-adsystem.com"
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
