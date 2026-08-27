#!/usr/bin/env python3
import logging
import json
from typing import Dict, Any, List, Optional
from fastapi import APIRouter, HTTPException, Depends, Query

from api.core.database import get_db_connection
from api.models.gcrawl_payloads import (
    CookieSyncPayload, 
    CookieResponse, 
    CookieListResponse, 
    StandardResponse
)
from api.routes.gcrawl_routes.api_key_routes import verify_api_key

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/cookies", tags=["Cookies"])

@router.post("", response_model=StandardResponse)
async def sync_cookies(
    payload: CookieSyncPayload, 
    api_key_user: Dict = Depends(verify_api_key)
):
    """
    Sync (insert or update) cookies/local storage for a specific URL.
    Authenticated via X-API-Key header.
    """
    user_id = int(api_key_user['user_id'])
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Serialize the cookies_ls object to JSON string for Postgres JSONB insert
        cookies_json = json.dumps(payload.cookies_ls)
        
        upsert_query = """
            INSERT INTO user_cookies (user_id, url, cookies_ls, updated_at)
            VALUES (%s, %s, %s, CURRENT_TIMESTAMP)
            ON CONFLICT (user_id, url)
            DO UPDATE SET 
                cookies_ls = EXCLUDED.cookies_ls, 
                updated_at = CURRENT_TIMESTAMP
        """
        
        cursor.execute(upsert_query, (user_id, payload.url, cookies_json))
        conn.commit()
        cursor.close()
        
        return StandardResponse(
            success=True,
            message=f"Cookies successfully synced for {payload.url}"
        )
    except Exception as e:
        if conn:
            conn.rollback()
        logger.error(f"Error syncing cookies for user {user_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to sync cookies.")
    finally:
        if conn:
            conn.close()

@router.put("", response_model=StandardResponse)
async def update_cookies(
    payload: CookieSyncPayload, 
    api_key_user: Dict = Depends(verify_api_key)
):
    """
    Update cookies/local storage for a specific URL.
    Returns 404 if the cookie entry does not exist yet.
    Authenticated via X-API-Key header.
    """
    user_id = int(api_key_user['user_id'])
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cookies_json = json.dumps(payload.cookies_ls)
        
        update_query = """
            UPDATE user_cookies 
            SET cookies_ls = %s, updated_at = CURRENT_TIMESTAMP
            WHERE user_id = %s AND url = %s
        """
        
        cursor.execute(update_query, (cookies_json, user_id, payload.url))
        rows_updated = cursor.rowcount
        conn.commit()
        cursor.close()
        
        if rows_updated == 0:
            raise HTTPException(status_code=404, detail="No cookies entry found for this URL to update.")
            
        return StandardResponse(
            success=True,
            message=f"Cookies successfully updated for {payload.url}"
        )
    except HTTPException:
        raise
    except Exception as e:
        if conn:
            conn.rollback()
        logger.error(f"Error updating cookies for user {user_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to update cookies.")
    finally:
        if conn:
            conn.close()

@router.get("", response_model=CookieListResponse)
async def list_cookies(
    api_key_user: Dict = Depends(verify_api_key)
):
    """
    List all stored cookies for the authenticated user.
    Authenticated via X-API-Key header.
    """
    user_id = int(api_key_user['user_id'])
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        select_query = """
            SELECT id, user_id, url, cookies_ls, created_at, updated_at
            FROM user_cookies
            WHERE user_id = %s
            ORDER BY updated_at DESC
        """
        
        cursor.execute(select_query, (user_id,))
        rows = cursor.fetchall()
        cursor.close()
        
        cookies_list = []
        for row in rows:
            cookies_data = row[3]
            if isinstance(cookies_data, str):
                cookies_data = json.loads(cookies_data)
                
            cookies_list.append(CookieResponse(
                id=row[0],
                user_id=row[1],
                url=row[2],
                cookies_ls=cookies_data,
                created_at=row[4].isoformat() if hasattr(row[4], 'isoformat') else str(row[4]),
                updated_at=row[5].isoformat() if hasattr(row[5], 'isoformat') else str(row[5])
            ))
            
        return CookieListResponse(
            success=True,
            cookies=cookies_list
        )
    except Exception as e:
        logger.error(f"Error retrieving cookies list for user {user_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to fetch cookies.")
    finally:
        if conn:
            conn.close()

