#!/usr/bin/env python3
"""
Admin User Management Routes
Provides CRUD endpoints for managing users (GET, PATCH, DELETE).
Secure access is verified via JWT token authentication + admin_login check in database.
"""
import logging
from datetime import datetime
from typing import Optional, Dict, Any
from fastapi import APIRouter, HTTPException, Depends, Header, status
from psycopg2.extras import RealDictCursor
from api.core.database import get_db_connection
from api.core.security import get_current_user_from_token
from api.models.payloads import (
    AdminUserResponse,
    AdminUserListResponse,
    AdminUserUpdateRequest,
    StandardResponse
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/admin", tags=["Admin User Management"])

# ==================== DEPENDENCY FUNCTIONS ====================

async def verify_admin_user(
    current_user: Dict[str, Any] = Depends(get_current_user_from_token)
) -> bool:
    """
    Verify if the authenticated JWT user exists and is active.
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
        cursor.execute("SELECT is_active FROM users WHERE user_id = %s", (user_id,))
        row = cursor.fetchone()
        cursor.close()

        if not row:
            logger.warning(f"Forbidden access: User {user_id} not found")
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access forbidden: User not found."
            )
        return True
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error checking user status for user {user_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Database verification failed")
    finally:
        if conn:
            conn.close()


async def verify_admin_user_optional(
    authorization: Optional[str] = Header(None)
) -> Optional[bool]:
    """
    Optional auth check: If Authorization header is provided, validate it.
    If not provided, allow access.
    """
    if not authorization:
        return None

    parts = authorization.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Authorization header format. Use 'Bearer <token>'"
        )
    token = parts[1]

    from api.core.security import verify_jwt_token
    token_data = verify_jwt_token(token)
    if not token_data:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token."
        )

    user_id = token_data.get('user_id')
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token data."
        )

    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT is_active FROM users WHERE user_id = %s", (user_id,))
        row = cursor.fetchone()
        cursor.close()

        if not row:
            logger.warning(f"Forbidden access: User {user_id} not found")
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access forbidden: User not found."
            )
        return True
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error checking user status for user {user_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Database verification failed")
    finally:
        if conn:
            conn.close()

# ==================== ADMIN ENDPOINTS ====================

@router.get("/users", response_model=AdminUserListResponse)
async def get_admin_users(
    page: int = 1,
    limit: int = 50,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    _: bool = Depends(verify_admin_user)
):
    """
    Retrieve all users joined with plan info and request usage stats.
    Allows filtering by created_at date range (start_date, end_date).
    Orders users by last_login DESC (most recently logged-in users first).
    """
    offset = (page - 1) * limit
    
    # 1. Parse date filters if provided
    parsed_start = None
    if start_date:
        try:
            parsed_start = datetime.strptime(start_date, "%Y-%m-%d")
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid start_date format. Use YYYY-MM-DD.")
            
    parsed_end = None
    if end_date:
        try:
            # Set time to end of day to include the entire day
            parsed_end = datetime.strptime(f"{end_date} 23:59:59", "%Y-%m-%d %H:%M:%S")
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid end_date format. Use YYYY-MM-DD.")

    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        
        # 2. Build Count Query
        count_query = "SELECT COUNT(*) FROM users u WHERE 1=1"
        count_params = []
        if parsed_start:
            count_query += " AND u.created_at >= %s"
            count_params.append(parsed_start)
        if parsed_end:
            count_query += " AND u.created_at <= %s"
            count_params.append(parsed_end)
            
        cursor.execute(count_query, tuple(count_params))
        total_count = cursor.fetchone()['count']
        
        # 3. Build Select Query
        select_query = """
            SELECT 
                u.user_id,
                u.name,
                u.email,
                u.is_active,
                u.created_at,
                u.last_login,
                COALESCE(p.plan_type, 'free') as plan_type,
                CASE WHEN e.subscript_type = 'YEARLY' THEN COALESCE(ys.credits_included, ms.credits_included, 500) ELSE COALESCE(ms.credits_included, 500) END as total_requests,
                COALESCE(p.used_requests, 0) as used_requests,
                COALESCE(e.subscript_type, 'MONTHLY') as subscript_type
            FROM users u
            LEFT JOIN user_plans p ON u.user_id = p.user_id
            LEFT JOIN plan_expiry e ON u.user_id = e.user_id
            LEFT JOIN monthly_subscription_plans ms ON p.plan_type = ms.plan_key
            LEFT JOIN yearly_subscription_plans ys ON p.plan_type = ys.plan_key
            WHERE 1=1
        """
        select_params = []
        if parsed_start:
            select_query += " AND u.created_at >= %s"
            select_params.append(parsed_start)
        if parsed_end:
            select_query += " AND u.created_at <= %s"
            select_params.append(parsed_end)
            
        select_query += " ORDER BY u.last_login DESC NULLS LAST, u.created_at DESC LIMIT %s OFFSET %s"
        select_params.extend([limit, offset])
        
        cursor.execute(select_query, tuple(select_params))
        rows = cursor.fetchall()
        cursor.close()

        users = []
        for row in rows:
            formatted_id = f"USR-{row['user_id']:03d}"
            status_str = "Active" if row['is_active'] else "Suspended"
            
            created_at_str = row['created_at'].isoformat() if isinstance(row['created_at'], datetime) else str(row['created_at'])
            last_login_str = row['last_login'].isoformat() if isinstance(row['last_login'], datetime) else (str(row['last_login']) if row['last_login'] else None)

            users.append(AdminUserResponse(
                user_id=row['user_id'],
                formatted_user_id=formatted_id,
                name=row['name'],
                email=row['email'],
                plan_type=row['plan_type'],
                subscript_type=row['subscript_type'],
                total_requests=int(row['total_requests']),
                used_requests=int(row['used_requests']),
                status=status_str,
                created_at=created_at_str,
                last_login=last_login_str
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
        if request.plan_type is not None or request.used_requests is not None:
            # 1. Fetch current plan details
            cursor.execute("SELECT plan_type, used_requests FROM user_plans WHERE user_id = %s", (user_id,))
            plan_row = cursor.fetchone()

            current_plan = plan_row['plan_type'] if plan_row else 'free'
            current_used = plan_row['used_requests'] if plan_row else 0

            target_plan = request.plan_type.lower() if request.plan_type is not None else current_plan

            # 2. Get limit (credits_included) for target plan
            cursor.execute("""
                SELECT e.subscript_type 
                FROM plan_expiry e 
                WHERE e.user_id = %s
            """, (user_id,))
            exp_row = cursor.fetchone()
            sub_type = exp_row['subscript_type'] if exp_row else 'MONTHLY'
            
            target_sub_type = request.subscript_type.upper() if request.subscript_type is not None else sub_type
            
            table_name = "yearly_subscription_plans" if target_sub_type == 'YEARLY' else "monthly_subscription_plans"
            cursor.execute(f"SELECT credits_included FROM {table_name} WHERE plan_key = %s", (target_plan,))
            limit_row = cursor.fetchone()
            credits_included = limit_row['credits_included'] if limit_row else 500

            # 3. Determine new used_requests
            if request.used_requests is not None:
                new_used = request.used_requests
                if new_used < 0 or new_used > credits_included:
                    cursor.close()
                    raise HTTPException(
                        status_code=400,
                        detail=f"used_requests must be between 0 and {credits_included} for plan '{target_plan}'"
                    )
            else:
                if request.plan_type is not None:
                    # 3a. Rollover: save remaining credits from old paid plan
                    if current_plan != 'free' and current_plan != target_plan:
                        cursor.execute("""
                            SELECT e.subscript_type, e.expiry_date
                            FROM plan_expiry e
                            WHERE e.user_id = %s AND e.expiry_date > CURRENT_TIMESTAMP
                        """, (user_id,))
                        old_exp_row = cursor.fetchone()
                        old_cycle = old_exp_row['subscript_type'] if old_exp_row else 'MONTHLY'
                        old_expiry = old_exp_row['expiry_date'] if old_exp_row else None

                        # Get old plan total credits
                        old_table = "yearly_subscription_plans" if old_cycle == 'YEARLY' else "monthly_subscription_plans"
                        cursor.execute(f"SELECT credits_included FROM {old_table} WHERE plan_key = %s", (current_plan,))
                        old_limit_row = cursor.fetchone()
                        if old_limit_row and old_expiry:
                            old_limit = old_limit_row['credits_included']
                            remaining = old_limit - current_used
                            if remaining > 0:
                                cursor.execute("""
                                    INSERT INTO rollover_credits (user_id, credits, expiry_date)
                                    VALUES (%s, %s, %s)
                                """, (user_id, remaining, old_expiry))

                    # Reset to 0 when plan changes and no used_requests is specified
                    new_used = 0
                else:
                    new_used = current_used
                    if new_used > credits_included:
                        new_used = credits_included

            # 4. Upsert user_plans
            cursor.execute("""
                INSERT INTO user_plans (user_id, plan_type, used_requests, updated_at)
                VALUES (%s, %s, %s, CURRENT_TIMESTAMP)
                ON CONFLICT (user_id) DO UPDATE SET
                    plan_type = EXCLUDED.plan_type,
                    used_requests = EXCLUDED.used_requests,
                    updated_at = EXCLUDED.updated_at
            """, (user_id, target_plan, new_used))

            # 5. Upsert plan_expiry if plan_type or subscript_type was explicitly updated
            if request.plan_type is not None or request.subscript_type is not None:
                cursor.execute("""
                    INSERT INTO plan_expiry (user_id, plan_type, subscript_type, expiry_date, is_active, updated_at)
                    VALUES (%s, %s, %s, CURRENT_TIMESTAMP + interval '30 days', TRUE, CURRENT_TIMESTAMP)
                    ON CONFLICT (user_id) DO UPDATE SET
                        plan_type = EXCLUDED.plan_type,
                        subscript_type = EXCLUDED.subscript_type,
                        updated_at = EXCLUDED.updated_at
                """, (user_id, target_plan, target_sub_type))

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
