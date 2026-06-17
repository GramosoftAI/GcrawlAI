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
from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth
import platform
import threading

if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

from web_crawler.common.config import CrawlConfig
from web_crawler.common.artifact_store import upsert_crawl_artifact

logger = logging.getLogger(__name__)


_db_pool = None
_pool_lock = threading.Lock()

class PooledConnectionWrapper:
    def __init__(self, pool, conn):
        self._pool = pool
        self._conn = conn

    def __getattr__(self, name):
        return getattr(self._conn, name)

    def close(self):
        try:
            self._pool.putconn(self._conn)
        except Exception as e:
            logger.warning(f"Error returning connection to pool: {e}")

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

                def _substitute(data):
                    if isinstance(data, dict):
                        return {k: _substitute(v) for k, v in data.items()}
                    if isinstance(data, str):
                        def _rep(m):
                            return os.getenv(m.group(1), m.group(2) or "")
                        return re.sub(r'\$\{([^:}]+)(?::([^}]*))?\}', _rep, data)
                    return data

                with open(config_path, "r") as f:
                    cfg = _substitute(yaml.safe_load(f))

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






def _store_crawl_artifact(
    crawl_id: Optional[str],
    artifact_type: str,
    content,
    *,
    content_kind: str = "text",
    page_url: Optional[str] = None,
    title: Optional[str] = None,
) -> Optional[str]:
    """
    Helper to store a crawl artifact in the database via the common artifact store.
    Returns the artifact ref (artifact://UUID) or None on failure.
    """
    if not crawl_id or content is None:
        return None

    conn = None
    try:
        conn = _get_db_conn()
        artifact_ref = upsert_crawl_artifact(
            conn,
            crawl_id=crawl_id,
            page_url=page_url,
            artifact_type=artifact_type,
            content=content,
            content_kind=content_kind,
            title=title,
        )
        conn.commit()
        return artifact_ref
    except Exception as db_err:
        logger.warning(
            f"⚠ Could not persist crawl artifact '{artifact_type}' for {page_url or crawl_id}: {db_err}"
        )
        return None
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass


