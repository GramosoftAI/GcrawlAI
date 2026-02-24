"""
Utility functions and helper classes
"""

import re
import threading
import asyncio
import logging
from pathlib import Path
from typing import Dict, Optional
import pytz
from datetime import datetime


logger = logging.getLogger(__name__)

from urllib.parse import urlparse, urljoin


BLOCKED_EXTENSIONS = (
    ".pdf", ".jpg", ".jpeg", ".png", ".gif", ".svg",
    ".css", ".js", ".woff", ".woff2", ".ttf", ".mp4",
    ".webm", ".ico"
)

BLOCKED_KEYWORDS = (
    "logout", "signout", "download",
    "mailto:", "tel:", "javascript:"
)


def normalize_url(url: str) -> str:
    """
    Normalize URL to avoid duplicates
    """
    if not url:
        return ""
        
    parsed = urlparse(url)

    path = parsed.path.rstrip("/")
    if not path:
        path = "/"

    normalized = parsed._replace(
        fragment="",
        query="",
        path=path
    )

    return normalized.geturl()


def is_valid_url(url: str, base_origin: str) -> bool:
    """
    Check if URL should be crawled
    """
    try:
        parsed = urlparse(url)
        base = urlparse(base_origin)

        if parsed.scheme not in ("http", "https"):
            return False

        if parsed.netloc != base.netloc:
            return False

        lower = url.lower()

        if lower.endswith(BLOCKED_EXTENSIONS):
            return False

        if any(b in lower for b in BLOCKED_KEYWORDS):
            return False

        return True
    except Exception:
        return False


def absolutize_url(href: str, base_url: str) -> str:
    """
    Convert relative links to absolute URLs
    """
    return urljoin(base_url, href)



class FileManager:
    """Thread-safe file operations"""
    
    def __init__(self):
        self.lock = threading.Lock()
    
    @staticmethod
    def safe_filename(text: str, max_len: int = 80) -> str:
        """Convert text to safe filesystem name"""
        if not text:
            return "page"
        text = str(text).strip().replace("&", "and")
        text = re.sub(r"[^\w\s-]", "", text)
        text = re.sub(r"\s+", "_", text)
        return text[:max_len] if text else "page"
    
    def append_to_file(self, filepath: Path, content: str) -> None:
        """Thread-safe file append"""
        with self.lock:
            try:
                with open(filepath, "a", encoding="utf-8") as f:
                    f.write(content)
            except Exception as e:
                logger.error(f"Failed to write to {filepath}: {e}")


class WebSocketManager:
    """Handle WebSocket updates safely"""
    
    @staticmethod
    def send_update(client_id: Optional[str], manager, message: Dict) -> None:
        """Send WebSocket update if available"""
        if not manager or not client_id:
            return
        
        try:
            loop = asyncio.get_running_loop()
            loop.call_soon_threadsafe(
                asyncio.create_task,
                manager.send_message(client_id, message)
            )
        except RuntimeError:
            logger.debug("No running event loop for WebSocket update")
        except Exception as e:
            logger.warning(f"WebSocket update failed: {e}")
