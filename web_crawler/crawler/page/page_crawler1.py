"""
Core imports, DB helper actions and browser pool manager.
"""

import logging
import asyncio
import sys
import json
import os
import re
import random
import time
import yaml
from typing import Optional, Dict
from urllib.parse import urlparse
from pathlib import Path
import cloakbrowser

import platform
import threading

if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

from web_crawler.common.config import CrawlConfig


logger = logging.getLogger(__name__)


_db_pool = None
_pool_lock = threading.Lock()

class PooledConnectionWrapper:
    def __init__(self, pool, conn):
        """Init."""
        self._pool = pool
        self._conn = conn

    def __getattr__(self, name):
        return getattr(self._conn, name)

    def close(self):
        """Close."""
        try:
            self._pool.putconn(self._conn)
        except Exception as e:
            logger.warning(f"Error returning connection to pool: {e}")

def _substitute_config(data):
    """Substitute config."""
    if isinstance(data, dict):
        return {k: _substitute_config(v) for k, v in data.items()}
    if isinstance(data, str):
        def _rep(m):
            """Rep."""
            return os.getenv(m.group(1), m.group(2) or "")
        return re.sub(r'\$\{([^:}]+)(?::([^}]*))?\}', _rep, data)
    return data

def _get_db_conn():
    """
    Get a pooled PostgreSQL connection.
    Lazy-initializes a ThreadedConnectionPool once in a thread-safe manner.
    """
    global _db_pool
    if _db_pool is None:
        with _pool_lock:
            if _db_pool is None:
                import psycopg2
                from psycopg2.pool import ThreadedConnectionPool
                from dotenv import load_dotenv
                
                BASE_DIR = Path(__file__).resolve().parent.parent.parent.parent
                dotenv_path = BASE_DIR / '.env'
                load_dotenv(dotenv_path, override=True)

                config_path = BASE_DIR / "config.yaml"

                with open(config_path, "r") as f:
                    cfg = _substitute_config(yaml.safe_load(f))

                db = cfg.get("postgres", {})
                logger.info("🚀 Initializing crawler thread-safe database connection pool...")
                _db_pool = ThreadedConnectionPool(
                    minconn=2,
                    maxconn=20,
                    host=db.get("host", "localhost"),
                    port=db.get("port", 5432),
                    database=db.get("database", "crawlerdb"),
                    user=db.get("user", "postgres"),
                    password=db.get("password", ""),
                )
                
    # Fetch connection from the pool
    conn = _db_pool.getconn()
    return PooledConnectionWrapper(_db_pool, conn)







