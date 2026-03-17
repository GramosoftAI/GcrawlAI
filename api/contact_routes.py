#!/usr/bin/env python3

"""
Contact Us Routes

Handles the public 'Contact Us' form submission.
Validates all incoming fields, sends a professional HTML email notification
to jeevae@gramosoft.in, and returns a structured JSON response.

Fields collected:
    - name     (required)
    - email    (required, valid email)
    - mobile   (required, E.164-compatible format)
    - company  (required)
    - country  (optional)
    - message  (required, min 10 chars)
"""

import logging
import re
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, EmailStr, field_validator

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────
# Router
# ─────────────────────────────────────────────
router = APIRouter(prefix="/contact", tags=["Contact Us"])

# ─────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────
CONTACT_RECIPIENT = "ganesha@gramosoft.in"


# ─────────────────────────────────────────────
# Request / Response Models
# ─────────────────────────────────────────────

class ContactRequest(BaseModel):
    """Payload for the Contact Us form"""

    name: str
    email: EmailStr
    mobile: str
    company: str
    country: Optional[str] = None
    message: str

    # ── Validators ──────────────────────────

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        v = v.strip()
        if len(v) < 2:
            raise ValueError("Name must be at least 2 characters long.")
        if len(v) > 100:
            raise ValueError("Name must not exceed 100 characters.")
        return v

    @field_validator("mobile")
    @classmethod
    def validate_mobile(cls, v: str) -> str:
        v = v.strip()
        # Strip spaces/dashes for validation, allow +, digits, spaces, dashes, parens
        cleaned = re.sub(r"[\s\-\(\)]", "", v)
        if not re.match(r"^\+?\d{7,15}$", cleaned):
            raise ValueError(
                "Mobile number must be between 7 and 15 digits and may start with '+'."
            )
        return v

    @field_validator("company")
    @classmethod
    def validate_company(cls, v: str) -> str:
        v = v.strip()
        if len(v) < 2:
            raise ValueError("Company name must be at least 2 characters long.")
        if len(v) > 150:
            raise ValueError("Company name must not exceed 150 characters.")
        return v

    @field_validator("message")
    @classmethod
    def validate_message(cls, v: str) -> str:
        v = v.strip()
        if len(v) < 10:
            raise ValueError("Message must be at least 10 characters long.")
        if len(v) > 5000:
            raise ValueError("Message must not exceed 5000 characters.")
        return v

    @field_validator("country")
    @classmethod
    def validate_country(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            v = v.strip()
            if len(v) > 100:
                raise ValueError("Country name must not exceed 100 characters.")
            return v if v else None
        return v


class ContactResponse(BaseModel):
    """Response for Contact Us form submission"""

    status_code: int = 200
    status: str = "success"
    success: bool
    message: str


# ─────────────────────────────────────────────
# Endpoint
# ─────────────────────────────────────────────

@router.post(
    "",
    response_model=ContactResponse,
    summary="Submit Contact Us form",
    description=(
        "Accepts contact form data (name, email, mobile, company, country, message) "
        "and sends a professional notification email to the GcrawlAI team."
    ),
)
async def submit_contact_form(payload: ContactRequest):
    """
    POST /contact

    Submit the 'Contact Us' form. A professional HTML notification is sent to
    jeevae@gramosoft.in with all the enquiry details.

    Example:
    ```json
    {
        "name": "Ravi Kumar",
        "email": "ravi@acme.com",
        "mobile": "+91 98765 43210",
        "company": "Acme Corp",
        "country": "India",
        "message": "We would like to integrate GcrawlAI into our RAG pipeline."
    }
    ```
    """
    try:
        # Import the shared email service that is initialised on startup
        from api.email_service import EmailService
        from api.api import load_config

        config = load_config()
        email_config = config.get("email", {})

        email_service = EmailService(email_config)

        sent = email_service.send_contact_email(
            to_email=CONTACT_RECIPIENT,
            name=payload.name,
            email=payload.email,
            mobile=payload.mobile,
            company=payload.company,
            country=payload.country,
            message=payload.message,
        )

        if sent:
            logger.info(
                f"[ContactUs] Enquiry from '{payload.name}' <{payload.email}> "
                f"forwarded to {CONTACT_RECIPIENT}"
            )
            return ContactResponse(
                success=True,
                message="Thank you for reaching out! We have received your enquiry and will get back to you shortly.",
            )
        else:
            # Email service not configured or SMTP failed — still accept the submission
            logger.warning(
                f"[ContactUs] Email delivery failed for enquiry from '{payload.name}' "
                f"<{payload.email}>. SMTP may not be configured."
            )
            return ContactResponse(
                success=True,
                message=(
                    "Your message has been received. "
                    "We will get back to you as soon as possible."
                ),
            )

    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"[ContactUs] Unexpected error: {exc}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail="An unexpected error occurred while processing your request. Please try again later.",
        )