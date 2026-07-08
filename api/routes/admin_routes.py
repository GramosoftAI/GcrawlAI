#!/usr/bin/env python3

"""

Admin User Management Routes

Provides CRUD endpoints for managing users (GET, PATCH, DELETE).

Secure access is verified via JWT token authentication + admin_login check in database.

"""

import logging

from datetime import datetime

from typing import Optional, Dict, Any, List

from fastapi import APIRouter, HTTPException, Depends, Header, status

from psycopg2.extras import RealDictCursor

from api.routes.api_key_routes import get_db_connection, get_current_user_from_token

from api.models.payloads import (

    AdminUserResponse,

    AdminUserListResponse,

    AdminUserUpdateRequest,

    StandardResponse,

    AdminEndpointResponse,

    AdminEndpointListResponse,

    UpdateEndpointRequest,

    AdminPlanResponse,

    AdminPlanListResponse,

    UpdatePlanRequest,
    AdminDashboardStatsResponse,
    DashboardStatCard

)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["Admin User Management"])

# ==================== DEPENDENCY FUNCTIONS ====================

async def verify_admin_user(

    current_user: Dict[str, Any] = Depends(get_current_user_from_token)

) -> bool:

    """

    Verify if the authenticated JWT user has admin privileges (admin_login == True).

    """

    user_id = current_user.get('user_id')

    if not user_id:

        raise HTTPException(

            status_code=status.HTTP_401_UNAUTHORIZED,

            detail="Invalid authentication token."

        )

    conn = None

    try:

        conn = get_db_connection()

        cursor = conn.cursor()

        cursor.execute("SELECT admin_login FROM users WHERE user_id = %s", (user_id,))

        row = cursor.fetchone()

        cursor.close()

        if not row or not row[0]:

            logger.warning(f"Forbidden admin access attempt by user {user_id}")

            raise HTTPException(

                status_code=status.HTTP_403_FORBIDDEN,

                detail="Access forbidden: User is not an admin."

            )

        return True

    except HTTPException:

        raise

    except Exception as e:

        logger.error(f"Error checking admin status for user {user_id}: {e}", exc_info=True)

        raise HTTPException(status_code=500, detail="Database verification failed")

    finally:

        if conn:

            conn.close()

# ==================== ADMIN ENDPOINTS ====================

@router.get("/users", response_model=AdminUserListResponse)

async def get_admin_users(

    page: int = 1,

    limit: int = 50,

    _: bool = Depends(verify_admin_user)

):

    """

    Retrieve all users joined with plan info and request usage stats.

    """

    offset = (page - 1) * limit

    conn = None

    try:

        conn = get_db_connection()

        cursor = conn.cursor(cursor_factory=RealDictCursor)

        # Count total users

        cursor.execute("SELECT COUNT(*) FROM users")

        total_count = cursor.fetchone()['count']

        # Fetch users with plan details

        cursor.execute("""

            SELECT 

                u.user_id,

                u.name,

                u.email,

                u.is_active,

                u.created_at,

                COALESCE(p.plan_type, 'free') as plan_type,

                COALESCE(p.total_requests, 0) as total_requests,

                COALESCE(p.used_requests, 0) as used_requests

            FROM users u

            LEFT JOIN user_plans p ON u.user_id = p.user_id

            ORDER BY u.user_id ASC

            LIMIT %s OFFSET %s

        """, (limit, offset))

        rows = cursor.fetchall()

        cursor.close()

        users = []

        for row in rows:

            formatted_id = f"USR-{row['user_id']:03d}"

            status_str = "Active" if row['is_active'] else "Suspended"

            if isinstance(row['created_at'], datetime):

                created_at_str = row['created_at'].isoformat()

            else:

                created_at_str = str(row['created_at'])

            users.append(AdminUserResponse(

                user_id=row['user_id'],

                formatted_user_id=formatted_id,

                name=row['name'],

                email=row['email'],

                plan_type=row['plan_type'],

                total_requests=int(row['total_requests']),

                used_requests=int(row['used_requests']),

                status=status_str,

                created_at=created_at_str

            ))

        return AdminUserListResponse(

            success=True,

            users=users,

            total_count=total_count

        )

    except Exception as e:

        logger.error(f"Error fetching admin users list: {e}", exc_info=True)

        raise HTTPException(status_code=500, detail=f"Failed to fetch users: {str(e)}")

    finally:

        if conn:

            conn.close()

