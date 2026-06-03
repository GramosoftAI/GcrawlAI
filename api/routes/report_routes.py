import os
import logging
from typing import List, Optional
from pydantic import BaseModel, field_validator
from fastapi import APIRouter, HTTPException
from api.core.database import get_pooled_connection
from api.core.config_setup import load_config
from api.services.email_service import EmailService

logger = logging.getLogger(__name__)

router = APIRouter()

class ReportIssueRequest(BaseModel):
    url_affected: str
    issue_related_to: List[str]
    explanation: str
    email: Optional[str] = None

    @field_validator("url_affected")
    @classmethod
    def url_must_not_be_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("url_affected must not be empty")
        return v

    @field_validator("issue_related_to")
    @classmethod
    def issues_must_not_be_empty(cls, v: List[str]) -> List[str]:
        if not v:
            raise ValueError("issue_related_to must contain at least one item")
        return [item.strip() for item in v if item.strip()]

    @field_validator("explanation")
    @classmethod
    def explanation_must_not_be_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("explanation must not be empty")
        return v

    @field_validator("email")
    @classmethod
    def email_must_be_valid(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        v = v.strip()
        if v and "@" not in v:
            raise ValueError("email must be a valid email address")
        return v or None


class ReportIssueResponse(BaseModel):
    status_code: int = 201
    status: str = "success"
    message: str
    report_id: Optional[int] = None
    email_sent: bool = False


@router.post("/report-issue", response_model=ReportIssueResponse, status_code=201, tags=["Report Issue"])
def report_issue(payload: ReportIssueRequest):
    """
    Submit an issue report.

    Stores the report in the `reported_issues` PostgreSQL table and
    sends an HTML notification email to the admin via the existing SMTP service.
    """
    try:
        report_id = None
        with get_pooled_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO reported_issues (url_affected, issue_related_to, explanation, email)
                VALUES (%s, %s, %s, %s)
                RETURNING id
                """,
                (
                    payload.url_affected,
                    payload.issue_related_to,
                    payload.explanation,
                    payload.email,
                )
            )
            row = cur.fetchone()
            report_id = row[0] if row else None
            conn.commit()
            cur.close()

        logger.info(f"Issue report #{report_id} stored in DB")

        config = load_config()
        smtp_config = config.get("email", {})

        admin_email = os.getenv("ADMIN_EMAIL") or smtp_config.get("from_email", "")

        email_sent = False
        if admin_email:
            try:
                email_service = EmailService(smtp_config)
                email_sent = email_service.send_report_issue_email(
                    to_email=admin_email,
                    url_affected=payload.url_affected,
                    issue_related_to=payload.issue_related_to,
                    explanation=payload.explanation,
                    report_id=report_id,
                )
            except Exception as email_err:
                logger.warning(f"Could not send admin email for report #{report_id}: {email_err}")
        else:
            logger.warning("ADMIN_EMAIL not configured; skipping admin notification email.")

        return ReportIssueResponse(
            status_code=201,
            status="success",
            message="Issue reported successfully. Thank you for your feedback!",
            report_id=report_id,
            email_sent=email_sent,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating issue report: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to submit issue report: {str(e)}")
