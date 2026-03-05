"""
Proxy management and rotation logic
"""

import random
import logging
from typing import List, Optional, Union

logger = logging.getLogger(__name__)

class ProxyManager:
    """
    Handles proxy rotation. 
    Supports a single proxy string, a list of proxy strings, or None.
    """
    def __init__(self, proxies: Union[str, List[str], None] = None):
        if isinstance(proxies, str):
            # If it's a comma-separated string, split it
            if "," in proxies:
                self.proxies = [p.strip() for p in proxies.split(",") if p.strip()]
            else:
                self.proxies = [proxies]
        elif isinstance(proxies, list):
            self.proxies = [p for p in proxies if p]
        else:
            self.proxies = []
        
        if self.proxies:
            logger.info(f"✓ ProxyManager initialized with {len(self.proxies)} proxies.")
        else:
            logger.debug("ProxyManager initialized with no proxies.")

    def get_proxy(self) -> Optional[str]:
        """
        Returns a random proxy from the list.
        Returns None if no proxies are configured.
        """
        if not self.proxies:
            return None
        
        selected = random.choice(self.proxies)
        logger.debug(f"Rotating proxy: {selected}")
        return selected

    def has_proxies(self) -> bool:
        """Check if any proxies are configured."""
        return len(self.proxies) > 0
