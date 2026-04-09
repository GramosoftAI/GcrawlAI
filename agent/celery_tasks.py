import logging

from web_crawler.celery_config import celery_app
from agent.db import AgentRepository
from agent.pipeline import AgentPipeline

logger = logging.getLogger(__name__)


@celery_app.task(name="agent_tasks.run_agent_job", bind=True)
def run_agent_job(self, job_id: str) -> None:
    repo = AgentRepository()
    job = repo.get_job(job_id)
    if not job:
        logger.error(f"Agent job {job_id} not found")
        return

    repo.update_job(job_id, status="processing")
    pipeline = AgentPipeline()
    pipeline.run(job_id)
