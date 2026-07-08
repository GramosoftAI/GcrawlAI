import os
import logging
import socket
import random
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse, urlunparse, unquote
import requests
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

# Ensure .env is loaded
BASE_DIR = Path(__file__).resolve().parent.parent.parent
dotenv_path = BASE_DIR / '.env'
load_dotenv(dotenv_path, override=True)

import datetime

def _get_isp_from_db(table_name: str, country: str) -> Optional[str]:
    if table_name not in ("nodemaven_isps", "evomi_isps"):
        return None
    
    # 1. Try pooled connection
    try:
        from api.core.database import get_pooled_connection
        conn_ctx = get_pooled_connection()
        with conn_ctx as conn:
            with conn.cursor() as cur:
                cur.execute(f"SELECT isp_code FROM {table_name} WHERE country_code = %s", (country.upper(),))
                row = cur.fetchone()
                return row[0] if row else None
    except Exception as e:
        logger.info(f"[ProxyManager] Pooled DB connection failed, trying direct connection: {e}")

    # 2. Fall back to direct psycopg2 connection
    try:
        import psycopg2
        conn = psycopg2.connect(
            host=os.getenv("POSTGRES_HOST", "localhost"),
            port=os.getenv("POSTGRES_PORT", "5432"),
            database=os.getenv("POSTGRES_DATABASE", "Dev_tamil"),
            user=os.getenv("POSTGRES_USER", "postgres"),
            password=os.getenv("POSTGRES_PASSWORD", "Ramkumar1+")
        )
        with conn:
            with conn.cursor() as cur:
                cur.execute(f"SELECT isp_code FROM {table_name} WHERE country_code = %s", (country.upper(),))
                row = cur.fetchone()
                return row[0] if row else None
    except Exception as ex:
        logger.error(f"[ProxyManager] Error reading {table_name} for country={country} (direct connection): {ex}")
        return None

def _save_isp_to_db(table_name: str, country: str, isp_code: str):
    if table_name not in ("nodemaven_isps", "evomi_isps"):
        return
        
    # 1. Try pooled connection
    try:
        from api.core.database import get_pooled_connection
        conn_ctx = get_pooled_connection()
        with conn_ctx as conn:
            with conn.cursor() as cur:
                cur.execute(f"""
                INSERT INTO {table_name} (country_code, isp_code, updated_at)
                VALUES (%s, %s, %s)
                ON CONFLICT (country_code) DO UPDATE
                SET isp_code = EXCLUDED.isp_code, updated_at = EXCLUDED.updated_at
                """, (country.upper(), isp_code, datetime.datetime.now()))
                conn.commit()
                return
    except Exception as e:
        logger.info(f"[ProxyManager] Pooled DB save failed, trying direct connection: {e}")

    # 2. Fall back to direct psycopg2 connection
    try:
        import psycopg2
        conn = psycopg2.connect(
            host=os.getenv("POSTGRES_HOST", "localhost"),
            port=os.getenv("POSTGRES_PORT", "5432"),
            database=os.getenv("POSTGRES_DATABASE", "Dev_tamil"),
            user=os.getenv("POSTGRES_USER", "postgres"),
            password=os.getenv("POSTGRES_PASSWORD", "Ramkumar1+")
        )
        with conn:
            with conn.cursor() as cur:
                cur.execute(f"""
                INSERT INTO {table_name} (country_code, isp_code, updated_at)
                VALUES (%s, %s, %s)
                ON CONFLICT (country_code) DO UPDATE
                SET isp_code = EXCLUDED.isp_code, updated_at = EXCLUDED.updated_at
                """, (country.upper(), isp_code, datetime.datetime.now()))
                conn.commit()
    except Exception as ex:
        logger.error(f"[ProxyManager] Error saving to {table_name} for country={country} (direct connection): {ex}")

_geoip_cache = {}