def _record_crawl_error(
    crawl_id: Optional[str],
    url: str,
    error_source: str,
    reason: str,
    blocked_message: Optional[str] = None,
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
    try:
        conn = _get_db_conn()
        cur = conn.cursor()
        
        # Look up user_id from crawl_jobs
        user_id = None
        cur.execute("SELECT user_id FROM crawl_jobs WHERE crawl_id = %s", (crawl_id,))
        row = cur.fetchone()
        if row:
            user_id = row[0]
            
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
        
        def _substitute(data):
            if isinstance(data, dict):
                return {k: _substitute(v) for k, v in data.items()}
            if isinstance(data, str):
                def _rep(m):
                    return os.getenv(m.group(1), m.group(2) or "")
                return re.sub(r'\$\{([^:}]+)(?::([^}]*))?\}', _rep, data)
            return data

        if not config_path.exists():
            logger.warning(f"Configuration file not found: {config_path}")
            return

        with open(config_path, "r") as f:
            cfg = _substitute(yaml.safe_load(f))
            
        smtp_cfg = cfg.get("email", {})
        admin_email = os.getenv("ADMIN_EMAIL")
        
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
        if not hasattr(self._local, 'playwright'):
            self._local.playwright = None
            self._local.chromium_browser = None
            self._local.chromium_browser_direct = None
            self._local.camoufox_browser = None
        return self._local

    def get_playwright(self):
        local = self._get_local_data()
        if not local.playwright:
            local.playwright = sync_playwright().start()
        return local.playwright

    def get_chromium(self, config, direct=False):
        local = self._get_local_data()
        p = self.get_playwright()
        
        target_browser = local.chromium_browser_direct if direct else local.chromium_browser
        
        # Check if browser is still connected
        is_connected = False
        if target_browser:
            try:
                is_connected = target_browser.is_connected()
            except:
                is_connected = False

        if not target_browser or not is_connected:
            with self._lock: # Thread-safe launch
                logger.info(f"🚀 Launching WARM Chromium instance (Thread {threading.get_ident()}, direct={direct})...")
                launch_args = {
                    "headless": config.headless,
                    "args": [
                        '--no-sandbox', '--disable-setuid-sandbox', '--disable-infobars',
                        '--ignore-certificate-errors', '--disable-blink-features=AutomationControlled',
                        '--disable-dev-shm-usage', '--disable-gpu',
                        '--no-first-run', '--no-default-browser-check', '--password-store=basic', '--use-mock-keychain',
                        '--disable-web-security',
                        '--disable-backgrounding-occluded-windows', '--disable-renderer-backgrounding',
                        '--disable-background-timer-throttling', '--disable-ipc-flooding-protection',
                        '--disable-http2'
                    ]
                }
                if not direct:
                    launch_args["proxy"] = {"server": "http://per-context"}
                    
                target_browser = p.chromium.launch(**launch_args)
                
                if direct:
                    local.chromium_browser_direct = target_browser
                else:
                    local.chromium_browser = target_browser
                    
        return target_browser

    def close_chromium(self, direct=False):
        local = self._get_local_data()
        with self._lock:
            target = local.chromium_browser_direct if direct else local.chromium_browser
            if target:
                try:
                    logger.info(f"Closing warm Chromium instance (Thread {threading.get_ident()}, direct={direct})...")
                    target.close()
                except Exception as e:
                    logger.debug(f"Failed to close chromium: {e}")
                if direct:
                    local.chromium_browser_direct = None
                else:
                    local.chromium_browser = None


    def get_camoufox(self, config):
        local = self._get_local_data()
        p = self.get_playwright()
        
        is_connected = False
        if local.camoufox_browser:
            try:
                is_connected = local.camoufox_browser.is_connected()
            except:
                is_connected = False

        if not local.camoufox_browser or not is_connected:
            with self._lock: # Thread-safe launch
                logger.info(f"🚀 Launching WARM Camoufox instance (Thread {threading.get_ident()})...")
                
                # Configure system CA certificate trust policy and trust Luminati proxy root certificates
                try:
                    from platformdirs import user_cache_dir
                    install_dir = Path(user_cache_dir("camoufox"))
                    dist_dir = install_dir / "distribution"
                    dist_dir.mkdir(parents=True, exist_ok=True)
                    
                    # 1. Write the Luminati CA certificate
                    luminati_cert_content = (
                        "-----BEGIN CERTIFICATE-----\n"
                        "MIIFozCCA4ugAwIBAgIJAPnnIqmvvTArMA0GCSqGSIb3DQEBBQUAMD8xCzAJBgNV\n"
                        "BAYTAklMMQswCQYDVQQIEwJJTDENMAsGA1UEChMESG9sYTEUMBIGA1UEAxMLbHVt\n"
                        "aW5hdGkuaW8wHhcNMTYwOTI3MTQyODM4WhcNMzYwOTE1MTQyODM4WjA/MQswCQYD\n"
                        "VQQGEwJJTDELMAkGA1UECBMCSUwxDTALBgNVBAoTBEhvbGExFDASBgNVBAMTC2x1\n"
                        "bWluYXRpLmlvMIICIjANBgkqhkiG9w0BAQEFAAOCAg8AMIICCgKCAgEAtiqw0DuX\n"
                        "g5g7BC+Cr7mZvgXB7CsJ10YFb2xwoDZlHHJ8G0KEMUeNiY9EjPR8ZIHlnjGJehsW\n"
                        "PUvJeSAoDnT+fh4udWyUJ3VSqDTyGpu4DpfLBwaaZP/fq45UeR0oLs3ZJd6joDss\n"
                        "AjJdQbdBPJj/57MjwbF+jddP6qm9XbCWjYzl1uxdMVjloetyRUgkhkh2ALp/VtK8\n"
                        "hUj/XgvD/Y1souKYs5DKayJTn+GM6MlSOUBQ0+b8yUbDb/9vjbHlX4pZ8gbgSEFf\n"
                        "xUV49Sxd6EhRXzFw4TERQVut0cgojmRmrgXXwc4kJi0Uvtc6tV/hJeH2yRS84Ehg\n"
                        "feY5dcJVc69ILYfGrNmwbFvf5aHZPWFG0kIcy9iMMk+3wSUaBP+FAYyd0i+PJTxy\n"
                        "5Jfmhs6BHowuEr0zgL+xge+/RCEbVUPvA6w9DWYbpqckZUh9sPga3JcHjaHGs6Cz\n"
                        "dnjEShgmlBm0DL6JMumLWFJrjztsm56Huuai0F5pwyrsyq8fbK6Sp18sq5/vH3Vy\n"
                        "t2XAj4EIFvpWHZjuocCe5/5vAbkSXjQ5HEIS+SyVhlFriCy5Mf3fTyMFqwm3tbZv\n"
                        "jEooumi0/9F2WvisUgheC1uatZ8M+Pzi+Kp3x2SSS992KWs0M35GEstiB09RkNHe\n"
                        "GItI6qxqY/Npw5u6lBE6Z28ISwvuet1a4vMCAwEAAaOBoTCBnjAdBgNVHQ4EFgQU\n"
                        "Wq7PsMnq2tuDhTV0oUW4jjzvLTcwbwYDVR0jBGgwZoAUWq7PsMnq2tuDhTV0oUW4\n"
                        "jjzvLTehQ6RBMD8xCzAJBgNVBAYTAklMMQswCQYDVQQIEwJJTDENMAsGA1UEChME\n"
                        "SG9sYTEUMBIGA1UEAxMLbHVtaW5hdGkuaW+CCQD55yKpr70wKzAMBgNVHRMEBTAD\n"
                        "AQH/MA0GCSqGSIb3DQEBBQUAA4ICAQA3oT4lrUErSqXjQtDUINo62KcJWs4kjEd8\n"
                        "qXZdl/HVim06nOG6DFZCSh8JngFi4MFmSzGlBGxe1pXaYArtekfLWmhwoVoJiiaA\n"
                        "DAAPItcZNlA9zIORyLZlrXlIuP5xzsb9PbnNWhd9xJHksHGoHDPHAW/KI/GJdjQv\n"
                        "uuCyObvv1IgGvfHbv4lXGCwQuU0OBGXv1kfZtAqUS+ei5zkK+nY0qc3L3Ce+Ow6h\n"
                        "/haDe0FDoT7zkwnEHu/ExCGSR3lNnyBAewlPVMzbJznuPMU3FFA3MHT7IcHxJWff\n"
                        "r8jOXo3qXWqd+T2oDO02KUR2ZVolI8FGx6yIKfLwWnj+eR2dfdMx0tUX4F6mRi4N\n"
                        "zGmhhIIHtViAMf59tBL7az26C8DGfX0p4oECpKtc86u5bYTbRZ1xrf6t/wFqqgB/\n"
                        "RVqn9IhSfXNZtxBn8G0odR8sPIiBxJKvkLMDKoAEeErwd0yqnr8FplskFuPn0FY5\n"
                        "N7n7dj5cHoSUtSAkM6bHCFY+XVtUoy6xisTAobajHvU3e2cDVKizC/ocUbHbTJgh\n"
                        "nevnzyTtKL2w820PDmI7plFN3wR3epd4kTAP5KT196Pjwjg+Dqgt2OnGAafKr+Qr\n"
                        "o2cdIF5MbULVkux4RKzpNKaoDtrnvC1jROM5s1R0Lb96dQcS/VwmyX22lKdbbY9F\n"
                        "ij5GZar9JA==\n"
                        "-----END CERTIFICATE-----\n"
                    )
                    luminati_cert_path = dist_dir / "luminati.crt"
                    with open(luminati_cert_path, "w") as cert_f:
                        cert_f.write(luminati_cert_content)
                    
                    policies = {
                        "Certificates": {
                            "Install": [
                                str(luminati_cert_path.resolve())
                            ],
                            "ImportEnterpriseRoots": True
                        }
                    }
                    
                    # If on Linux, also configure system CA certificate trust policy via p11-kit
                    if platform.system().lower() == "linux":
                        p11_paths = [
                            "/usr/lib/x86_64-linux-gnu/pkcs11/p11-kit-trust.so",
                            "/usr/lib64/pkcs11/p11-kit-trust.so",
                            "/usr/lib/pkcs11/p11-kit-trust.so",
                            "/usr/lib/i386-linux-gnu/pkcs11/p11-kit-trust.so",
                            "/usr/lib/aarch64-linux-gnu/pkcs11/p11-kit-trust.so",
                            "/usr/lib/arm-linux-gnueabihf/pkcs11/p11-kit-trust.so",
                        ]
                        active_p11_path = None
                        for p11_path in p11_paths:
                            if os.path.exists(p11_path):
                                active_p11_path = p11_path
                                break
                                
                        # Fallback: Dynamic lookup via shell find command
                        if not active_p11_path:
                            try:
                                import subprocess
                                find_res = subprocess.run(
                                    ["find", "/usr/lib", "-name", "p11-kit-trust.so"],
                                    capture_output=True, text=True, timeout=3
                                )
                                found_paths = [p.strip() for p in find_res.stdout.split("\n") if p.strip()]
                                if found_paths and os.path.exists(found_paths[0]):
                                    active_p11_path = found_paths[0]
                            except Exception:
                                pass
                        
                        if active_p11_path:
                            policies["SecurityDevices"] = {
                                "p11-kit-trust": active_p11_path
                            }
                            logger.info(f"✓ Configured Firefox system CA cert policy using PKCS11 module: {active_p11_path}")
                        else:
                            logger.warning("Could not find p11-kit-trust.so on Linux. Firefox system root certificate policy skipped.")
                    
                    policies_file = dist_dir / "policies.json"
                    policies_content = {"policies": policies}
                    with open(policies_file, "w") as f:
                        json.dump(policies_content, f, indent=2)
                    logger.info(f"✓ Configured Firefox custom CA cert trust policies successfully.")
                except Exception as policy_err:
                    logger.warning(f"Failed to auto-configure Camoufox CA trust policies: {policy_err}")

                from camoufox.sync_api import NewBrowser
                local.camoufox_browser = NewBrowser(
                    p,
                    headless=config.headless,
                    os="windows",
                    block_webrtc=True,
                    humanize=False,
                    firefox_user_prefs={
                        "security.cert_pinning.enforcement_level": 0,
                        "security.enterprise_roots.enabled": True,
                        "network.stricttransportsecurity.preloadlist": False,
                        "network.http.hsts.enabled": False,
                        "security.ssl.enable_ocsp_stapling": False,
                        "security.ssl.enable_ocsp_must_staple": False,
                        "security.OCSP.enabled": 0,
                        "security.ssl.errorReporting.enabled": False,
                        "security.tls.version.min": 1,
                        "network.trr.mode": 5,
                        "extensions.pocket.enabled": False,
                        "browser.safebrowsing.enabled": False,
                        "browser.safebrowsing.downloads.remote.enabled": False,
                        "toolkit.telemetry.enabled": False,
                        "toolkit.telemetry.unified": False,
                        "datareporting.healthreport.uploadEnabled": False,
                        "datareporting.policy.dataSubmissionEnabled": False,
                        "browser.cache.disk.enable": False,
                        "browser.cache.memory.enable": True,
                    }
                )
        return local.camoufox_browser

    def shutdown(self):
        local = self._get_local_data()
        try:
            if local.chromium_browser: local.chromium_browser.close()
            if local.chromium_browser_direct: local.chromium_browser_direct.close()
            if local.camoufox_browser: local.camoufox_browser.close()
            if local.playwright: local.playwright.stop()
        except: pass


browser_manager = BrowserManager()
