import os
import logging
from typing import List, Optional
from pydantic import BaseModel, field_validator
from fastapi import APIRouter, HTTPException, Header
from api.core.database import get_pooled_connection
from api.core.config_setup import load_config
from api.services.email_service import EmailService

logger = logging.getLogger(__name__)

router = APIRouter()

class ReportIssueRequest(BaseModel):
    url_affected: str
    issue_related_to: List[str]
    explanation: str
    email: str

    @field_validator("url_affected")
    @classmethod
    def url_must_not_be_empty(cls, v: str) -> str:
        """Url must not be empty."""
        v = v.strip()
        if not v:
            raise ValueError("url_affected must not be empty")
        return v

    @field_validator("issue_related_to")
    @classmethod
    def issues_must_not_be_empty(cls, v: List[str]) -> List[str]:
        """Issues must not be empty."""
        if not v:
            raise ValueError("issue_related_to must contain at least one item")
        return [item.strip() for item in v if item.strip()]

    @field_validator("explanation")
    @classmethod
    def explanation_must_not_be_empty(cls, v: str) -> str:
        """Explanation must not be empty."""
        v = v.strip()
        if not v:
            raise ValueError("explanation must not be empty")
        return v

    @field_validator("email")
    @classmethod
    def email_must_be_valid(cls, v: str) -> str:
        """Email must be valid."""
        v = v.strip()
        if not v:
            raise ValueError("email must not be empty")
        if "@" not in v:
            raise ValueError("email must be a valid email address")
        return v


class ReportIssueResponse(BaseModel):
    status_code: int = 201
    status: str = "success"
    message: str
    report_id: Optional[int] = None
    email_sent: bool = False


@router.post("/report-issue", response_model=ReportIssueResponse, status_code=201, tags=["Report Issue"])
def report_issue(
    payload: ReportIssueRequest,
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
    authorization: Optional[str] = Header(None, alias="Authorization"),
    recaptcha_token: Optional[str] = Header(None, alias="recaptcha-token")
):
    """
    Submit an issue report.

    Stores the report in the `reported_issues` PostgreSQL table and
    sends an HTML notification email to the admin via the existing SMTP service.
    """
    from api.core.security import validate_recaptcha_or_jwt

    user_id = None
    if x_api_key or authorization or recaptcha_token:
        try:
            val_user_id = validate_recaptcha_or_jwt(
                auth_header=authorization,
                recaptcha_header=recaptcha_token,
                api_key_header=x_api_key
            )
            user_id = "demo" if val_user_id == "demo" else str(val_user_id)
        except Exception as auth_err:
            logger.warning(f"Optional authentication for report issue failed: {auth_err}")

    try:
        report_id = None
        with get_pooled_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO reported_issues (url_affected, issue_related_to, explanation, email, user_id, status)
                    VALUES (%s, %s, %s, %s, %s, 'Pending')
                    RETURNING id
                    """,
                    (
                        payload.url_affected,
                        payload.issue_related_to,
                        payload.explanation,
                        payload.email,
                        user_id
                    )
                )
                row = cur.fetchone()
                report_id = row[0] if row else None
                conn.commit()

        logger.info(f"Issue report #{report_id} stored in DB")

        from api.core.database import get_admin_recipient_emails
        admin_email = get_admin_recipient_emails()
        config = load_config()
        smtp_config = config.get("email", {})

        email_sent = False
        if admin_email:
            admin_emails = [email.strip() for email in admin_email.split(",") if email.strip()]
            try:
                email_service = EmailService(smtp_config)
                for target_email in admin_emails:
                    try:
                        sent = email_service.send_report_issue_email(
                            to_email=target_email,
                            url_affected=payload.url_affected,
                            issue_related_to=payload.issue_related_to,
                            explanation=payload.explanation,
                            report_id=report_id,
                            user_id=user_id,
                        )
                        if sent:
                            email_sent = True
                    except Exception as email_err:
                        logger.warning(f"Could not send admin email for report #{report_id} to {target_email}: {email_err}")
            except Exception as service_err:
                logger.warning(f"Could not initialize EmailService for report #{report_id}: {service_err}")
        else:
            logger.warning("Admin emails not configured in database; skipping admin notification email.")

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
