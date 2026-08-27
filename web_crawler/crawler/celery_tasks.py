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
    default_retry_delay=60,
    time_limit=3600,
    soft_time_limit=3300,  
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

        from api.core.database import get_pooled_connection, update_activity_log_status, update_activity_log_time, get_ist_now
        from api.core.security import increment_used_requests
        from datetime import datetime
        try:
            with get_pooled_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "UPDATE crawl_jobs SET updated_at = %s WHERE crawl_id = %s",
                        (get_ist_now(), task_id)
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
    from api.core.database import get_pooled_connection, get_ist_now
    
    # 1. Cleanup Filesystem (legacy or local assets)
    base_dir = Path(__file__).parent.parent / "crawl_output-api"
    cutoff_date = (get_ist_now() - timedelta(days=days_old)).replace(tzinfo=None)
    
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
        
    # 3. Cleanup Grag Database Partitions (older than 2 days)
    dropped_grag_partitions = 0
    try:
        from grag.db_setup import drop_old_gsearch_partitions
        dropped_grag_partitions = drop_old_gsearch_partitions(days_old=2)
    except Exception as e:
        logger.error(f"Failed to drop old Grag partitions: {e}")
        
    # 4. Cleanup old activity_logs (older than 30 days)
    deleted_activity_logs = 0
    try:
        with get_pooled_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    "DELETE FROM activity_logs WHERE created_at < NOW() - INTERVAL '30 days'"
                )
                deleted_activity_logs = cursor.rowcount
            conn.commit()
        logger.info(f"✓ Cleaned up {deleted_activity_logs} old activity logs older than 30 days")
    except Exception as e:
        logger.error(f"Failed to cleanup old activity logs: {e}")
    
    logger.info(f"Cleaned up {deleted_dirs} old crawl directories, {dropped_partitions} DB partitions, {dropped_grag_partitions} Grag partitions, and {deleted_activity_logs} old activity logs")
    return {
        'deleted_dirs': deleted_dirs, 
        'dropped_partitions': dropped_partitions, 
        'dropped_grag_partitions': dropped_grag_partitions,
        'deleted_activity_logs': deleted_activity_logs
    }


# =========================================================
# GRAG BATCH LINKS SCRAPING WORKERS & TASKS
# =========================================================

@celery_app.task(
    name='celery_tasks.scrape_links_task',
    bind=True,
    time_limit=3600
)
def scrape_links_task(self, gsearch_id: str, urls: list):
    """Celery task to scrape a batch of URLs with max 5 concurrent browsers"""
    logger.info(f"Starting Grag Celery scrape task for gsearch_id: {gsearch_id}")
    run_scrape_links_worker(gsearch_id, urls)

def local_scrape_links_worker(gsearch_id: str, urls: list):
    """Local ThreadPool task to scrape a batch of URLs with max 5 concurrent browsers"""
    logger.info(f"Starting Grag Local ThreadPool scrape task for gsearch_id: {gsearch_id}")
    run_scrape_links_worker(gsearch_id, urls)

