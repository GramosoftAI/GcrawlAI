#!/usr/bin/env python3
import os
import logging
from fastapi import APIRouter, HTTPException, BackgroundTasks
from api.routes.api_key_routes import get_db_connection
from api.models.payloads import CustomRequestSubmitPayload, StandardResponse
from api.services.email_service import EmailService
from api.core.config_setup import load_config

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/custom-requests", tags=["Custom Requests"])

# Initialize EmailService
email_config = load_config().get('email', {})
email_service = EmailService(email_config)

def send_admin_notification_email(payload: CustomRequestSubmitPayload):
    admin_emails_str = os.getenv('ADMIN_EMAIL')
    if not admin_emails_str:
        logger.warning("ADMIN_EMAIL not set in env variables. Skipping notification email.")
        return

    admin_emails = [email.strip() for email in admin_emails_str.split(',')]
    
    subject = f"New Custom Scraping Request: {payload.request_type} from {payload.full_name}"
    
    html_content = f"""
    <h2>New Custom Request Received</h2>
    <p><strong>Name:</strong> {payload.full_name}</p>
    <p><strong>Email:</strong> {payload.work_email}</p>
    <p><strong>Company:</strong> {payload.company or 'N/A'}</p>
    <p><strong>Request Type:</strong> {payload.request_type}</p>
    <p><strong>Expected Volume:</strong> {payload.expected_volume}</p>
    <p><strong>Target Websites:</strong> {payload.target_websites}</p>
    <p><strong>Description:</strong></p>
    <blockquote style="background-color: #f9f9f9; padding: 10px; border-left: 4px solid #ccc;">
        {payload.description}
    </blockquote>
    <p>Log in to the Admin Panel to view and manage this request.</p>
    """
    
    for admin_email in admin_emails:
        if admin_email:
            try:
                email_service.send_email(
                    to_email=admin_email,
                    subject=subject,
                    html_content=html_content
                )
            except Exception as e:
                logger.error(f"Failed to send custom request notification to {admin_email}: {e}")

@router.post("", response_model=StandardResponse)
async def submit_custom_request(payload: CustomRequestSubmitPayload, background_tasks: BackgroundTasks):
    """
    Public endpoint to submit a custom scraping request.
    Stores the data in the database and triggers an email notification to admins.
    """
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        insert_query = """
            INSERT INTO custom_requests (
                full_name, work_email, company, expected_volume, 
                request_type, target_websites, description, status, created_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, 'New', CURRENT_TIMESTAMP)
        """
        
        cursor.execute(insert_query, (
            payload.full_name,
            payload.work_email,
            payload.company,
            payload.expected_volume,
            payload.request_type,
            payload.target_websites,
            payload.description
        ))
        
        conn.commit()
        cursor.close()
        
        # Dispatch email asynchronously
        background_tasks.add_task(send_admin_notification_email, payload)
        
        return StandardResponse(
            success=True,
            message="Your request has been submitted successfully."
        )
        
    except Exception as e:
        if conn:
            conn.rollback()
        logger.error(f"Error saving custom request: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="An error occurred while processing your request.")
    finally:
        if conn:
            conn.close()
