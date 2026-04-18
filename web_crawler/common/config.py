# web_crawler/config.py

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Union
from urllib.parse import urlparse
from dotenv import load_dotenv

# Ensure .env is loaded (especially for Celery workers)
load_dotenv(override=True)

@dataclass
class CrawlConfig:
    max_pages: int = 10
    max_workers: int = 8
    timezone: str = "Asia/Kolkata"

    headless: bool = True
    page_timeout: int = 30_000
    nav_timeout: int = 60_000

    use_stealth: bool = True
    simulate_human: bool = False
    use_custom_headers: bool = True
    bypass_cloudflare: bool = True

    output_dir: str = "crawl_output-api"
    camoufox_path: Optional[str] = r"C:\Users\ganes\AppData\Local\camoufox\camoufox\Cache\camoufox.exe"

    # Optional proxy URL or list of URLs for rotation
    # Example: "http://user:pass@host:port" or ["p1", "p2"]
    proxy: Optional[Union[str, list]] = None

    # Firecrawl-style BYOP env settings
    proxy_server: Optional[str] = None
    proxy_username: Optional[str] = None
    proxy_password: Optional[str] = None

    # New Firecrawl-like multi-tier proxy settings
    basic_proxies: Optional[Union[str, list]] = None
    stealth_proxies: Optional[Union[str, list]] = None
    enhanced_proxies: Optional[Union[str, list]] = None
    proxy_mode: str = "auto"  # "auto", "basic", "stealth", "enhanced"

    def __post_init__(self):
        self.proxy_server = self._clean_env(self.proxy_server or os.getenv("PROXY_SERVER"))
        self.proxy_username = self._clean_env(self.proxy_username or os.getenv("PROXY_USERNAME"))
        self.proxy_password = self._clean_env(self.proxy_password or os.getenv("PROXY_PASSWORD"))

        # Load from env if not explicitly provided
        if self.proxy is None:
            self.proxy = os.getenv("CRAWL_PROXY")
        
        if self.basic_proxies is None:
            self.basic_proxies = os.getenv("BASIC_PROXIES")
        
        if self.stealth_proxies is None:
            self.stealth_proxies = os.getenv("STEALTH_PROXIES")

        if self.enhanced_proxies is None:
            self.enhanced_proxies = os.getenv("ENHANCED_PROXIES")

        # Backward-compatible alias: if enhanced pool is not explicitly set,
        # reuse stealth pool.
        if self.enhanced_proxies is None:
            self.enhanced_proxies = self.stealth_proxies
        
        raw_proxy_mode = self.proxy_mode
        if raw_proxy_mode is None or str(raw_proxy_mode).strip().lower() == "auto":
            raw_proxy_mode = os.getenv("PROXY_MODE", raw_proxy_mode)
        self.proxy_mode = self._normalize_proxy_mode(raw_proxy_mode)

        # If legacy CRAWL_PROXY is not set, derive requests-compatible proxy from BYOP env.
        if self.proxy is None and self.proxy_server:
            self.proxy = self._compose_proxy_url(
                server=self.proxy_server,
                username=self.proxy_username,
                password=self.proxy_password,
            )
        
        self.rebuild_paths()

    @staticmethod
    def _clean_env(value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        trimmed = value.strip()
        return trimmed if trimmed else None

    @staticmethod
    def _compose_proxy_url(
        server: str,
        username: Optional[str] = None,
        password: Optional[str] = None,
    ) -> str:
        """
        Build a requests-compatible proxy URL from Firecrawl-style env vars.
        Accepts full URLs (with scheme) and host:port values.
        """
        server = server.strip()
        parsed = urlparse(server if "://" in server else f"http://{server}")

        scheme = parsed.scheme or "http"
        host = parsed.hostname or parsed.netloc
        port = f":{parsed.port}" if parsed.port else ""

        auth = ""
        if username and password:
            auth = f"{username}:{password}@"

        return f"{scheme}://{auth}{host}{port}"

    @staticmethod
    def _normalize_proxy_mode(value: Optional[str]) -> str:
        """
        Normalize proxy mode to supported values.
        Unknown values are treated as "auto" to preserve resiliency.
        """
        allowed = {"auto", "basic", "stealth", "enhanced"}
        mode = (value or "auto").strip().lower()
        return mode if mode in allowed else "auto"

    def get_playwright_proxy(self) -> Optional[dict]:
        """
        Return a Playwright-compatible proxy block from Firecrawl-style env vars.
        """
        if not self.proxy_server:
            return None

        proxy_config = {"server": self.proxy_server}
        if self.proxy_username and self.proxy_password:
            proxy_config["username"] = self.proxy_username
            proxy_config["password"] = self.proxy_password

        return proxy_config

    def rebuild_paths(self):
        """Rebuild all output paths (important when output_dir changes)"""
        base = Path(self.output_dir)
        self.html_dir = base / "html"
        self.md_dir = base / "markdown"
        self.screenshot_dir = base / "screenshots"
        self.links_file = base / "links.txt"
        self.json_file = base / "pages.json"
        self.summary_file = base / "summary.json"
        self.seo_dir = base / "seo"
