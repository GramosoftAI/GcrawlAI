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
        """Loads TIER_1 to TIER_9 configurations from environment variables."""
        for tier in range(1, 11):
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
        elif ptype == "mobile":
            return 2
        elif ptype == "bright_data":
            return 3
        elif ptype == "basic":
            return 4
        elif ptype == "stealth":
            return 6
        elif ptype == "enhanced":
            return 7
        elif ptype == "auto":
            return 4 # Starting point for auto escalation
            
        if ptype.isdigit():
            return int(ptype)
            
        return 3 # Default to basic

    def get_playwright_proxy(self, tier: Union[int, str] = 1, session_id: Optional[str] = None, target_url: Optional[str] = None, geo: Optional[str] = None) -> Optional[dict]:
        """Returns a dict suitable for Playwright's proxy argument based on Tier."""
        resolved_tier = self._resolve_tier(tier)
        tier_config = self.tiers.get(resolved_tier)
        
        if not tier_config or tier_config.get("direct"):
            return None # No proxy
            
        server = f"http://{tier_config['host']}:{tier_config['port']}"
        proxy_dict = {"server": server}
        
        if tier_config.get("username") and tier_config.get("password"):
            username = tier_config["username"]
            password = tier_config["password"]
            
            # Check if target URL belongs to Japanese domain (.jp or JAL)
            is_japan_target = False
            is_india_target = False
            if target_url:
                from urllib.parse import urlparse
                try:
                    parsed_url = urlparse(target_url)
                    hostname = parsed_url.hostname or ""
                    if hostname.endswith(".jp") or "jal.co.jp" in hostname.lower():
                        is_japan_target = True
                    if hostname.endswith(".in") or any(keyword in hostname.lower() for keyword in ["meesho", "dinamalar", "flipkart", "ajio"]):
                        is_india_target = True
                except:
                    pass

            # REASON: Force fresh IP session for residential proxies (using password for better compatibility)
            if session_id:
                if "evomi" in tier_config.get("host", ""):
                    if "_session-" not in password:
                        password = f"{password}_session-{session_id}"
                elif "brd.superproxy.io" in tier_config.get("host", ""):
                    if "-session-" not in username:
                        username = f"{username}-session-{session_id}"

            # Dynamic Country Routing based on target URL domain or user geo
            if geo and geo.lower() != "default":
                geo_upper = geo.upper()
                geo_lower = geo.lower()
                if "evomi" in tier_config.get("host", ""):
                    if f"_country-{geo_lower}" not in password.lower():
                        password = f"{password}_country-{geo_upper}"
                elif "brd.superproxy.io" in tier_config.get("host", ""):
                    if f"-country-{geo_lower}" not in username.lower():
                        username = f"{username}-country-{geo_lower}"
            elif is_japan_target:
                if "evomi" in tier_config.get("host", ""):
                    if "_country-jp" not in password.lower():
                        password = f"{password}_country-JP"
                elif "brd.superproxy.io" in tier_config.get("host", ""):
                    if "-country-jp" not in username.lower():
                        username = f"{username}-country-jp"
            elif is_india_target:
                if "evomi" in tier_config.get("host", ""):
                    if "_country-in" not in password.lower():
                        password = f"{password}_country-IN"
                elif "brd.superproxy.io" in tier_config.get("host", ""):
                    if "-country-in" not in username.lower():
                        username = f"{username}-country-in"
            else:
                # Fallback to default configured GEOs
                if tier_config.get("geo", "").lower() == "india":
                    if "_country-in" not in password.lower():
                        password = f"{password}_country-IN"
            
            proxy_dict["username"] = username
            proxy_dict["password"] = password
            
        logger.debug(f"Using proxy tier {resolved_tier}: {tier_config['name']} (Session: {session_id})")
        return proxy_dict

    def get_proxy(self, tier: Union[int, str] = 1, target_url: Optional[str] = None, geo: Optional[str] = None) -> Optional[str]:
        """Returns a string proxy URL."""
        resolved_tier = self._resolve_tier(tier)
        tier_config = self.tiers.get(resolved_tier)
        
        if not tier_config or tier_config.get("direct"):
            return None
            
        is_japan_target = False
        is_india_target = False
        if target_url:
            from urllib.parse import urlparse
            try:
                parsed_url = urlparse(target_url)
                hostname = parsed_url.hostname or ""
                if hostname.endswith(".jp") or "jal.co.jp" in hostname.lower():
                    is_japan_target = True
                if hostname.endswith(".in") or any(keyword in hostname.lower() for keyword in ["meesho", "dinamalar", "flipkart", "ajio"]):
                    is_india_target = True
            except:
                pass

        auth = ""
        if tier_config.get("username") and tier_config.get("password"):
            username = tier_config["username"]
            password = tier_config["password"]
            
            # Dynamic Country Routing based on target URL domain or user geo
            if geo and geo.lower() != "default":
                geo_upper = geo.upper()
                geo_lower = geo.lower()
                if "evomi" in tier_config.get("host", ""):
                    if f"_country-{geo_lower}" not in password.lower():
                        password = f"{password}_country-{geo_upper}"
                elif "brd.superproxy.io" in tier_config.get("host", ""):
                    if f"-country-{geo_lower}" not in username.lower():
                        username = f"{username}-country-{geo_lower}"
            elif is_japan_target:
                if "evomi" in tier_config.get("host", ""):
                    if "_country-jp" not in password.lower():
                        password = f"{password}_country-JP"
                elif "brd.superproxy.io" in tier_config.get("host", ""):
                    if "-country-jp" not in username.lower():
                        username = f"{username}-country-jp"
            elif is_india_target:
                if "evomi" in tier_config.get("host", ""):
                    if "_country-in" not in password.lower():
                        password = f"{password}_country-IN"
                elif "brd.superproxy.io" in tier_config.get("host", ""):
                    if "-country-in" not in username.lower():
                        username = f"{username}-country-in"
            else:
                if tier_config.get("geo", "").lower() == "india":
                    if "_country-in" not in password.lower():
                        password = f"{password}_country-IN"
            
            auth = f"{username}:{password}@"
            
        return f"http://{auth}{tier_config['host']}:{tier_config['port']}"

    def get_requests_proxies(self, proxy_type: Union[int, str] = "basic", target_url: Optional[str] = None, geo: Optional[str] = None) -> Optional[dict]:
        """Returns a dict suitable for requests proxies argument."""
        proxy_url = self.get_proxy(proxy_type, target_url=target_url, geo=geo)
        if not proxy_url:
            return None
        return {"http": proxy_url, "https": proxy_url}

