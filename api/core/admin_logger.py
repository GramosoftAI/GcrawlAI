#!/usr/bin/env python3
"""
Admin Error Logger Utilities
"""
import logging
import re
import requests
import json
import traceback
from typing import Optional, List, Dict, Any
from concurrent.futures import ThreadPoolExecutor
from api.core.database import get_pooled_connection

logger = logging.getLogger(__name__)

def get_proxy_exit_ip(proxy_settings: dict) -> str:
    """
    Resolve exit IP of the proxy by querying fast IP APIs.
    Returns: provider_country_ip (e.g. Nodemaven_IN_103.45.8.89)
    """
    provider = proxy_settings.get("provider", "Unknown")
    server = proxy_settings.get("server", "")
    username = proxy_settings.get("username", "")
    password = proxy_settings.get("password", "")

    # Standardize provider name format
    provider_name = provider.replace(" ", "")
    if provider_name.lower() == "nodemaven":
        provider_name = "Nodemaven"
    elif provider_name.lower() == "thordata":
        provider_name = "Thordata"
    elif provider_name.lower() == "evomicore":
        provider_name = "Evomicore"


    # Extract country code from username or password
    country = "US"
    country_match = re.search(r"country-([a-zA-Z]{2})", f"{username} {password}", re.IGNORECASE)
    if country_match:
        country = country_match.group(1).upper()

    if not server:
        return f"{provider_name}_{country}_Unknown"

    # Strip scheme from server if present and preserve it (e.g. http vs https)
    from urllib.parse import urlparse
    parsed_server = urlparse(server)
    scheme = parsed_server.scheme if parsed_server.scheme else "http"
    host_port = parsed_server.netloc if parsed_server.netloc else server

    proxies = {
        "http": f"{scheme}://{username}:{password}@{host_port}",
        "https": f"{scheme}://{username}:{password}@{host_port}",
    }

    # Attempt 1: http://ip-api.com/json (Fast, no SSL handshake required)
    try:
        r = requests.get("http://ip-api.com/json", proxies=proxies, timeout=3.0)
        if r.status_code == 200:
            data = r.json()
            ip = data.get("query")
            if ip:
                return f"{provider_name}_{country}_{ip}"
    except Exception:
        pass

    # Attempt 2: https://api.ipify.org?format=json (SSL fallback)
    try:
        r = requests.get("https://api.ipify.org?format=json", proxies=proxies, timeout=3.0)
        if r.status_code == 200:
            data = r.json()
            ip = data.get("ip")
            if ip:
                return f"{provider_name}_{country}_{ip}"
    except Exception:
        pass

    # Fallback when resolution fails
    return f"{provider_name}_{country}_Rotated"


def resolve_proxy_ips_for_attempts(proxy_attempts: List[Dict[str, Any]]) -> str:
    """
    Resolve proxy IPs in parallel using a ThreadPoolExecutor
    """
    if not proxy_attempts:
        return "Unknown"
        
    resolved = []
    try:
        with ThreadPoolExecutor(max_workers=len(proxy_attempts)) as executor:
            futures = [executor.submit(get_proxy_exit_ip, attempt) for attempt in proxy_attempts]
            for future in futures:
                try:
                    res = future.result()
                    if res:
                        resolved.append(res)
                except Exception:
                    pass
    except Exception as e:
        logger.error(f"Error in parallel proxy exit IP resolution: {e}")
        
    if not resolved:
        return "Unknown"
    return ", ".join(resolved)


def log_admin_error(
    log_id: str,
    source_tool: str,
    target_domain: str,
    error_type: str,
    severity: str,
    error_details: str,
    request_params: Optional[Dict[str, Any]] = None,
    stack_trace: Optional[str] = None,
    proxy_ip: Optional[str] = None,
    user_id: Optional[str] = None
) -> None:
    """
    Inserts a row into the admin_error_logs table.
    """
    # Auto-classify severity if not provided or empty
    if not severity:
        severity = "Error"
        
    # Standardize user_id
    if user_id is None:
        user_id = "demo"
    else:
        user_id = str(user_id)
        
    # Standardize request_params as JSON string
    params_json = "{}"
    if request_params:
        try:
            params_json = json.dumps(request_params)
        except Exception:
            params_json = "{}"

    try:
        with get_pooled_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO admin_error_logs 
                    (log_id, source_tool, target_domain, error_type, severity, proxy_ip, error_details, request_params, stack_trace, user_id)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        log_id,
                        source_tool,
                        target_domain,
                        error_type,
                        severity,
                        proxy_ip,
                        error_details,
                        params_json,
                        stack_trace,
                        user_id
                    )
                )
            conn.commit()
        logger.info(f"✓ Recorded error log into admin_error_logs for {log_id} ({error_type})")
    except Exception as db_err:
        logger.error(f"Failed to write admin error log for {log_id}: {db_err}", exc_info=True)