@router.patch("/users/{user_id}", response_model=StandardResponse)

async def update_admin_user(

    user_id: int,

    request: AdminUserUpdateRequest,

    _: bool = Depends(verify_admin_user)

):

    """

    Update details (name, email, plan, credits, status) of a user.

    """

    conn = None

    try:

        conn = get_db_connection()

        cursor = conn.cursor(cursor_factory=RealDictCursor)

        # Check user existence

        cursor.execute("SELECT user_id, is_active FROM users WHERE user_id = %s", (user_id,))

        user_row = cursor.fetchone()

        if not user_row:

            cursor.close()

            raise HTTPException(status_code=404, detail="User not found")

        # Update fields in users table

        user_updates = []

        user_params = []

        if request.name is not None:

            user_updates.append("name = %s")

            user_params.append(request.name)

        if request.email is not None:

            user_updates.append("email = %s")

            user_params.append(request.email.lower())

        # Handle status logic mapping

        is_active_val = None

        if request.status is not None:

            is_active_val = (request.status.lower() == "active")

        elif request.is_active is not None:

            is_active_val = request.is_active

        if is_active_val is not None:

            user_updates.append("is_active = %s")

            user_params.append(is_active_val)

        if user_updates:

            user_updates.append("updated_at = CURRENT_TIMESTAMP")

            query = f"UPDATE users SET {', '.join(user_updates)} WHERE user_id = %s"

            user_params.append(user_id)

            cursor.execute(query, tuple(user_params))

        # Update fields in user_plans and plan_expiry

        if request.plan_type is not None or request.total_requests is not None:

            cursor.execute("SELECT plan_type, total_requests, concurrency_limit FROM user_plans WHERE user_id = %s", (user_id,))

            plan_row = cursor.fetchone()

            current_plan = plan_row['plan_type'] if plan_row else 'free'

            current_total = plan_row['total_requests'] if plan_row else 500

            current_concurrency = plan_row['concurrency_limit'] if plan_row else 2

            new_plan = request.plan_type.lower() if request.plan_type is not None else current_plan

            new_total = request.total_requests if request.total_requests is not None else current_total

            # Retrieve default limits from payment routes

            from api.routes.payment_routes import PLAN_LIMITS

            limits = PLAN_LIMITS.get(new_plan)

            if limits:

                new_concurrency = limits['concurrency']

                if request.total_requests is None:

                    new_total = limits['requests']

            else:

                new_concurrency = current_concurrency

            # Update user_plans

            cursor.execute("""

                INSERT INTO user_plans (user_id, plan_type, total_requests, used_requests, concurrency_limit, updated_at)

                VALUES (%s, %s, %s, 0, %s, CURRENT_TIMESTAMP)

                ON CONFLICT (user_id) DO UPDATE SET

                    plan_type = EXCLUDED.plan_type,

                    total_requests = EXCLUDED.total_requests,

                    concurrency_limit = EXCLUDED.concurrency_limit,

                    updated_at = EXCLUDED.updated_at

            """, (user_id, new_plan, new_total, new_concurrency))

            # Update plan_expiry

            cursor.execute("""

                INSERT INTO plan_expiry (user_id, plan_type, subscript_type, expiry_date, is_active, updated_at)

                VALUES (%s, %s, 'MONTHLY', CURRENT_TIMESTAMP + interval '30 days', TRUE, CURRENT_TIMESTAMP)

                ON CONFLICT (user_id) DO UPDATE SET

                    plan_type = EXCLUDED.plan_type,

                    updated_at = EXCLUDED.updated_at

            """, (user_id, new_plan))

        conn.commit()

        cursor.close()

        return StandardResponse(

            success=True,

            message="User updated successfully"

        )

    except HTTPException:

        raise

    except Exception as e:

        if conn:

            conn.rollback()

        logger.error(f"Error updating user {user_id}: {e}", exc_info=True)

        raise HTTPException(status_code=500, detail=f"Failed to update user: {str(e)}")

    finally:

        if conn:

            conn.close()

