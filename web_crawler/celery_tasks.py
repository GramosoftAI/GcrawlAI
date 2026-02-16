"""
Celery tasks for distributed web crawling
"""

import json
import logging
from typing import Dict, Optional
from pathlib import Path

from web_crawler.celery_config import celery_app
from web_crawler.config import CrawlConfig
from web_crawler.crawler import main as crawl_main
import redis
import os

logger = logging.getLogger(__name__)


redis_client = redis.Redis.from_url(
    os.getenv("REDIS_URL", "redis://localhost:6379/0"),
    decode_responses=True
)


@celery_app.task(
    name='celery_tasks.crawl_website',
    bind=True,
    max_retries=3,
    default_retry_delay=60,  # Retry after 60 seconds
    time_limit=3600,  # Kill task after 1 hour
    soft_time_limit=3300,  # Warning at 55 minutes
)
def crawl_website(
    self,
    start_url: str,
    config_dict: Dict,
    enable_md: bool = True,
    enable_html: bool = True,
    enable_ss: bool = False,
    enable_json: bool = False,
    enable_links: bool = True,
    crawl_mode: str = "all",
) -> Dict:
    """
    Celery task to crawl a website
    
    Args:
        self: Task instance (bind=True)
        start_url: URL to start crawling
        config_dict: Configuration as dictionary
        Other args: Output options
    
    Returns:
        Dictionary with crawl summary and results
    """
    task_id = self.request.id
    logger.info(f"Starting crawl task {task_id} for {start_url}")
    
    try:
        # Update task state
        self.update_state(
            state='PROGRESS',
            meta={
                'status': 'Starting crawl',
                'url': start_url,
                'progress': 0
            }
        )
        
        # Reconstruct config from dict
        config = CrawlConfig(**config_dict)
        
        # Add task_id to output directory for tracking
        config.output_dir = f"{config.output_dir}_{task_id}"
        
        # Run the crawler
        summary = crawl_main(
            start_url=start_url,
            enable_md=enable_md,
            enable_html=enable_html,
            enable_ss=enable_ss,
            enable_json=enable_json,
            enable_links=True,
            client_id=task_id,  # Use task_id as client_id
            websocket_manager=None,  # No WebSocket in Celery
            crawl_mode=crawl_mode,
            config=config
        )

        from web_crawler.redis_events import publish_event

        publish_event(
            crawl_id=task_id,
            payload={
                "type": "crawl_completed",
                "summary": summary
            }
        )
        
        # Add task metadata
        summary['task_id'] = task_id
        summary['status'] = 'completed'
        
        logger.info(f"Completed crawl task {task_id}")
        
        return summary
        
    except Exception as exc:
        logger.error(f"Error in crawl task {task_id}: {exc}")
        
        # Retry with exponential backoff
        try:
            raise self.retry(exc=exc, countdown=2 ** self.request.retries)
        except self.MaxRetriesExceededError:
            return {
                'task_id': task_id,
                'status': 'failed',
                'error': str(exc),
                'start_url': start_url
            }


@celery_app.task(
    name='celery_tasks.crawl_single_page',
    bind=True,
    max_retries=2,
    time_limit=300,  # 5 minutes max
)
def crawl_single_page(self, url: str, config_dict: Dict) -> Dict:
    """
    Celery task to crawl a single page (faster, for single-page mode)
    """
    return crawl_website(
        self,
        start_url=url,
        config_dict=config_dict,
        crawl_mode="single",
        enable_md=True,
        enable_html=False,
        enable_ss=False,
        enable_json=True,
        enable_links=True
    )


@celery_app.task(name='celery_tasks.cleanup_old_results')
def cleanup_old_results(days_old: int = 7):
    """
    Periodic task to cleanup old crawl results
    """
    import shutil
    from datetime import datetime, timedelta
    
    base_dir = Path(__file__).parent / "crawl_output-api"
    cutoff_date = datetime.now() - timedelta(days=days_old)
    
    deleted = 0
    if base_dir.exists():
        for crawl_dir in base_dir.iterdir():
            if crawl_dir.is_dir():
                mtime = datetime.fromtimestamp(crawl_dir.stat().st_mtime)
                if mtime < cutoff_date:
                    shutil.rmtree(crawl_dir)
                    deleted += 1
    
    logger.info(f"Cleaned up {deleted} old crawl directories")
    return {'deleted': deleted}