def run_scrape_links_worker(gsearch_id: str, urls: list):
    """Executes the scraping of URLs using ThreadPoolExecutor(max_workers=5)"""
    from concurrent.futures import ThreadPoolExecutor
    import threading
    from web_crawler.crawler.page_crawler import PageCrawler
    from web_crawler.common.config import CrawlConfig
    
    total_urls = len(urls)
    completed_count = 0
    lock = threading.Lock()
    
    def scrape_single(url, index):
        nonlocal completed_count
        logger.info(f"Grag scraping page [{index+1}/{total_urls}]: {url}")
        
        config = CrawlConfig(
            headless=True,
            use_stealth=True,
            js_render=False,
            auto_scroll=False,
            markdown_clean=False
        )
        config.raw_payload = {"url": url, "gsearch_id": gsearch_id}
        
        try:
            crawler = PageCrawler(config)
            result = crawler.crawl_page(
                url=url,
                count=index + 1,
                enable_md=True,
                enable_html=False,
                enable_ss=False,
                enable_seo=False,
                enable_images=False,
                enable_json=False,
                client_id=None,
                websocket_manager=None
            )
            
            if result and "error" not in result:
                md = result.get("markdown_content") or ""
                _upsert_gsearch_result(gsearch_id, url, md, status="success")
                _publish_grag_progress(gsearch_id, url, "success", index + 1, total_urls, markdown=md)
            else:
                err_msg = result.get("error") if result else "Failed to scrape page"
                _upsert_gsearch_result(gsearch_id, url, "", status="failed", error=err_msg)
                _publish_grag_progress(gsearch_id, url, "failed", index + 1, total_urls, error=err_msg)
        except Exception as ex:
            logger.error(f"Error scraping {url} in grag: {ex}")
            _upsert_gsearch_result(gsearch_id, url, "", status="failed", error=str(ex))
            _publish_grag_progress(gsearch_id, url, "failed", index + 1, total_urls, error=str(ex))
            
        with lock:
            completed_count += 1
            
    # Process up to 5 URLs concurrently
    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = [executor.submit(scrape_single, url, i) for i, url in enumerate(urls)]
        for fut in futures:
            try:
                fut.result()
            except Exception as e:
                logger.error(f"Thread execution failed: {e}")
                
    # Mark task as completed in DB
    _mark_gsearch_completed(gsearch_id)
    
    # Publish completion event
    _publish_grag_completed(gsearch_id, total_urls)
    logger.info(f"✅ Completed all scraping for gsearch_id: {gsearch_id}")

def _upsert_gsearch_result(gsearch_id: str, url: str, markdown: str, status: str = "success", error: str = None) -> None:
    from api.core.database import get_pooled_connection, get_ist_now
    from datetime import datetime
    import json
    
    try:
        with get_pooled_connection() as conn:
            with conn.cursor() as cursor:
                page_result = {
                    "url": url,
                    "status": status,
                    "markdown_content": markdown,
                    "error": error,
                    "scraped_at": get_ist_now().isoformat()
                }
                
                payload_str = json.dumps([page_result])
                
                cursor.execute(
                    "UPDATE gsearch_results SET json_content = json_content || %s::jsonb WHERE gsearch_id = %s",
                    (payload_str, gsearch_id)
                )
                
                if cursor.rowcount == 0:
                    cursor.execute(
                        "INSERT INTO gsearch_results (gsearch_id, json_content, status) VALUES (%s, %s::jsonb, 'processing')",
                        (gsearch_id, payload_str)
                    )
            conn.commit()
    except Exception as e:
        logger.error(f"Failed to upsert gsearch result for {gsearch_id}: {e}")

def _mark_gsearch_completed(gsearch_id: str) -> None:
    from api.core.database import get_pooled_connection
    try:
        with get_pooled_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    "UPDATE gsearch_results SET status = 'completed' WHERE gsearch_id = %s",
                    (gsearch_id,)
                )
            conn.commit()
            logger.info(f"Updated status to completed in DB for gsearch_id: {gsearch_id}")
    except Exception as e:
        logger.error(f"Failed to mark gsearch completed in DB: {e}")

def _publish_grag_progress(gsearch_id: str, url: str, status: str, page_no: int, total_pages: int, markdown: str = None, error: str = None):
    import redis
    import os
    import json
    try:
        r_client = redis.Redis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379/0"), decode_responses=True)
        payload = {
            "type": "page_processed",
            "url": url,
            "status": status,
            "page": page_no,
            "total_pages": total_pages,
            "markdown_content": markdown,
            "error": error
        }
        r_client.publish(f"grag:{gsearch_id}", json.dumps(payload))
    except Exception as e:
        logger.warning(f"Could not publish grag event to Redis: {e}")

def _publish_grag_completed(gsearch_id: str, total_pages: int):
    import redis
    import os
    import json
    try:
        r_client = redis.Redis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379/0"), decode_responses=True)
        payload = {
            "type": "gsearch_completed",
            "gsearch_id": gsearch_id,
            "status": "completed",
            "total_pages": total_pages
        }
        r_client.publish(f"grag:{gsearch_id}", json.dumps(payload))
    except Exception as e:
        logger.warning(f"Could not publish completion event to Redis: {e}")