GENERIC_CCTLDS = {
    "co", "io", "ai", "tv", "me", "ly", "fm", "cc", "to",
    "la", "am", "ad", "mu", "sh", "gg", "gl", "im", "je",
    "as", "by",
}

def get_domain_geo(url_str: str) -> dict:
    domain = urlparse(url_str).netloc.split(":")[0].lower()

    if domain in ("localhost", "127.0.0.1", "::1"):
        return {"country": "", "region": "", "city": ""}

    if domain in _geoip_cache:
        return _geoip_cache[domain]

    geo = {"country": "", "region": "", "city": ""}

    parts = domain.split(".")
    has_tld_country = False
    if len(parts) >= 2:
        tld = parts[-1]
        tld_mapping = {"uk": "gb", "tech": "us"}
        
        if tld in tld_mapping:
            geo["country"] = tld_mapping[tld]
            has_tld_country = True
        elif len(tld) == 2 and tld not in GENERIC_CCTLDS:
            geo["country"] = tld
            has_tld_country = True

    if not has_tld_country:
        try:
            target_ip = socket.gethostbyname(domain)
            if target_ip:
                resp = requests.get(f"https://ipwho.is/{target_ip}", timeout=4.0)
                if resp.status_code == 200:
                    data = resp.json()
                    if data.get("success"):
                        geo["country"] = (data.get("country_code") or "").lower()
                        geo["region"]  = (data.get("region") or "").lower().replace(" ", "_")
                        geo["city"]    = (data.get("city") or "").lower().replace(" ", "_")
        except Exception as e:
            logger.warning(f"[GeoIP] Lookup failed for {domain}: {e}")

    _geoip_cache[domain] = geo
    logger.info(f"[GeoIP] {domain} -> country={geo['country']} region={geo['region']} city={geo['city']}")
    return geo

NODEMAVEN_HOST = os.getenv("NODEMAVEN_HOST", os.getenv("ATTEMPT_1_PROXY_HOST"))
NODEMAVEN_PORT = os.getenv("NODEMAVEN_PORT", os.getenv("ATTEMPT_1_PROXY_PORT"))
NODEMAVEN_BASE_USER = os.getenv("NODEMAVEN_BASE_USER")
tier1_user = os.getenv("ATTEMPT_1_PROXY_USER")
if tier1_user:
    if "-" in tier1_user:
        NODEMAVEN_BASE_USER = tier1_user.split("-")[0]
    else:
        NODEMAVEN_BASE_USER = tier1_user
NODEMAVEN_PASS = os.getenv("NODEMAVEN_PASS", os.getenv("ATTEMPT_1_PROXY_PASS"))

EVOMI_HOST = os.getenv("EVOMI_HOST", os.getenv("ATTEMPT_3_PROXY_HOST"))
EVOMI_PORT = os.getenv("EVOMI_PORT", os.getenv("ATTEMPT_3_PROXY_PORT"))
EVOMI_USER = os.getenv("EVOMI_USER", os.getenv("ATTEMPT_3_PROXY_USER"))
EVOMI_PASS = os.getenv("EVOMI_PASS", os.getenv("ATTEMPT_3_PROXY_PASS"))

EVOMI_PREMIUM_HOST = os.getenv("EVOMI_PREMIUM_HOST", os.getenv("ATTEMPT_2_PROXY_HOST"))
EVOMI_PREMIUM_PORT = os.getenv("EVOMI_PREMIUM_PORT", os.getenv("ATTEMPT_2_PROXY_PORT"))
EVOMI_PREMIUM_USER = os.getenv("EVOMI_PREMIUM_USER", os.getenv("ATTEMPT_2_PROXY_USER"))
EVOMI_PREMIUM_PASS = os.getenv("EVOMI_PREMIUM_PASS", os.getenv("ATTEMPT_2_PROXY_PASS"))

