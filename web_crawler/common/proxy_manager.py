import os
import logging
import random
import re
import requests
from typing import List, Optional, Union, Dict, Any
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

class ProxyManager:
    """
    Handles proxy rotation based on Tiers (1-3).
    """

    def __init__(self, **kwargs):
        self.tiers = {}
        self._geo_cache = {}
        self._load_tiers_from_env()

    def _load_tiers_from_env(self):
        """Loads TIER_1 to TIER_3 configurations from environment variables."""
        for tier in range(1, 4):
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

        logger.info(f"ProxyManager initialized with {len(self.tiers)} active proxy tiers.")

    def _resolve_tier(self, proxy_type_or_tier: Union[str, int]) -> int:
        if isinstance(proxy_type_or_tier, int):
            return proxy_type_or_tier
            
        ptype = str(proxy_type_or_tier).strip().lower()
        if ptype == "none":
            return 1
        elif ptype == "enhanced":
            return 1
        elif ptype == "bright_data" or ptype == "nodemaven":
            return 2
        elif ptype == "basic":
            return 1
        elif ptype == "stealth":
            return 3
        elif ptype == "premium":
            return 2
        elif ptype == "auto":
            return 1 # Starting point for auto escalation (Tier 1)
            
        if ptype.isdigit():
            return int(ptype)
            
        return 1

    def _detect_geo(self, target_url: str) -> tuple:
        """Dynamically detect the country code, region, and city of the target URL."""
        if not target_url:
            return None, None, None
            
        try:
            parsed_url = urlparse(target_url)
            hostname = parsed_url.hostname or ""
            if not hostname:
                return None, None, None
                
            # Use cached result if available
            if hostname in self._geo_cache:
                return self._geo_cache[hostname]
                
            # Quick TLD and domain checks for obvious domains (saving external request time)
            hostname_lower = hostname.lower()
            if hostname_lower.endswith(".jp") or "jal.co.jp" in hostname_lower:
                res = ("JP", "tokyo", "tokyo")
                self._geo_cache[hostname] = res
                return res
            if hostname_lower.endswith(".in") or any(keyword in hostname_lower for keyword in ["meesho", "dinamalar", "flipkart", "ajio"]):
                res = ("IN", "tamil_nadu", "chennai")
                self._geo_cache[hostname] = res
                return res
            if hostname_lower.endswith(".us"):
                res = ("US", "california", "mountain_view")
                self._geo_cache[hostname] = res
                return res
            if hostname_lower.endswith(".uk") or hostname_lower.endswith(".co.uk"):
                res = ("GB", "england", "london")
                self._geo_cache[hostname] = res
                return res
            if hostname_lower.endswith(".de"):
                res = ("DE", "berlin", "berlin")
                self._geo_cache[hostname] = res
                return res
            if hostname_lower.endswith(".fr"):
                res = ("FR", "ile-de-france", "paris")
                self._geo_cache[hostname] = res
                return res
            if hostname_lower.endswith(".ca"):
                res = ("CA", "ontario", "toronto")
                self._geo_cache[hostname] = res
                return res
            if hostname_lower.endswith(".au"):
                res = ("AU", "new_south_wales", "sydney")
                self._geo_cache[hostname] = res
                return res
                
            # Lookup via IP-API
            logger.info(f"Looking up geo location for domain: {hostname}")
            response = requests.get(f"http://ip-api.com/json/{hostname}?fields=status,countryCode,regionName,city", timeout=5)
            if response.status_code == 200:
                data = response.json()
                if data.get("status") == "success":
                    country = data.get("countryCode")
                    region = data.get("regionName")
                    city = data.get("city")
                    
                    # Normalize helper: lowercase and replace spaces/specials
                    def _normalize(val, spacer):
                        if not val:
                            return ""
                        val = re.sub(r'[^a-zA-Z0-9\s\.\-_]', '', val)
                        val = val.lower().strip()
                        return re.sub(r'\s+', spacer, val)
                        
                    region_norm = _normalize(region, "_")
                    city_norm = _normalize(city, "_")
                    
                    res = (country, region_norm, city_norm)
                    self._geo_cache[hostname] = res
                    return res
        except Exception as e:
            logger.warning(f"Failed to detect geo location for {target_url}: {e}")
            
        return None, None, None

    def _get_credentials(self, tier_config: dict, session_id: Optional[str] = None, target_url: Optional[str] = None, geo: Optional[str] = None) -> tuple:
        username = tier_config.get("username") or ""
        password = tier_config.get("password") or ""
        host = tier_config.get("host") or ""
        tier_geo = tier_config.get("geo") or ""
        
        resolved_tier = None
        for k, v in self.tiers.items():
            if v == tier_config:
                resolved_tier = k
                break

        if "evomi" in host:
            target_country, target_region, target_city = None, None, None
            if geo and geo.lower() != "default":
                target_country = geo.upper()
            elif (not geo or geo.lower() == "default") and resolved_tier in [1, 2]:
                target_country, target_region, target_city = self._detect_geo(target_url)
            
            suffixes = []
            if target_country:
                suffixes.append(f"country-{target_country.lower()}")
                if target_region:
                    reg = target_region.replace("_", ".")
                    suffixes.append(f"region-{reg}")
                if target_city:
                    cit = target_city.replace("_", ".")
                    suffixes.append(f"city-{cit}")
            else:
                if tier_geo.lower() == "india":
                    suffixes.append("country-in")
                    
            if session_id:
                suffixes.append(f"session-{session_id}")
                
            if suffixes:
                suffix_str = "_".join(suffixes)
                if suffix_str not in password:
                    password = f"{password}_{suffix_str}"
                    
        elif "nodemaven" in host:
            target_country, target_region, target_city = None, None, None
            if geo and geo.lower() != "default":
                target_country = geo.upper()
            elif (not geo or geo.lower() == "default") and resolved_tier in [1, 2]:
                target_country, target_region, target_city = self._detect_geo(target_url)
            
            geo_parts = []
            if target_country:
                geo_parts.append(f"country-{target_country.lower()}")
                if target_region:
                    geo_parts.append(f"region-{target_region.lower()}")
                if target_city:
                    geo_parts.append(f"city-{target_city.lower()}")
            else:
                geo_parts.append("country-any")
                
            if session_id:
                geo_parts.append(f"sid-{session_id}")
                
            geo_str = "-".join(geo_parts)
            if "-country-any" in username:
                username = username.replace("-country-any", f"-{geo_str}")
            else:
                username = f"{username}-{geo_str}"
                
        logger.info(f"[ProxyManager] Resolved proxy credentials for Tier {resolved_tier}: host={host}, username={username}")
        return username, password

    def get_playwright_proxy(self, tier: Union[int, str] = 1, session_id: Optional[str] = None, target_url: Optional[str] = None, geo: Optional[str] = None) -> Optional[dict]:
        """Returns a dict suitable for Playwright's proxy argument based on Tier."""
        resolved_tier = self._resolve_tier(tier)
        tier_config = self.tiers.get(resolved_tier)
        
        if not tier_config or tier_config.get("direct"):
            return None # No proxy
            
        server = f"http://{tier_config['host']}:{tier_config['port']}"
        proxy_dict = {"server": server}
        
        if tier_config.get("username") and tier_config.get("password"):
            username, password = self._get_credentials(tier_config, session_id, target_url, geo)
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

        auth = ""
        if tier_config.get("username") and tier_config.get("password"):
            username, password = self._get_credentials(tier_config, None, target_url, geo)
            auth = f"{username}:{password}@"
            
        return f"http://{auth}{tier_config['host']}:{tier_config['port']}"

    def get_requests_proxies(self, proxy_type: Union[int, str] = "basic", target_url: Optional[str] = None, geo: Optional[str] = None) -> Optional[dict]:
        """Returns a dict suitable for requests proxies argument."""
        proxy_url = self.get_proxy(proxy_type, target_url=target_url, geo=geo)
        if not proxy_url:
            return None
        return {"http": proxy_url, "https": proxy_url}
