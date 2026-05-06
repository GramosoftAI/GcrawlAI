import os
import logging
import random
from typing import List, Optional, Union, Dict

logger = logging.getLogger(__name__)

class ProxyManager:
    """
    Handles proxy rotation based on Tiers (1-7).
    """

    def __init__(self, **kwargs):
        self.tiers = {}
        self._load_tiers_from_env()

    def _load_tiers_from_env(self):
        """Loads TIER_1 to TIER_7 configurations from environment variables."""
        for tier in range(1, 8):
            enabled = os.getenv(f"TIER_{tier}_ENABLED", "False").lower() == "true"
            if not enabled:
                continue

            host = os.getenv(f"TIER_{tier}_PROXY_HOST")
            port = os.getenv(f"TIER_{tier}_PROXY_PORT")
            user = os.getenv(f"TIER_{tier}_PROXY_USER")
            password = os.getenv(f"TIER_{tier}_PROXY_PASS")
            name = os.getenv(f"TIER_{tier}_NAME", f"Tier {tier}")
            geo = os.getenv(f"TIER_{tier}_GEO", "Global")

            if host and port:
                self.tiers[tier] = {
                    "name": name,
                    "host": host,
                    "port": port,
                    "username": user,
                    "password": password,
                    "geo": geo
                }
            elif tier == 1:
                # Tier 1 is usually Direct (No Proxy)
                self.tiers[tier] = {"name": name, "direct": True, "geo": "Global"}

        logger.info(f"ProxyManager initialized with {len(self.tiers)} active proxy tiers.")

    def _resolve_tier(self, proxy_type_or_tier: Union[str, int]) -> int:
        if isinstance(proxy_type_or_tier, int):
            return proxy_type_or_tier
            
        ptype = str(proxy_type_or_tier).strip().lower()
        if ptype == "none":
            return 1
        elif ptype == "basic":
            return 2
        elif ptype == "stealth":
            return 3
        elif ptype == "enhanced":
            return 4
        elif ptype == "auto":
            return 2
            
        if ptype.isdigit():
            return int(ptype)
            
        return 2

    def get_playwright_proxy(self, tier: Union[int, str] = 1) -> Optional[dict]:
        """Returns a dict suitable for Playwright's proxy argument based on Tier."""
        resolved_tier = self._resolve_tier(tier)
        tier_config = self.tiers.get(resolved_tier)
        
        if not tier_config or tier_config.get("direct"):
            return None # No proxy
            
        server = f"http://{tier_config['host']}:{tier_config['port']}"
        proxy_dict = {"server": server}
        
        if tier_config.get("username") and tier_config.get("password"):
            proxy_dict["username"] = tier_config["username"]
            
            password = tier_config["password"]
            if tier_config.get("geo", "").lower() == "india":
                # Only append if not already present
                if "_country-in" not in password.lower():
                    password = f"{password}_country-IN"
            
            proxy_dict["password"] = password
            
        logger.debug(f"Using proxy tier {resolved_tier}: {tier_config['name']}")
        return proxy_dict

    def get_proxy(self, tier: Union[int, str] = 1) -> Optional[str]:
        """Returns a string proxy URL."""
        resolved_tier = self._resolve_tier(tier)
        tier_config = self.tiers.get(resolved_tier)
        
        if not tier_config or tier_config.get("direct"):
            return None
            
        auth = ""
        if tier_config.get("username") and tier_config.get("password"):
            password = tier_config["password"]
            if tier_config.get("geo", "").lower() == "india":
                if "_country-in" not in password.lower():
                    password = f"{password}_country-IN"
            
            auth = f"{tier_config['username']}:{password}@"
            
        return f"http://{auth}{tier_config['host']}:{tier_config['port']}"

    def get_requests_proxies(self, proxy_type: Union[int, str] = "basic") -> Optional[dict]:
        """Returns a dict suitable for requests proxies argument."""
        proxy_url = self.get_proxy(proxy_type)
        if not proxy_url:
            return None
        return {"http": proxy_url, "https": proxy_url}

