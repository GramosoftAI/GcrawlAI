from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, Field
from typing import Dict, Any, Optional
import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime, timedelta
import logging

from api.routes.api_key_routes import get_db_connection, get_current_user_from_token

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/payment", tags=["Payments"])

# Plan Definitions
PLAN_LIMITS = {
    "free": {"requests": 500, "concurrency": 2},
    "starter": {"requests": 30000, "concurrency": 5},
    "growth": {"requests": 50000, "concurrency": 15},
    "pro": {"requests": 150000, "concurrency": 25}
}

class DummyUpgradeRequest(BaseModel):
    plan_type: str = Field(..., description="Plan name (e.g. starter, growth, pro)")
    billing_cycle: str = Field(..., description="Billing cycle: MONTHLY or YEARLY")
    amount: float = Field(..., description="Amount paid in USD")

@router.post("/dummy-upgrade")
async def dummy_upgrade_plan(
    request: DummyUpgradeRequest,
    current_user: Dict[str, Any] = Depends(get_current_user_from_token)
):
    """
    Dummy endpoint to simulate payment and plan upgrade.
    Updates the database with the new plan and credit limits.
    """
    plan = request.plan_type.lower()
    cycle = request.billing_cycle.upper()
    
    if plan not in PLAN_LIMITS:
        raise HTTPException(status_code=400, detail=f"Invalid plan type. Must be one of: {list(PLAN_LIMITS.keys())}")
    
    if cycle not in ["MONTHLY", "YEARLY"]:
        raise HTTPException(status_code=400, detail="Invalid billing cycle. Must be MONTHLY or YEARLY")
        
    user_id = current_user.get('user_id')
    limits = PLAN_LIMITS[plan]
    
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # 1. Insert into payment_requests (Dummy Transaction)
        cursor.execute("""
            INSERT INTO payment_requests 
            (user_id, plan_type, subscript_type, amount, currency, status)
            VALUES (%s, %s, %s, %s, 'USD', 'success')
        """, (user_id, plan, cycle, request.amount))
        
        # 2. Update or Insert into user_plans (UPSERT)
        cursor.execute("""
            INSERT INTO user_plans (user_id, plan_type, total_requests, used_requests, concurrency_limit, updated_at)
            VALUES (%s, %s, %s, 0, %s, CURRENT_TIMESTAMP)
            ON CONFLICT (user_id) DO UPDATE SET 
                plan_type = EXCLUDED.plan_type, 
                total_requests = EXCLUDED.total_requests, 
                used_requests = EXCLUDED.used_requests, 
                concurrency_limit = EXCLUDED.concurrency_limit,
                updated_at = EXCLUDED.updated_at
        """, (user_id, plan, limits["requests"], limits["concurrency"]))
        
        # 3. Update or Insert into plan_expiry (UPSERT)
        days = 30 if cycle == "MONTHLY" else 365
        cursor.execute("""
            INSERT INTO plan_expiry (user_id, plan_type, subscript_type, expiry_date, is_active, updated_at)
            VALUES (%s, %s, %s, CURRENT_TIMESTAMP + interval '%s days', TRUE, CURRENT_TIMESTAMP)
            ON CONFLICT (user_id) DO UPDATE SET
                plan_type = EXCLUDED.plan_type,
                subscript_type = EXCLUDED.subscript_type,
                expiry_date = EXCLUDED.expiry_date,
                is_active = EXCLUDED.is_active,
                updated_at = EXCLUDED.updated_at
        """, (user_id, plan, cycle, days))
        
        conn.commit()
        cursor.close()
        
        logger.info(f"✅ User {user_id} successfully upgraded to {plan} ({cycle})")
        
        return {
            "success": True,
            "message": f"Successfully upgraded to {plan} plan.",
            "new_limits": {
                "total_requests": limits["requests"],
                "concurrency": limits["concurrency"],
                "expiry_days": days
            }
        }
        
    except Exception as e:
        if conn:
            conn.rollback()
        logger.error(f"Error processing dummy payment: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to process payment upgrade.")
    finally:
        if conn:
            conn.close()
