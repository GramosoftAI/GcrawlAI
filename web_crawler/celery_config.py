"""
Celery configuration for distributed crawling
"""

from celery import Celery
import os

# Redis connection
REDIS_URL = os.getenv('REDIS_URL', 'redis://localhost:6379/0')

# Initialize Celery app
celery_app = Celery(
    'web_crawler',
    broker=REDIS_URL,
    backend=REDIS_URL,
    include=['web_crawler.celery_tasks', 'agent.celery_tasks']  # Import tasks modules
)

# Celery configuration
celery_app.conf.update(
    # Task settings
    task_serializer='json',
    accept_content=['json'],
    result_serializer='json',
    timezone='Asia/Kolkata',
    enable_utc=True,
    
    # Performance settings
    task_acks_late=True,  # Acknowledge after task completion
    worker_prefetch_multiplier=1,  # Take one task at a time
    task_reject_on_worker_lost=True,
    
    # Result backend settings
    result_expires=3600,  # Results expire after 1 hour
    result_extended=True,  # Include start time and runtime metadata in results
    result_backend_transport_options={
        'master_name': 'mymaster'
    },
    
    # Worker settings
    worker_max_tasks_per_child=100,  # Restart worker after 100 tasks (prevent memory leaks)
    worker_disable_rate_limits=True,
    
    # Resilience — auto-retry broker connection on startup
    broker_connection_retry_on_startup=True,
    # Cancel long-running tasks if broker connection is lost
    worker_cancel_long_running_tasks_on_connection_loss=True,
    
    # Task routing (optional - for multiple queues)
    task_routes={
        'celery_tasks.crawl_website': {'queue': 'crawl_queue'},
        'celery_tasks.crawl_single_page': {'queue': 'page_queue'},
        'celery_tasks.crawl_links': {'queue': 'page_queue'},
        'agent_tasks.run_agent_job': {'queue': 'agent_queue'},
    },
    
    # Concurrency
    worker_concurrency=4,  # Number of concurrent tasks per worker
)

# Optional: Configure multiple queues for priority
celery_app.conf.task_default_queue = 'default'
celery_app.conf.task_queues = {
    'default': {
        'exchange': 'default',
        'routing_key': 'default',
    },
    'crawl_queue': {
        'exchange': 'crawl',
        'routing_key': 'crawl',
    },
    'page_queue': {
        'exchange': 'page',
        'routing_key': 'page',
    },
    'agent_queue': {
        'exchange': 'agent',
        'routing_key': 'agent',
    },
}


class CrawlConfig:
    def __init__(
        self,
        max_pages=50,
        max_workers=4,
        headless=True,
        use_stealth=True,
        output_dir="crawl_output-api"
    ):
        self.max_pages = max_pages
        self.max_workers = max_workers
        self.headless = headless
        self.use_stealth = use_stealth
        self.output_dir = output_dir

    def to_dict(self):
        return {
            "max_pages": self.max_pages,
            "max_workers": self.max_workers,
            "headless": self.headless,
            "use_stealth": self.use_stealth,
            "output_dir": self.output_dir,
        }
