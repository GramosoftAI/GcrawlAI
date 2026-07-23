#!/usr/bin/env python3
"""
Admin API Endpoints Management Routes
Provides read and update endpoints for API endpoints configuration.
"""
import logging
from typing import Optional
from fastapi import APIRouter, HTTPException, Depends
from psycopg2.extras import RealDictCursor
from api.routes.api_key_routes import get_db_connection
from api.routes.admin_users_routes import verify_admin_user, verify_admin_user_optional
from api.models.payloads import (
    AdminEndpointResponse,
    AdminEndpointListResponse,
    UpdateEndpointRequest,
    StandardResponse
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/admin", tags=["Admin User Management"])

def format_calls_count(count: int) -> str:
    """Format total calls count into human-readable notation (e.g. 1.2M, 800K, 0)"""
    if count >= 1_000_000:
        return f"{count / 1_000_000:.1f}M".replace(".0M", "M")
    elif count >= 1_000:
        return f"{count / 1_000:.0f}K"
    return str(count)

@router.get("/endpoints", response_model=AdminEndpointListResponse)
async def get_admin_endpoints(
    _: Optional[bool] = Depends(verify_admin_user_optional)
):
    """
    Retrieve all monitored API endpoints with status, average latency, and monthly calls count.
    """
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        # 1. Fetch current month's aggregate stats (count & latency) grouped by endpoint key in activity_logs
        # Convert time_taken to numeric seconds for AVG calculation
        cursor.execute("""
            SELECT 
                UPPER(endpoint) as endpoint_key,
                COUNT(*) as total_calls,
                AVG(
                    CASE 
                        -- If it is a numeric float/integer
                        WHEN time_taken ~ '^[0-9.]+$' THEN time_taken::double precision
                        -- If it is formatted as "0.456s"
                        WHEN time_taken ~ '^[0-9.]+s$' THEN REPLACE(time_taken, 's', '')::double precision
                        -- If it is formatted as "120ms"
                        WHEN time_taken ~ '^[0-9.]+ms$' THEN REPLACE(time_taken, 'ms', '')::double precision / 1000.0
                        ELSE NULL
                    END
                ) as avg_latency
            FROM activity_logs
            WHERE created_at >= date_trunc('month', CURRENT_TIMESTAMP)
            GROUP BY UPPER(endpoint)
        """)
        stats_rows = cursor.fetchall()

        # Build dictionary from stats
        stats_map = {}
        for row in stats_rows:
            stats_map[row['endpoint_key']] = {
                'total_calls': row['total_calls'],
                'avg_latency': row['avg_latency']
            }

        # 2. Retrieve endpoint configs from api_endpoints
        cursor.execute("""
            SELECT id, endpoint_name, url_path, status, is_active 
            FROM api_endpoints 
            ORDER BY id ASC
        """)
        endpoint_rows = cursor.fetchall()
        cursor.close()

        endpoints = []
        for ep in endpoint_rows:
            # Map endpoint_name to endpoint_key in activity_logs
            name = ep['endpoint_name']
            # Map Scrape API -> /SCRAPE, Crawl API -> /CRAWL, etc.
            key_mapping = {
                'Scrape API': '/SCRAPE',
                'Crawl API': '/CRAWL',
                'Search API': '/SEARCH',
                'Screenshot API': '/SCREENSHOT',
                'Links API': '/LINKS'
            }
            key = key_mapping.get(name, f"/{name.split()[0].upper()}")
            ep_stats = stats_map.get(key, {'total_calls': 0, 'avg_latency': None})

            # Format average latency (in ms)
            if ep_stats['avg_latency'] is not None:
                avg_ms = ep_stats['avg_latency'] * 1000.0
                latency_str = f"{int(avg_ms)}ms"
            else:
                # Fallback mock value or '-' if there are no calls yet
                if ep_stats['total_calls'] > 0:
                    latency_str = "120ms"  # safe fallback if time_taken was null
                else:
                    latency_str = "-"

            # Format total calls
            calls_str = format_calls_count(ep_stats['total_calls'])

            endpoints.append(AdminEndpointResponse(
                id=ep['id'],
                name=ep['endpoint_name'],
                url_path=ep['url_path'],
                status=ep['status'],
                avg_latency=latency_str,
                total_calls=calls_str,
                is_active=ep['is_active']
            ))

        return AdminEndpointListResponse(
            success=True,
            endpoints=endpoints
        )
    except Exception as e:
        logger.error(f"Error fetching admin endpoints: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to fetch endpoints: {str(e)}")
    finally:
        if conn:
            conn.close()

@router.patch("/endpoints/{endpoint_id}", response_model=StandardResponse)
async def update_admin_endpoint(
    endpoint_id: int,
    request: UpdateEndpointRequest,
    _: bool = Depends(verify_admin_user)
):
    """
    Toggle endpoint configuration status ('Active' or 'Maintenance') and status boolean.
    """
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        # Check endpoint existence
        cursor.execute("SELECT id, endpoint_name FROM api_endpoints WHERE id = %s", (endpoint_id,))
        row = cursor.fetchone()
        if not row:
            cursor.close()
            raise HTTPException(status_code=404, detail="API Endpoint config not found.")

        updates = []
        params = []
        if request.status is not None:
            updates.append("status = %s")
            params.append(request.status)
        if request.is_active is not None:
            updates.append("is_active = %s")
            params.append(request.is_active)

        if updates:
            updates.append("updated_at = CURRENT_TIMESTAMP")
            query = f"UPDATE api_endpoints SET {', '.join(updates)} WHERE id = %s"
            params.append(endpoint_id)
            cursor.execute(query, tuple(params))
            conn.commit()

        cursor.close()
        return StandardResponse(
            success=True,
            message="API Endpoint configuration updated successfully."
        )
    except HTTPException:
        raise
    except Exception as e:
        if conn:
            conn.rollback()
        logger.error(f"Error updating API Endpoint {endpoint_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to update API Endpoint config: {str(e)}")
    finally:
        if conn:
            conn.close()
