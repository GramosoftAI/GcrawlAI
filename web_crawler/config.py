# web_crawler/config.py

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

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

    def __post_init__(self):
        self.rebuild_paths()

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