@router.get("/by-url", response_model=CookieResponse)
async def get_cookie_by_url(
    url: str = Query(..., description="The URL of the site to retrieve cookies for"),
    api_key_user: Dict = Depends(verify_api_key)
):
    """
    Retrieve stored cookies for a specific website URL.
    Authenticated via X-API-Key header.
    """
    user_id = int(api_key_user['user_id'])
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        select_query = """
            SELECT id, user_id, url, cookies_ls, created_at, updated_at
            FROM user_cookies
            WHERE user_id = %s AND url = %s
        """
        
        cursor.execute(select_query, (user_id, url))
        row = cursor.fetchone()
        cursor.close()
        
        if not row:
            raise HTTPException(status_code=404, detail="No cookies found for the specified URL.")
            
        cookies_data = row[3]
        if isinstance(cookies_data, str):
            cookies_data = json.loads(cookies_data)
            
        return CookieResponse(
            id=row[0],
            user_id=row[1],
            url=row[2],
            cookies_ls=cookies_data,
            created_at=row[4].isoformat() if hasattr(row[4], 'isoformat') else str(row[4]),
            updated_at=row[5].isoformat() if hasattr(row[5], 'isoformat') else str(row[5])
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error retrieving cookies by URL for user {user_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to retrieve cookies.")
    finally:
        if conn:
            conn.close()

@router.delete("/{cookie_id}", response_model=StandardResponse)
async def delete_cookie_by_id(
    cookie_id: int,
    api_key_user: Dict = Depends(verify_api_key)
):
    """
    Delete a specific cookie entry by its ID.
    Authenticated via X-API-Key header.
    """
    user_id = int(api_key_user['user_id'])
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        delete_query = """
            DELETE FROM user_cookies
            WHERE id = %s AND user_id = %s
        """
        
        cursor.execute(delete_query, (cookie_id, user_id))
        rows_deleted = cursor.rowcount
        conn.commit()
        cursor.close()
        
        if rows_deleted == 0:
            raise HTTPException(status_code=404, detail="Cookie entry not found or unauthorized.")
            
        return StandardResponse(
            success=True,
            message="Cookie entry successfully deleted."
        )
    except HTTPException:
        raise
    except Exception as e:
        if conn:
            conn.rollback()
        logger.error(f"Error deleting cookie ID {cookie_id} for user {user_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to delete cookie.")
    finally:
        if conn:
            conn.close()

@router.delete("", response_model=StandardResponse)
async def delete_cookies(
    url: Optional[str] = Query(None, description="Optional URL to delete cookies for. If omitted, deletes all user cookies."),
    api_key_user: Dict = Depends(verify_api_key)
):
    """
    Delete cookies. If a URL is provided, deletes cookies only for that URL.
    If no URL is provided, deletes all stored cookies for the authenticated user.
    Authenticated via X-API-Key header.
    """
    user_id = int(api_key_user['user_id'])
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        if url:
            delete_query = """
                DELETE FROM user_cookies
                WHERE user_id = %s AND url = %s
            """
            cursor.execute(delete_query, (user_id, url))
            message = f"Cookies for {url} successfully deleted."
        else:
            delete_query = """
                DELETE FROM user_cookies
                WHERE user_id = %s
            """
            cursor.execute(delete_query, (user_id,))
            message = "All stored cookies successfully deleted."
            
        conn.commit()
        cursor.close()
        
        return StandardResponse(
            success=True,
            message=message
        )
    except Exception as e:
        if conn:
            conn.rollback()
        logger.error(f"Error deleting cookies for user {user_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to delete cookies.")
    finally:
        if conn:
            conn.close()