def _record_crawl_error(
    crawl_id: str,
    url: str,
    error_source: str,
    reason: str,
    blocked_message: str,
    proxy_attempts: Optional[list] = None,
    request_params: Optional[dict] = None
) -> None:
    """
    Insert a row into crawl_errors table.
    """
    if not crawl_id:
        return
    # 1. Trigger email notification first (to ensure it's sent even if DB insert fails)
    try:
        _send_crawl_error_notification(crawl_id, url, error_source, reason, blocked_message)
    except Exception as mail_err:
        logger.warning(f"⚠ Could not send crawl error notification: {mail_err}")

        # 2. Record to DB
    conn = None
    user_id = None
    crawl_mode = None
    try:
        conn = _get_db_conn()
        cur = conn.cursor()
        
        # Look up user_id and crawl_mode from crawl_jobs
        cur.execute("SELECT user_id, crawl_mode FROM crawl_jobs WHERE crawl_id = %s", (crawl_id,))
        row = cur.fetchone()
        if row:
            user_id = row[0]
            crawl_mode = row[1]
            
        cur.execute(
            """
            INSERT INTO crawl_errors (crawl_id, url, error_source, reason, blocked_message, user_id)
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (crawl_id, url, error_source, reason, blocked_message, user_id),
        )
        conn.commit()
        cur.close()
        logger.info(f"✓ Crawl error ({error_source}) recorded in DB for: {url}")
        
    except Exception as db_err:
        logger.warning(f"⚠ Could not record crawl error in DB for {url}: {db_err}")
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass

    # 3. Log to admin error logs
    try:
        from api.core.admin_logger import log_admin_error, resolve_proxy_ips_for_attempts
        
        # Determine target domain
        from urllib.parse import urlparse
        parsed = urlparse(url)
        domain = parsed.netloc if parsed.netloc else url
        
        # Classify error type and severity
        err_msg = (blocked_message or "").lower()
        if any(kw in err_msg for kw in ["captcha", "block", "cloudflare", "datadome", "forbidden", "403"]):
            error_type = "Anti-bot Block"
            severity = "Critical"
        elif any(kw in err_msg for kw in ["timeout", "navigation timeout", "page load timeout"]):
            error_type = "JS Timeout"
            severity = "Error"
        elif any(kw in err_msg for kw in ["rate limit", "429", "too many requests"]):
            error_type = "Rate Limit"
            severity = "Warning"
        elif any(kw in err_msg for kw in ["proxy", "tunnel", "proxy connection", "proxy auth"]):
            error_type = "Proxy Error"
            severity = "Critical"
        elif any(kw in err_msg for kw in ["ssl", "tls", "cert", "handshake"]):
            error_type = "TLS Handshake"
            severity = "Error"
        else:
            error_type = "Internal Error"
            severity = "Error"

        # Resolve proxy IPs for all attempts
        resolved_proxies_str = resolve_proxy_ips_for_attempts(proxy_attempts or [])

        # Build request parameters summary
        if not request_params:
            request_params = {
                "url": url,
                "error_source": error_source,
                "reason": reason
            }

        # Retrieve stack trace if any exception active, otherwise capture execution call stack
        import sys
        import traceback
        exc_type, exc_value, exc_traceback = sys.exc_info()
        if exc_traceback:
            stack_trace = "".join(traceback.format_exception(exc_type, exc_value, exc_traceback))
        else:
            stack_trace = "".join(traceback.format_stack())

        # Determine source_tool from crawl_mode
        source_tool = "Crawl"
        if crawl_mode == "single":
            source_tool = "Scrape"
        elif crawl_mode == "all":
            source_tool = "Crawl"
        elif crawl_mode == "links":
            source_tool = "Links"
        elif crawl_mode == "screenshot":
            source_tool = "Screenshot"

        log_admin_error(
            log_id=crawl_id,
            source_tool=source_tool,
            target_domain=domain,
            error_type=error_type,
            severity=severity,
            error_details=f"{reason} | {blocked_message}",
            request_params=request_params,
            stack_trace=stack_trace,
            proxy_ip=resolved_proxies_str,
            user_id=user_id
        )
    except Exception as log_err:
        logger.warning(f"⚠ Could not write to admin_error_logs: {log_err}")


def _send_crawl_error_notification(
    crawl_id: str,
    url: str,
    error_source: str,
    reason: str,
    blocked_message: Optional[str] = None,
) -> None:
    """
    Send an email notification for a crawl error.
    """
    try:
        from api.services.email_service import EmailService
        
        # Load config to get SMTP settings and admin email
        BASE_DIR = Path(__file__).resolve().parent.parent.parent.parent
        config_path = BASE_DIR / "config.yaml"
        
        if not config_path.exists():
            logger.warning(f"Configuration file not found: {config_path}")
            return

        with open(config_path, "r") as f:
            cfg = _substitute_config(yaml.safe_load(f))
            
        smtp_cfg = cfg.get("email", {})
        admin_email = os.getenv("ADMIN_EMAIL")
        
        if not admin_email:
            logger.info("Admin email is not set. Skipping crawl error email notification.")
            return

        if not smtp_cfg:
            logger.warning("Email configuration not found in config.yaml")
            return

        email_service = EmailService(smtp_cfg)
        email_service.send_crawl_error_email(
            to_email=admin_email,
            crawl_id=crawl_id,
            url=url,
            error_source=error_source,
            reason=reason,
            blocked_message=blocked_message
        )
    except Exception as e:
        logger.warning(f"⚠ Could not send crawl error email: {e}")


class BrowserManager:
    """Thread-safe Singleton to manage warm browser instances (Pooling)"""
    _instance = None
    _lock = threading.Lock()
    _local = threading.local()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(BrowserManager, cls).__new__(cls)
            return cls._instance

    def _get_local_data(self):
        """Return local data."""
        if not hasattr(self._local, 'clock_browser'):
            self._local.clock_browser = None
        return self._local

    def get_clock_browser(self, config, direct=False):
        """Return clock browser."""
        local = self._get_local_data()
        
        target_browser = local.clock_browser
        
        # Check if browser is still connected
        is_connected = False
        if target_browser:
            try:
                is_connected = target_browser.is_connected()
            except:
                is_connected = False

        if not target_browser or not is_connected:
            with self._lock: # Thread-safe launch
                logger.info(f"🚀 Launching WARM ClockBrowser instance (Thread {threading.get_ident()}, direct={direct})...")
                
                import random
                platform_choice = random.choices(["windows", "macos", "linux"], weights=[85, 10, 5])[0]
                seed = random.randint(100000, 9999999)
                concurrency = random.choice([4, 8, 12, 16])
                memory = random.choice([4, 8, 16])
                
                if platform_choice == "windows":
                    res = random.choice([(1920, 1080, 48), (1366, 768, 40), (1536, 864, 40)])
                elif platform_choice == "macos":
                    res = random.choice([(1440, 900, 95), (1680, 1050, 95), (2560, 1600, 95)])
                else:
                    res = random.choice([(1920, 1080, 0), (1366, 768, 0)])
                    
                width, height, taskbar = res
                local.width = width
                local.height = height
                
                fingerprint_args = [
                    f"--fingerprint={seed}",
                    f"--fingerprint-platform={platform_choice}",
                    f"--fingerprint-screen-width={width}",
                    f"--fingerprint-screen-height={height}",
                    f"--fingerprint-taskbar-height={taskbar}",
                    f"--fingerprint-hardware-concurrency={concurrency}",
                    f"--fingerprint-device-memory={memory}",
                ]
                
                launch_args = {
                    "headless": config.headless if config is not None else True,
                    "timezone": "America/Los_Angeles",
                    "locale": "en-US",
                    "args": fingerprint_args
                }
                # Match app.py: launch browser without proxy at the binary level
                    
                import asyncio
                old_loop = None
                try:
                    old_loop = asyncio.get_running_loop()
                    asyncio._set_running_loop(None)
                except RuntimeError:
                    pass

                try:
                    target_browser = cloakbrowser.launch(humanize=True, **launch_args)
                    target_browser._stealth_viewport = {"width": width, "height": height - taskbar}
                finally:
                    if old_loop is not None:
                        asyncio._set_running_loop(old_loop)
                
                local.clock_browser = target_browser
                    
        return target_browser

    def close_clock_browser(self, direct=False):
        """Close clock browser."""
        local = self._get_local_data()
        with self._lock:
            target = local.clock_browser
            if target:
                try:
                    logger.info(f"Closing warm ClockBrowser instance (Thread {threading.get_ident()}, direct={direct})...")
                    target.close()
                except Exception as e:
                    logger.debug(f"Failed to close clock_browser: {e}")
                local.clock_browser = None


    def shutdown(self):
        """Shutdown."""
        local = self._get_local_data()
        try:
            if local.clock_browser: local.clock_browser.close()
        except: pass


browser_manager = BrowserManager()