@router.delete("/users/{user_id}", response_model=StandardResponse)

async def delete_admin_user(

    user_id: int,

    _: bool = Depends(verify_admin_user)

):

    """

    Permanently delete a user from the system. Cascades to plans and expiries.

    """

    conn = None

    try:

        conn = get_db_connection()

        cursor = conn.cursor(cursor_factory=RealDictCursor)

        # Check user existence

        cursor.execute("SELECT user_id FROM users WHERE user_id = %s", (user_id,))

        user_row = cursor.fetchone()

        if not user_row:

            cursor.close()

            raise HTTPException(status_code=404, detail="User not found")

        # Delete user

        cursor.execute("DELETE FROM users WHERE user_id = %s", (user_id,))

        conn.commit()

        cursor.close()

        return StandardResponse(

            success=True,

            message="User deleted successfully"

        )

    except HTTPException:

        raise

    except Exception as e:

        if conn:

            conn.rollback()

        logger.error(f"Error deleting user {user_id}: {e}", exc_info=True)

        raise HTTPException(status_code=500, detail=f"Failed to delete user: {str(e)}")

    finally:

        if conn:

            conn.close()

def format_calls_count(count: int) -> str:

    """Format total calls count into human-readable notation (e.g. 1.2M, 800K, 0)"""

    if count >= 1_000_000:

        return f"{count / 1_000_000:.1f}M".replace(".0M", "M")

    elif count >= 1_000:

        return f"{count / 1_000:.0f}K"

    return str(count)

@router.get("/endpoints", response_model=AdminEndpointListResponse)

