# web_crawler/config.py

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Union, List
from urllib.parse import urlparse
from dotenv import load_dotenv

# Ensure .env is loaded (especially for Celery workers)
BASE_DIR = Path(__file__).resolve().parent.parent.parent
dotenv_path = BASE_DIR / '.env'
load_dotenv(dotenv_path, override=True)

@dataclass
class CrawlConfig:
    max_pages: int = 10
    max_workers: int = 8
    timezone: str = "Asia/Kolkata"

    headless: bool = True
    page_timeout: int = 30_000
    nav_timeout: int = 60_000

    use_stealth: bool = True
    simulate_human: bool = True
    use_custom_headers: bool = True
    bypass_cloudflare: bool = True

    output_dir: str = "crawl_output-api"

    proxy_geo: Optional[str] = None
    proxy_type_custom: Optional[str] = None
    js_render: bool = True
    render_timeout: int = 30000
    auto_scroll: bool = True
    auto_scroll_for_html: bool = False
    scroll_delay: int = 500
    max_scrolls: int = 10
    scroll_iteration_js: Optional[str] = None
    html_clean: bool = True
    html_remove_external_links: bool = False
    html_relative_to_absolute_links: bool = True
    html_remove_data_images: bool = False
    html_ignore_tags: List[str] = field(default_factory=list)
    screenshot_full_page: bool = True
    screenshot_format: str = "png"
    screenshot_quality: int = 90
    markdown_clean: bool = True

    # Optional proxy URL or list of URLs for rotation
    # Example: "http://user:pass@host:port" or ["p1", "p2"]
    proxy: Optional[Union[str, list]] = None

    # Firecrawl-style BYOP env settings
    proxy_server: Optional[str] = None
    proxy_username: Optional[str] = None
    proxy_password: Optional[str] = None

    raw_payload: Optional[dict] = None
    plugin_name: Optional[str] = None

    def __post_init__(self):
        # Allow overriding headless mode from environment variable
        crawl_headless_env = os.getenv("CRAWL_HEADLESS")
        if crawl_headless_env is not None:
            self.headless = crawl_headless_env.strip().lower() == "true"

        self.proxy_server = self._clean_env(self.proxy_server or os.getenv("PROXY_SERVER", os.getenv("EVOMI_PROXY_SERVER")))
        self.proxy_username = self._clean_env(self.proxy_username or os.getenv("PROXY_USERNAME", os.getenv("EVOMI_PROXY_USERNAME")))
        self.proxy_password = self._clean_env(self.proxy_password or os.getenv("PROXY_PASSWORD", os.getenv("EVOMI_PROXY_PASSWORD")))
        
        # Load custom region password fallback (like India or US) as provided by user
        self.proxy_password_india = self._clean_env(os.getenv("EVOMI_PROXY_PASSWORD_INDIA"))
        self.proxy_password_us = f"{self.proxy_password}_country-US" if self.proxy_password else None

        # Load from env if not explicitly provided
        if self.proxy is None:
            self.proxy = os.getenv("CRAWL_PROXY")

        # If legacy CRAWL_PROXY is not set, derive requests-compatible proxies from BYOP env.
        if self.proxy is None and self.proxy_server:
            base_url = self._compose_proxy_url(
                server=self.proxy_server,
                username=self.proxy_username,
                password=self.proxy_password,
            )
            self.proxy = base_url
        
        self.rebuild_paths()

    @staticmethod
    def _clean_env(value: Optional[str]) -> Optional[str]:
        """Clean env."""
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
        self.images_dir = base / "images"
