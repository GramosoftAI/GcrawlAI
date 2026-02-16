"""
Main entry point for web crawler
"""

import uuid
import logging
from pathlib import Path
from typing import Optional, Dict

from web_crawler.config import CrawlConfig
from web_crawler.web_crawler import WebCrawler

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def main(
    start_url: str,
    enable_md: bool = True,
    enable_html: bool = False,
    enable_ss: bool = False,
    enable_json: bool = False,
    enable_links: bool = True,
    client_id: Optional[str] = None,
    websocket_manager = None,
    crawl_mode: str = "all",
    config: Optional[CrawlConfig] = None
) -> Dict:
    """Main entry point for the crawler"""
    
    # Use default config if not provided
    if config is None:
        config = CrawlConfig(
            max_pages=50,
            max_workers=4,
            headless=True,
            use_stealth=True
        )
    
    # Get base directory
    BASE_DIR = Path(__file__).resolve().parent
    
    # Create unique crawl ID and directory
    crawl_id = uuid.uuid4().hex
    crawl_dir = BASE_DIR / "crawl_output-api" / f"crawl_{crawl_id}"
    crawl_dir.mkdir(parents=True, exist_ok=True)
    
    # Update config with crawl-specific output directory
    config.output_dir = str(crawl_dir)
    config.rebuild_paths()
    
    # Create subdirectories
    (Path(config.output_dir) / "html").mkdir(parents=True, exist_ok=True)
    (Path(config.output_dir) / "screenshots").mkdir(parents=True, exist_ok=True)
    
    # Initialize and run crawler
    crawler = WebCrawler(config)
    
    summary = crawler.crawl(
        start_url=start_url,
        enable_md=enable_md,
        enable_html=enable_html,
        enable_ss=enable_ss,
        enable_json=enable_json,
        enable_links=enable_links,
        client_id=client_id,
        websocket_manager=websocket_manager,
        crawl_mode=crawl_mode
    )

    if crawl_mode == "single":
        summary["markdown_path"] = summary["markdown_file"]
    else:
        summary["markdown_path"] = str(crawl_dir)
    
    # Add crawl metadata to summary
    summary["crawl_id"] = crawl_id
    
    return summary


if __name__ == "__main__":
    # Example usage
    config = CrawlConfig(
        max_pages=50,
        max_workers=4,
        headless=True,
        use_stealth=True
    )
    
    main(
        start_url="https://www.batikair.com.my/",
        crawl_mode="all",
        config=config
    )