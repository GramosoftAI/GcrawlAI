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


