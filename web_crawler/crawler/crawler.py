"""
Main entry point for web crawler
"""

import uuid
import logging
from pathlib import Path
from typing import Optional, Dict

from web_crawler.common.config import CrawlConfig
from web_crawler.crawler.web_crawler import WebCrawler

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def main(
    start_url: str,
    enable_md: bool = False,
    enable_html: bool = False,
    enable_ss: bool = False,
    enable_json: bool = False,
    enable_links: bool = True,
    enable_seo: bool = False,
    enable_images: bool = False,
    client_id: Optional[str] = None,
    user_id: Optional[int] = None,
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
    
    BASE_DIR = Path(__file__).resolve().parent.parent
    
    crawl_id = client_id if client_id else uuid.uuid4().hex
    crawl_dir = BASE_DIR / "crawl_output-api" / f"crawl_{crawl_id}"
    
    config.output_dir = str(crawl_dir)
    config.rebuild_paths()
    
    crawler = WebCrawler(config)
    
    summary = crawler.crawl(
        start_url=start_url,
        enable_md=enable_md,
        enable_html=enable_html,
        enable_ss=enable_ss,
        enable_json=enable_json,
        enable_links=enable_links,
        enable_seo=enable_seo,
        enable_images=enable_images,
        client_id=client_id,
        user_id=user_id,
        websocket_manager=websocket_manager,
        crawl_mode=crawl_mode
    )

    if crawl_mode == "single":
        if client_id:
            from web_crawler.common.redis_events import publish_event
            publish_event(
                crawl_id=client_id,
                payload={
                    "type": "crawl_completed",
                    "summary": summary,
                    "summary_file_path": summary.get("summary_file_path")
                }
            )
    elif crawl_mode == "links":
        if client_id:
            from web_crawler.common.redis_events import publish_event
            publish_event(
                crawl_id=client_id,
                payload={
                    "type": "crawl_completed",
                    "summary": summary,
                    "summary_file_path": summary.get("summary_file_path"),
                    "total_links_found": summary.get("total_links_found"),
                    "from_sitemap": summary.get("from_sitemap"),
                    "from_homepage": summary.get("from_homepage"),
                }
            )
    summary["crawl_id"] = crawl_id
    return summary


if __name__ == "__main__":
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