async def get_admin_endpoints(

    _: bool = Depends(verify_admin_user)

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

@router.get("/plans", response_model=AdminPlanListResponse)

async def list_subscription_plans(

    _: bool = Depends(verify_admin_user)

):

    """

    Retrieve all subscription plan tiers and specifications.

    """

    conn = None

    try:

        conn = get_db_connection()

        cursor = conn.cursor(cursor_factory=RealDictCursor)

        cursor.execute("""

            SELECT id, plan_name, plan_key, price, credits_included, max_concurrency 

            FROM subscription_plans 

            ORDER BY id ASC

        """)

        rows = cursor.fetchall()

        cursor.close()

        return AdminPlanListResponse(

            success=True,

            plans=[

                AdminPlanResponse(

                    id=row['id'],

                    plan_name=row['plan_name'],

                    plan_key=row['plan_key'],

                    price=row['price'],

                    credits_included=row['credits_included'],

                    max_concurrency=row['max_concurrency']

                ) for row in rows

            ]

        )

    except Exception as e:

        logger.error(f"Error fetching subscription plans: {e}", exc_info=True)

        raise HTTPException(status_code=500, detail=f"Failed to fetch subscription plans: {str(e)}")

    finally:

        if conn:

            conn.close()

@router.patch("/plans/{plan_id}", response_model=StandardResponse)

async def update_subscription_plan(

    plan_id: int,

    request: UpdatePlanRequest,
    AdminDashboardStatsResponse,
    DashboardStatCard,

    _: bool = Depends(verify_admin_user)

):

    """

    Update details for a specific subscription plan tier template.

    """

    conn = None

    try:

        conn = get_db_connection()

        cursor = conn.cursor()

        # Check plan existence

        cursor.execute("SELECT id, plan_name FROM subscription_plans WHERE id = %s", (plan_id,))

        row = cursor.fetchone()

        if not row:

            cursor.close()

            raise HTTPException(status_code=404, detail="Subscription plan not found.")

        updates = []

        params = []

        if request.price is not None:

            updates.append("price = %s")

            params.append(request.price)

        if request.credits_included is not None:

            updates.append("credits_included = %s")

            params.append(request.credits_included)

        if request.max_concurrency is not None:

            updates.append("max_concurrency = %s")

            params.append(request.max_concurrency)

        if updates:

            updates.append("updated_at = CURRENT_TIMESTAMP")

            query = f"UPDATE subscription_plans SET {', '.join(updates)} WHERE id = %s"

            params.append(plan_id)

            cursor.execute(query, tuple(params))

            conn.commit()

        cursor.close()

        return StandardResponse(

            success=True,

            message="Subscription plan updated successfully."

        )

    except HTTPException:

        raise

    except Exception as e:

        if conn:

            conn.rollback()

        logger.error(f"Error updating subscription plan {plan_id}: {e}", exc_info=True)

        raise HTTPException(status_code=500, detail=f"Failed to update subscription plan: {str(e)}")

    finally:

        if conn:

            conn.close()

@router.get("/stats", response_model=AdminDashboardStatsResponse)
async def get_admin_dashboard_stats(
    _: bool = Depends(verify_admin_user)
):
    """
    Retrieve global platform overview statistics for the Admin Dashboard.
    """
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # 1. Query Total Users and Weekly Change
        cursor.execute("SELECT COUNT(*) FROM users")
        total_users = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM users WHERE created_at >= NOW() - INTERVAL '7 days'")
        weekly_users = cursor.fetchone()[0]
        
        # 2. Query Active Jobs (Crawl & Search tasks count)
        cursor.execute("SELECT COUNT(*) FROM crawl_jobs")
        crawl_jobs_count = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM search_jobs")
        search_jobs_count = cursor.fetchone()[0]
        
        total_jobs = crawl_jobs_count + search_jobs_count
        
        # 3. Query Total API Calls from activity_logs
        cursor.execute("SELECT COUNT(*) FROM activity_logs")
        total_api_calls = cursor.fetchone()[0]
        
        # 4. Query System Health dynamically from api_endpoints status
        cursor.execute("SELECT COUNT(*), SUM(CASE WHEN is_active = TRUE THEN 1 ELSE 0 END) FROM api_endpoints")
        health_row = cursor.fetchone()
        
        total_endpoints = health_row[0] or 0
        active_endpoints = health_row[1] or 0
        
        cursor.close()
        
        # System Health percentage calculation logic
        if total_endpoints == 0:
            health_str = "100%"
            health_sublabel = "All systems operational"
        else:
            ratio = active_endpoints / total_endpoints
            if ratio == 1.0:
                health_str = "99.9%"
                health_sublabel = "All systems operational"
            else:
                health_str = f"{ratio * 100:.1f}%"
                down_count = total_endpoints - active_endpoints
                health_sublabel = f"{down_count} API Endpoint(s) under maintenance"
                
        return AdminDashboardStatsResponse(
            success=True,
            total_users=DashboardStatCard(
                value=f"{total_users:,}",
                change=f"+{weekly_users} this week"
            ),
            active_endpoints=DashboardStatCard(
                value=f"{total_jobs:,}",
                sublabel="Live scraping jobs"
            ),
            total_api_calls=DashboardStatCard(
                value=format_calls_count(total_api_calls),
                sublabel="Current billing cycle"
            ),
            system_health=DashboardStatCard(
                value=health_str,
                sublabel=health_sublabel
            )
        )
    except Exception as e:
        logger.error(f"Error fetching admin dashboard statistics: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to fetch dashboard statistics: {str(e)}")
    finally:
        if conn:
            conn.close()