# Clean Evomi passwords to remove any hardcoded suffixes (like _isp- or _country- or _mode-)
EVOMI_PASS_CLEAN = EVOMI_PASS
if EVOMI_PASS and "_" in EVOMI_PASS:
    if any(ind in EVOMI_PASS for ind in ["_country-", "_isp-", "_session-", "_mode-"]):
        EVOMI_PASS_CLEAN = EVOMI_PASS.split("_")[0]

EVOMI_PREMIUM_PASS_CLEAN = EVOMI_PREMIUM_PASS
if EVOMI_PREMIUM_PASS and "_" in EVOMI_PREMIUM_PASS:
    if any(ind in EVOMI_PREMIUM_PASS for ind in ["_country-", "_isp-", "_session-", "_mode-"]):
        EVOMI_PREMIUM_PASS_CLEAN = EVOMI_PREMIUM_PASS.split("_")[0]

# Fast consumer ISP keywords to prioritize globally
PRIORITY_ISPS = [
    "jio", "airtel", "comcast", "charter", "att", "verizon", 
    "virgin", "bt", "telekom", "orange", "rogers", "telstra", 
    "bell", "shaw", "singtel", "optus", "starhub", "tmnet", "maxis"
]

def build_nodemaven_proxy(geo: dict, session_id: Optional[str] = None, isp_code: Optional[str] = None) -> str:
    parts = [NODEMAVEN_BASE_USER]
    if geo.get("country"):
        parts.append(f"country-{geo['country'].lower()}")
    
    if isp_code:
        parts.append(f"isp-{isp_code}")
        
    if session_id:
        parts.append(f"session-{session_id}")
    
    parts.append("filter-medium-speed-fast")

    username = "-".join(parts)
    proxy_url = f"http://{username}:{NODEMAVEN_PASS}@{NODEMAVEN_HOST}:{NODEMAVEN_PORT}"
    logger.info(f"[Nodemaven] username={username}")
    return proxy_url

def build_evomi_proxy(geo: dict, session_id: Optional[str] = None) -> str:
    country = geo.get("country")
    if country and country != "any":
        password = f"{EVOMI_PASS_CLEAN}_country-{country.upper()}"
    else:
        password = EVOMI_PASS_CLEAN
    if session_id:
        password = f"{password}_session-{session_id}"
    proxy_url = f"http://{EVOMI_USER}:{password}@{EVOMI_HOST}:{EVOMI_PORT}"
    logger.info(f"[Evomi Core] country={country.upper() if (country and country != 'any') else 'ANY'}")
    return proxy_url

def build_evomi_premium_proxy(geo: dict, session_id: Optional[str] = None, isp_code: Optional[str] = None) -> str:
    country = geo.get("country")
    if country and country != "any":
        if isp_code:
            password = f"{EVOMI_PREMIUM_PASS_CLEAN}_country-{country.upper()}_isp-{isp_code}"
        else:
            password = f"{EVOMI_PREMIUM_PASS_CLEAN}_country-{country.upper()}"
    else:
        password = EVOMI_PREMIUM_PASS_CLEAN
    
    # Append mode-speed for speed optimization
    password = f"{password}_mode-speed"
    
    if session_id:
        password = f"{password}_session-{session_id}"
    proxy_url = f"https://{EVOMI_PREMIUM_USER}:{password}@{EVOMI_PREMIUM_HOST}:{EVOMI_PREMIUM_PORT}"
    if isp_code:
        logger.info(f"[Evomi Premium] country={country.upper()} isp={isp_code}")
    else:
        logger.info(f"[Evomi Premium] country={country.upper() if (country and country != 'any') else 'ANY'}")
    return proxy_url

def parse_proxy_for_playwright(proxy_url: str) -> dict:
    if not proxy_url:
        return None

    normalized = proxy_url.strip()
    if "://" not in normalized:
        normalized = f"http://{normalized}"

    parsed = urlparse(normalized)

    if not parsed.username:
        return {"server": normalized}

    netloc = parsed.hostname or ""
    if parsed.port:
        netloc += f":{parsed.port}"

    server = urlunparse((parsed.scheme or "http", netloc, "", "", "", ""))
    result = {"server": server, "username": unquote(parsed.username)}
    if parsed.password:
        result["password"] = unquote(parsed.password)
    return result

