"""
Proxy management and rotation logic
"""

import logging
import random
from typing import List, Optional, Union

logger = logging.getLogger(__name__)


class ProxyManager:
    """
    Handles proxy rotation.
    Supports legacy, basic, stealth, and enhanced pools.
    """

    def __init__(
        self,
        proxies: Union[str, List[str], None] = None,
        basic_proxies: Union[str, List[str], None] = None,
        stealth_proxies: Union[str, List[str], None] = None,
        enhanced_proxies: Union[str, List[str], None] = None,
    ):
        self.proxies = self._parse_proxies(proxies)
        self.basic_proxies = self._parse_proxies(basic_proxies)
        self.stealth_proxies = self._parse_proxies(stealth_proxies)
        self.enhanced_proxies = self._parse_proxies(enhanced_proxies)

        logger.info(
            "ProxyManager initialized: "
            f"{len(self.proxies)} legacy, "
            f"{len(self.basic_proxies)} basic, "
            f"{len(self.stealth_proxies)} stealth, "
            f"{len(self.enhanced_proxies)} enhanced."
        )

    def _parse_proxies(self, proxies: Union[str, List[str], None]) -> List[str]:
        if isinstance(proxies, str):
            if "," in proxies:
                return [p.strip() for p in proxies.split(",") if p.strip()]
            return [proxies]
        if isinstance(proxies, list):
            return [p for p in proxies if p]
        return []

    def get_proxy(self, proxy_type: str = "basic") -> Optional[str]:
        """
        Returns a random proxy from the requested pool.
        Types: "basic", "stealth", "enhanced", "legacy"
        """
        proxy_type = (proxy_type or "basic").strip().lower()

        target_list = self.basic_proxies
        if proxy_type == "stealth":
            target_list = self.stealth_proxies
        elif proxy_type == "enhanced":
            target_list = self.enhanced_proxies
        elif proxy_type == "legacy":
            target_list = self.proxies

        # Fallback logic
        if not target_list:
            if proxy_type == "basic":
                target_list = self.proxies  # Use legacy if no basic pool
            elif proxy_type == "stealth":
                target_list = self.basic_proxies or self.proxies
            elif proxy_type == "enhanced":
                target_list = (
                    self.stealth_proxies or self.basic_proxies or self.proxies
                )

        if not target_list:
            logger.warning(f"No proxies available for type: {proxy_type}")
            return None

        selected = random.choice(target_list)
        logger.debug(f"Rotating {proxy_type} proxy: {selected}")
        return selected

    def has_proxies(self, proxy_type: str = "any") -> bool:
        """Check if proxies of requested type are configured."""
        proxy_type = (proxy_type or "any").strip().lower()

        if proxy_type == "basic":
            return len(self.basic_proxies) > 0 or len(self.proxies) > 0
        if proxy_type == "stealth":
            return len(self.stealth_proxies) > 0
        if proxy_type == "enhanced":
            return (
                len(self.enhanced_proxies) > 0
                or len(self.stealth_proxies) > 0
                or len(self.basic_proxies) > 0
                or len(self.proxies) > 0
            )
        return (
            len(self.proxies) > 0
            or len(self.basic_proxies) > 0
            or len(self.stealth_proxies) > 0
            or len(self.enhanced_proxies) > 0
        )

    def get_requests_proxies(self, proxy_type: str = "basic") -> Optional[dict]:
        """Returns a dict suitable for requests proxies argument."""
        proxy = self.get_proxy(proxy_type)
        if not proxy:
            return None
        return {"http": proxy, "https": proxy}

    def get_playwright_proxy(self, proxy_type: str = "basic") -> Optional[dict]:
        """Returns a dict suitable for Playwright's proxy argument."""
        proxy = self.get_proxy(proxy_type)
        if not proxy:
            return None

        # Parse http://user:pass@host:port or host:port
        if "://" in proxy:
            from urllib.parse import urlparse

            parsed = urlparse(proxy)
            server = f"{parsed.scheme}://{parsed.hostname or parsed.netloc}"
            if parsed.port:
                server += f":{parsed.port}"

            p_dict = {"server": server}
            if parsed.username:
                p_dict["username"] = parsed.username
            if parsed.password:
                p_dict["password"] = parsed.password
            return p_dict

        return {"server": proxy}
