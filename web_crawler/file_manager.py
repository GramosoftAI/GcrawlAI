"""
Thread-safe file operations for web crawler
"""

import re
import logging
import threading
from pathlib import Path

logger = logging.getLogger(__name__)


class FileManager:
    """Thread-safe file operations"""
    
    def __init__(self):
        self.lock = threading.Lock()
    
    @staticmethod
    def safe_filename(text: str, max_len: int = 80) -> str:
        """Convert text to safe filesystem name"""
        text = text.strip().replace("&", "and")
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