class ProxyManager:
    """Refactored to natively support Nodemaven -> Evomi fallback logic with dynamic ISP targeting and caching."""
    # Shared class-level caches across all instances
    _nodemaven_isp_cache = {}
    _evomi_isp_cache = {}
    _evomi_settings_data = None

    def __init__(self, **kwargs):
        pass

    def _fetch_nodemaven_isp(self, country_code: str) -> Optional[str]:
        if not country_code:
            country_code = "US"
        country = country_code.lower()
        
        # 1. Try DB first
        db_isp = _get_isp_from_db("nodemaven_isps", country)
        if db_isp is not None:
            selected_isp = db_isp if db_isp != "" else None
            ProxyManager._nodemaven_isp_cache[country] = selected_isp
            return selected_isp
            
        # 2. Fallback to US if country not found in DB
        logger.info(f"[ProxyManager] Country={country.upper()} not found in DB nodemaven_isps. Falling back to US.")
        db_isp = _get_isp_from_db("nodemaven_isps", "US")
        if db_isp is not None:
            selected_isp = db_isp if db_isp != "" else None
            ProxyManager._nodemaven_isp_cache[country] = selected_isp
            return selected_isp

        if country in ProxyManager._nodemaven_isp_cache:
            return ProxyManager._nodemaven_isp_cache[country]

        api_key = os.getenv("NODEMAVEN_ISP_APIKEY")
        if not api_key:
            logger.warning("[ProxyManager] NODEMAVEN_ISP_APIKEY is not set in .env")
            return None

        # Fetch paginated lists from Nodemaven
        headers = {
            "Authorization": f"x-api-key {api_key}",
            "Content-Type": "application/json"
        }
        all_isps = []
        limit = 100
        offset = 0
        try:
            for _ in range(5):  # Fetch maximum of 500 ISPs (5 pages)
                params = {
                    "country__code": country,
                    "limit": limit,
                    "offset": offset
                }
                resp = requests.get(
                    "https://api.nodemaven.com/api/v2/base/locations/isps/",
                    params=params,
                    headers=headers,
                    timeout=3.0
                )
                if resp.status_code != 200:
                    logger.info(f"[ProxyManager] Nodemaven ISP API status {resp.status_code} for country={country}")
                    break
                data = resp.json()
                isps = data.get("isps", [])
                if not isps:
                    break
                all_isps.extend(isps)
                if len(isps) < limit:
                    break
                offset += limit
        except Exception as e:
            logger.info(f"[ProxyManager] Connection to Nodemaven ISP API timed out or failed for country={country} (falling back to default ISP): {e}")

        if not all_isps:
            ProxyManager._nodemaven_isp_cache[country] = None
            return None

        # Filter and prioritize by effective availability
        high_isps = [isp for isp in all_isps if isp.get("effective_availability") == "high"]
        medium_isps = [isp for isp in all_isps if isp.get("effective_availability") == "medium"]
        low_isps = [isp for isp in all_isps if isp.get("effective_availability") == "low"]

        # Sort and select according to PRIORITY_ISPS
        selected = None
        
        # 1. High availability with priority ISP keywords
        for prio in PRIORITY_ISPS:
            for isp in high_isps:
                code = isp.get("code", "")
                name = isp.get("name", "")
                if prio in code.lower() or prio in name.lower():
                    selected = code
                    break
            if selected:
                break
                
        # 2. Fall back to any high availability ISP
        if not selected and high_isps:
            selected = high_isps[0].get("code")
            
        # 3. Medium availability with priority ISP keywords
        if not selected:
            for prio in PRIORITY_ISPS:
                for isp in medium_isps:
                    code = isp.get("code", "")
                    name = isp.get("name", "")
                    if prio in code.lower() or prio in name.lower():
                        selected = code
                        break
                if selected:
                    break
                    
        # 4. Fall back to any medium availability ISP
        if not selected and medium_isps:
            selected = medium_isps[0].get("code")
            
        # 5. Low availability with priority ISP keywords
        if not selected:
            for prio in PRIORITY_ISPS:
                for isp in low_isps:
                    code = isp.get("code", "")
                    name = isp.get("name", "")
                    if prio in code.lower() or prio in name.lower():
                        selected = code
                        break
                if selected:
                    break
                    
        # 6. Fall back to any low availability ISP
        if not selected and low_isps:
            selected = low_isps[0].get("code")

        ProxyManager._nodemaven_isp_cache[country] = selected
        _save_isp_to_db("nodemaven_isps", country, selected or "")
        if selected:
            logger.info(f"[ProxyManager] Dynamic Nodemaven ISP selected for country={country}: {selected}")
        return selected

    def _fetch_evomi_isp(self, country_code: str) -> Optional[str]:
        if not country_code:
            country_code = "US"
        country = country_code.upper()
        
        # 1. Try DB first
        db_isp = _get_isp_from_db("evomi_isps", country)
        if db_isp is not None:
            selected_isp = db_isp if db_isp != "" else None
            ProxyManager._evomi_isp_cache[country] = selected_isp
            return selected_isp
            
        # 2. Fallback to US if country not found in DB
        logger.info(f"[ProxyManager] Country={country} not found in DB evomi_isps. Falling back to US.")
        db_isp = _get_isp_from_db("evomi_isps", "US")
        if db_isp is not None:
            selected_isp = db_isp if db_isp != "" else None
            ProxyManager._evomi_isp_cache[country] = selected_isp
            return selected_isp

        if country in ProxyManager._evomi_isp_cache:
            return ProxyManager._evomi_isp_cache[country]

        api_key = os.getenv("EVOMI_PREMIUM_ISP_APIKEY")
        if not api_key:
            logger.warning("[ProxyManager] EVOMI_PREMIUM_ISP_APIKEY is not set in .env")
            return None

        # Call settings globally if not already fetched
        if not ProxyManager._evomi_settings_data:
            headers = {"x-apikey": api_key}
            try:
                resp = requests.get("https://api.evomi.com/public/settings", headers=headers, timeout=3.0)
                if resp.status_code == 200:
                    ProxyManager._evomi_settings_data = resp.json()
                else:
                    logger.info(f"[ProxyManager] Evomi settings API status {resp.status_code}")
            except Exception as e:
                logger.info(f"[ProxyManager] Error calling Evomi settings API: {e}")

        if not ProxyManager._evomi_settings_data or "data" not in ProxyManager._evomi_settings_data:
            ProxyManager._evomi_isp_cache[country] = None
            return None

        # Extract Premium Residential (rp) ISPs
        isp_dict = ProxyManager._evomi_settings_data.get("data", {}).get("rp", {}).get("isp", {})
        if not isp_dict:
            ProxyManager._evomi_isp_cache[country] = None
            return None

        # Filter ISPs belonging to target country (uppercase)
        filtered_isps = {
            k: v for k, v in isp_dict.items()
            if country in [c.upper() for c in v.get("countries", [])]
        }

        if not filtered_isps:
            ProxyManager._evomi_isp_cache[country] = None
            return None

        # Match against prioritized speed ISPs
        selected = None
        for prio in PRIORITY_ISPS:
            for key, val in filtered_isps.items():
                if prio in key.lower() or prio in val.get("label", "").lower():
                    selected = key
                    break
            if selected:
                break

        # Fallback to first available ISP
        if not selected:
            selected = list(filtered_isps.keys())[0]

        ProxyManager._evomi_isp_cache[country] = selected
        _save_isp_to_db("evomi_isps", country, selected or "")
        if selected:
            logger.info(f"[ProxyManager] Dynamic Evomi ISP selected for country={country}: {selected}")
        return selected
        
    def get_requests_proxies(self, target_url: str, provider: str = "nodemaven", session_id: Optional[str] = None, use_high_speed: bool = True, proxy_geo: Optional[str] = None, is_search: bool = False) -> dict:
        if provider == "direct":
            return None
        if proxy_geo and proxy_geo.strip().lower() != "default":
            geo = {"country": proxy_geo.strip().lower(), "region": "", "city": ""}
        else:
            geo = get_domain_geo(target_url)
        if not session_id:
            session_id = "".join(random.choices("0123456789abcdef", k=8))
            
        target_country = geo.get("country", "").upper() if geo else ""
        
        if is_search:
            provider = "nodemaven"
            if target_country:
                in_nodemaven = _get_isp_from_db("nodemaven_isps", target_country) is not None
                if not in_nodemaven:
                    geo["country"] = "in"
            else:
                geo["country"] = "in"
        else:
            if target_country:
                in_nodemaven = _get_isp_from_db("nodemaven_isps", target_country) is not None
                in_evomi = _get_isp_from_db("evomi_isps", target_country) is not None
                
                if in_nodemaven:
                    pass
                elif in_evomi:
                    if provider == "nodemaven":
                        provider = "evomi_premium"
                else:
                    geo["country"] = "us"
            else:
                geo["country"] = "us"

        isp_code = None
        if use_high_speed and geo.get("country"):
            if provider == "nodemaven":
                isp_code = self._fetch_nodemaven_isp(geo["country"])
            elif provider == "evomi_premium":
                isp_code = self._fetch_evomi_isp(geo["country"])

        if provider == "evomi_premium":
            proxy_url = build_evomi_premium_proxy(geo, session_id, isp_code)
        elif provider == "evomi_core":
            proxy_url = build_evomi_proxy(geo, session_id)
        else:
            proxy_url = build_nodemaven_proxy(geo, session_id, isp_code)
        return {"http": proxy_url, "https": proxy_url}

    def get_playwright_proxy(self, target_url: str, provider: str = "nodemaven", session_id: Optional[str] = None, use_high_speed: bool = True, proxy_geo: Optional[str] = None, is_search: bool = False) -> dict:
        if provider == "direct":
            return None
        if proxy_geo and proxy_geo.strip().lower() != "default":
            geo = {"country": proxy_geo.strip().lower(), "region": "", "city": ""}
        else:
            geo = get_domain_geo(target_url)
        if not session_id:
            session_id = "".join(random.choices("0123456789abcdef", k=8))
            
        target_country = geo.get("country", "").upper() if geo else ""
        
        if is_search:
            provider = "nodemaven"
            if target_country:
                in_nodemaven = _get_isp_from_db("nodemaven_isps", target_country) is not None
                if not in_nodemaven:
                    geo["country"] = "in"
            else:
                geo["country"] = "in"
        else:
            if target_country:
                in_nodemaven = _get_isp_from_db("nodemaven_isps", target_country) is not None
                in_evomi = _get_isp_from_db("evomi_isps", target_country) is not None
                
                if in_nodemaven:
                    pass
                elif in_evomi:
                    if provider == "nodemaven":
                        provider = "evomi_premium"
                else:
                    geo["country"] = "us"
            else:
                geo["country"] = "us"

        isp_code = None
        if use_high_speed and geo.get("country"):
            if provider == "nodemaven":
                isp_code = self._fetch_nodemaven_isp(geo["country"])
            elif provider == "evomi_premium":
                isp_code = self._fetch_evomi_isp(geo["country"])

        if provider == "evomi_premium":
            proxy_url = build_evomi_premium_proxy(geo, session_id, isp_code)
        elif provider == "evomi_core":
            proxy_url = build_evomi_proxy(geo, session_id)
        else:
            proxy_url = build_nodemaven_proxy(geo, session_id, isp_code)
        return parse_proxy_for_playwright(proxy_url)
