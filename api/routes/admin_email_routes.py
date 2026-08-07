#!/usr/bin/env python3
"""
Admin Email Management Routes
Provides CRUD endpoints for managing admin notification recipient emails in the database.
"""
import logging
from typing import List, Optional
from fastapi import APIRouter, HTTPException, Depends
from psycopg2.extras import RealDictCursor
from pydantic import BaseModel, field_validator

from api.core.database import get_db_connection
from api.routes.admin_users_routes import verify_admin_user
from api.models.payloads import StandardResponse

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/admin/emails", tags=["Admin Email Management"])

class AdminEmailRequest(BaseModel):
    email: str

    @field_validator("email")
    @classmethod
    def email_must_be_valid(cls, v: str) -> str:
        """Email must be valid."""
        v = v.strip().lower()
        if not v:
            raise ValueError("email must not be empty")
        if "@" not in v:
            raise ValueError("email must be a valid email address")
        return v

class AdminEmailResponse(BaseModel):
    id: int
    email: str
    created_at: str

class AdminEmailListResponse(BaseModel):
    success: bool
    data: List[AdminEmailResponse]


@router.get("", response_model=AdminEmailListResponse)
async def list_admin_emails(_: bool = Depends(verify_admin_user)):
    """
    List all configured admin email addresses.
    """
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("SELECT id, email, created_at FROM admin_emails ORDER BY id ASC")
        rows = cursor.fetchall()
        cursor.close()
        
        data = []
        for r in rows:
            data.append(AdminEmailResponse(
                id=r['id'],
                email=r['email'],
                created_at=r['created_at'].isoformat() if r['created_at'] else ""
            ))
            
        return AdminEmailListResponse(success=True, data=data)
    except Exception as e:
        logger.error(f"Error listing admin emails: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")
    finally:
        if conn:
            conn.close()


@router.post("", response_model=StandardResponse, status_code=201)
async def add_admin_email(payload: AdminEmailRequest, _: bool = Depends(verify_admin_user)):
    """
    Add a new admin email address.
    """
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Check if already exists
        cursor.execute("SELECT id FROM admin_emails WHERE email = %s", (payload.email,))
        if cursor.fetchone():
            cursor.close()
            raise HTTPException(status_code=400, detail=f"Email '{payload.email}' already exists.")
            
        cursor.execute(
            "INSERT INTO admin_emails (email) VALUES (%s) RETURNING id",
            (payload.email,)
        )
        conn.commit()
        cursor.close()
        return StandardResponse(success=True, message=f"Successfully added admin email: {payload.email}")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error adding admin email: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")
    finally:
        if conn:
            conn.close()


@router.put("/{email_id}", response_model=StandardResponse)
async def update_admin_email(email_id: int, payload: AdminEmailRequest, _: bool = Depends(verify_admin_user)):
    """
    Update an existing admin email address.
    """
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Check if the target email_id exists
        cursor.execute("SELECT id FROM admin_emails WHERE id = %s", (email_id,))
        if not cursor.fetchone():
            cursor.close()
            raise HTTPException(status_code=404, detail=f"Admin email ID {email_id} not found.")
            
        # Check if new email conflicts with another email ID
        cursor.execute("SELECT id FROM admin_emails WHERE email = %s AND id != %s", (payload.email, email_id))
        if cursor.fetchone():
            cursor.close()
            raise HTTPException(status_code=400, detail=f"Email '{payload.email}' is already in use by another record.")
            
        cursor.execute(
            "UPDATE admin_emails SET email = %s WHERE id = %s",
            (payload.email, email_id)
        )
        conn.commit()
        cursor.close()
        return StandardResponse(success=True, message=f"Successfully updated admin email ID {email_id} to '{payload.email}'")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating admin email: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")
    finally:
        if conn:
            conn.close()


@router.delete("/{email_id}", response_model=StandardResponse)
async def delete_admin_email(email_id: int, _: bool = Depends(verify_admin_user)):
    """
    Delete an admin email address.
    """
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Check if it exists
        cursor.execute("SELECT email FROM admin_emails WHERE id = %s", (email_id,))
        row = cursor.fetchone()
        if not row:
            cursor.close()
            raise HTTPException(status_code=404, detail=f"Admin email ID {email_id} not found.")
            
        email = row[0]
        cursor.execute("DELETE FROM admin_emails WHERE id = %s", (email_id,))
        conn.commit()
        cursor.close()
        return StandardResponse(success=True, message=f"Successfully deleted admin email: {email}")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting admin email: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")
    finally:
        if conn:
            conn.close()
