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


def simulate_human_mouse(page: Page, target_x: int, target_y: int, start_x: Optional[int] = None, start_y: Optional[int] = None) -> Tuple[int, int]:
    """
    Simulates advanced human-like mouse movement using a Cubic Bezier curve
    with variable speed, organic jitter, and acceleration/deceleration.
    Returns the final coordinates.
    """
    try:
        if start_x is None or start_y is None:
            start_x = random.randint(10, 500)
            start_y = random.randint(10, 500)
        
        # If distance is very small, just move directly with minor steps
        distance = ((target_x - start_x) ** 2 + (target_y - start_y) ** 2) ** 0.5
        if distance < 30:
            page.mouse.move(target_x, target_y, steps=random.randint(1, 3))
            return target_x, target_y
        
        # Generate two random control points inside the bounding box of start and end
        control_x1 = start_x + (target_x - start_x) * random.uniform(0.1, 0.4) + random.randint(-50, 50)
        control_y1 = start_y + (target_y - start_y) * random.uniform(0.1, 0.4) + random.randint(-50, 50)
        control_x2 = start_x + (target_x - start_x) * random.uniform(0.6, 0.9) + random.randint(-50, 50)
        control_y2 = start_y + (target_y - start_y) * random.uniform(0.6, 0.9) + random.randint(-50, 50)
        
        # Determine number of steps based on distance
        steps = int(max(10, min(30, distance / 25)))
        
        for i in range(steps + 1):
            t = i / steps
            # Apply an easing function (cubic easing in-out) to mimic acceleration/deceleration
            eased_t = 3 * (t ** 2) - 2 * (t ** 3)
            
            # Cubic Bezier formula
            x = (1 - eased_t) ** 3 * start_x + 3 * (1 - eased_t) ** 2 * eased_t * control_x1 + 3 * (1 - eased_t) * eased_t ** 2 * control_x2 + eased_t ** 3 * target_x
            y = (1 - eased_t) ** 3 * start_y + 3 * (1 - eased_t) ** 2 * eased_t * control_y1 + 3 * (1 - eased_t) * eased_t ** 2 * control_y2 + eased_t ** 3 * target_y
            
            # Add minor hand jitter
            if i < steps:
                x += random.uniform(-1, 1)
                y += random.uniform(-1, 1)
            
            page.mouse.move(int(x), int(y))
            
            # Sleep a tiny bit to mimic real time motion (variable duration)
            # Faster in middle, slower at start/end
            sleep_time = random.uniform(0.002, 0.008)
            if t < 0.15 or t > 0.85:
                sleep_time += random.uniform(0.005, 0.01)
            time.sleep(sleep_time)
            
        return target_x, target_y
    except Exception as e:
        logger.debug(f"Human mouse move failed: {e}")
        try:
            page.mouse.move(target_x, target_y)
        except:
            pass
        return target_x, target_y


def get_filename_from_url(url: str) -> str:
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
