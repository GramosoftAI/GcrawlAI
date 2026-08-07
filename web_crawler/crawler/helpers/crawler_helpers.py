import logging
import re
import random
import time
import io
from typing import Optional, Tuple, Dict
from urllib.parse import urlparse
from PIL import Image
from playwright.sync_api import Page

logger = logging.getLogger(__name__)

def get_filename_from_url(url: str) -> str:
    """Return filename from url."""
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


def is_screenshot_blank(screenshot_bytes: bytes) -> bool:
    """
    Heuristic to detect if a screenshot is blank (mostly white or a single color).
    Uses PIL to calculate image entropy or standard deviation.
    """
    if not screenshot_bytes:
        return True
    try:
        img = Image.open(io.BytesIO(screenshot_bytes)).convert("L") # Grayscale
        from PIL import ImageStat
        stat = ImageStat.Stat(img)
        if stat.stddev[0] < 1.0:
            return True
        return False
    except Exception as e:
        logger.error(f"Error validating screenshot blankness: {e}")
        return False


def is_page_content_blank(title: str, text_content: str, links_count: int) -> bool:
    """
    Check if the page content seems blank or stuck on a loader.
    """
    if len(text_content.strip()) < 100 and links_count == 0:
        return True
    if not title and len(text_content.strip()) < 200:
        return True
    return False


def is_likely_proxy_failure(result: Optional[Dict]) -> bool:
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
