"""
Celery tasks for distributed web crawling
"""

import json
import logging
from typing import Dict, Optional
from pathlib import Path

from web_crawler.crawler.celery_config import celery_app
from web_crawler.common.config import CrawlConfig
from web_crawler.crawler.crawler import main as crawl_main
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
    enable_md: bool = False,
    enable_html: bool = False,
    enable_ss: bool = False,
    enable_json: bool = False,
    enable_links: bool = True,
    enable_seo: bool = False,
    enable_images: bool = False,
    user_id: Optional[int] = None,
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
            enable_seo=enable_seo,
            enable_images=enable_images,
            client_id=task_id,  # Use task_id as client_id
            user_id=user_id,
            websocket_manager=None,  # No WebSocket in Celery
            crawl_mode=crawl_mode,
            config=config
        )

        from web_crawler.common.redis_events import publish_event

        publish_event(
            crawl_id=task_id,
            payload={
                "type": "crawl_completed",
                "summary": summary,
                "summary_file_path": summary.get("summary_file_path")
            }
        )
        
        # Add task metadata
        summary['task_id'] = task_id
        if summary.get('status') != 'failed':
            summary['status'] = 'completed'

        from api.core.database import get_pooled_connection, update_activity_log_status, update_activity_log_time
        from api.core.security import increment_used_requests
        from datetime import datetime
        try:
            with get_pooled_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "UPDATE crawl_jobs SET updated_at = %s WHERE crawl_id = %s",
                        (datetime.now(), task_id)
                    )
                conn.commit()

            # Billing: calculate charge and deduct using centralized rollover-aware function
            if user_id and user_id != "demo":
                if crawl_mode == "links":
                    links_found = summary.get("total_links_found", 1)
                    charge_amount = (links_found + 9) // 10
                elif crawl_mode == "screenshot":
                    charge_amount = 1
                else:
                    enabled_formats_count = sum(bool(x) for x in [enable_md, enable_html, enable_ss, enable_seo, enable_images])
                    if crawl_mode == "single":
                        charge_amount = enabled_formats_count or 1
                    else:
                        pages_crawled = summary.get("pages_crawled", 1)
                        charge_amount = pages_crawled * (enabled_formats_count or 1)

                increment_used_requests(user_id, amount=charge_amount)
            
            # Update activity log status and latency
            status = "FAILED" if summary.get("status") == "failed" else "COMPLETED"
            update_activity_log_status(task_id, status)
            if summary.get("time_taken"):
                update_activity_log_time(task_id, summary.get("time_taken"))
        except Exception as db_e:
            logger.error(f"Failed to update database records for task {task_id}: {db_e}")

        
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


@celery_app.task(name='celery_tasks.cleanup_old_results')
def cleanup_old_results(days_old: int = 7):
    """
    Periodic task to cleanup old crawl results from filesystem and drop old DB partitions.
    """
    import shutil
    from datetime import datetime, timedelta
    from api.core.database import get_pooled_connection
    
    # 1. Cleanup Filesystem (legacy or local assets)
    base_dir = Path(__file__).parent.parent / "crawl_output-api"
    cutoff_date = datetime.now() - timedelta(days=days_old)
    
    deleted_dirs = 0
    if base_dir.exists():
        for crawl_dir in base_dir.iterdir():
            if crawl_dir.is_dir():
                mtime = datetime.fromtimestamp(crawl_dir.stat().st_mtime)
                if mtime < cutoff_date:
                    shutil.rmtree(crawl_dir)
                    deleted_dirs += 1
                    
    # 2. Cleanup Database Partitions
    dropped_partitions = 0
    try:
        with get_pooled_connection() as conn:
            with conn.cursor() as cursor:
                # Get all partitions for job_results
                cursor.execute("""
                    SELECT child.relname
                    FROM pg_inherits
                    JOIN pg_class parent ON pg_inherits.inhparent = parent.oid
                    JOIN pg_class child ON pg_inherits.inhrelid = child.oid
                    WHERE parent.relname = 'job_results';
                """)
                partitions = cursor.fetchall()
                
                for (part_name,) in partitions:
                    # part_name format: job_results_YYYY_MM_DD
                    try:
                        date_str = part_name.replace("job_results_", "")
                        part_date = datetime.strptime(date_str, "%Y_%m_%d")
                        if part_date < cutoff_date:
                            cursor.execute(f"DROP TABLE IF EXISTS {part_name};")
                            dropped_partitions += 1
                    except ValueError:
                        pass
            conn.commit()
    except Exception as e:
        logger.error(f"Error dropping old partitions: {e}")
    
    logger.info(f"Cleaned up {deleted_dirs} old crawl directories and {dropped_partitions} DB partitions")
    return {'deleted_dirs': deleted_dirs, 'dropped_partitions': dropped_partitions}