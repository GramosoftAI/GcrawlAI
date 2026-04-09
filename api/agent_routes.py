import logging
import uuid
from datetime import datetime
from typing import Any, Dict

import jsonschema
from fastapi import APIRouter, HTTPException

from agent.celery_tasks import run_agent_job
from agent.db import AgentRepository
from agent.models import AgentCancelResponse, AgentRequest, AgentStartResponse, AgentStatusResponse
from agent.settings import AgentSettings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/agent", tags=["Agent"])


@router.post("", response_model=AgentStartResponse)
def start_agent_job(payload: AgentRequest) -> AgentStartResponse:
    settings = AgentSettings()
    job_id = uuid.uuid4().hex

    if payload.strictConstrainToURLs and not payload.urls:
        raise HTTPException(status_code=400, detail="strictConstrainToURLs requires urls")

    schema_json = payload.schema
    if schema_json:
        try:
            jsonschema.Draft7Validator.check_schema(schema_json)
        except jsonschema.SchemaError as exc:
            raise HTTPException(status_code=400, detail=f"Invalid schema: {exc.message}") from exc

    model = payload.model or "spark-1-mini"
    max_credits = payload.maxCredits or settings.default_max_credits

    repo = AgentRepository()
    repo.create_job(
        {
            "job_id": job_id,
            "prompt": payload.prompt,
            "urls": payload.urls,
            "schema_json": schema_json,
            "strict_constrain": payload.strictConstrainToURLs,
            "model": model,
            "max_credits": max_credits,
            "status": "processing",
            "credits_used": 0,
            "created_at": datetime.utcnow(),
        }
    )

    run_agent_job.apply_async(kwargs={"job_id": job_id}, task_id=job_id)
    return AgentStartResponse(success=True, id=job_id)


@router.get("/{job_id}", response_model=AgentStatusResponse)
def get_agent_status(job_id: str) -> AgentStatusResponse:
    repo = AgentRepository()
    job = repo.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    data = job["result_json"] if job["status"] == "completed" else None
    return AgentStatusResponse(
        success=True,
        status=job["status"],
        data=data,
        creditsUsed=job.get("credits_used", 0),
        expiresAt=job.get("expires_at"),
        model=job.get("model"),
        error=job.get("error"),
    )


@router.delete("/{job_id}", response_model=AgentCancelResponse)
def cancel_agent_job(job_id: str) -> AgentCancelResponse:
    repo = AgentRepository()
    job = repo.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if job["status"] not in {"completed", "failed", "cancelled"}:
        repo.update_job(job_id, status="cancelled", error="Cancelled by user")
        try:
            run_agent_job.AsyncResult(job_id).revoke(terminate=True)
        except Exception as exc:
            logger.warning(f"Failed to revoke task {job_id}: {exc}")

    return AgentCancelResponse(success=True)
