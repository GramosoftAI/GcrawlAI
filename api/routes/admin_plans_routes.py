#!/usr/bin/env python3
"""
Admin Subscription Plans Management Routes
Provides read and update endpoints for subscription plans.
"""
import logging
from typing import Optional
from fastapi import APIRouter, HTTPException, Depends, Query
from psycopg2.extras import RealDictCursor
from api.core.database import get_db_connection
from api.routes.admin_users_routes import verify_admin_user, verify_admin_user_optional
from api.models.payloads import (
    AdminPlanResponse,
    AdminPlanListResponse,
    UpdatePlanRequest,
    StandardResponse,
    CreatePlanRequest
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/admin", tags=["Admin User Management"])

@router.get("/plans", response_model=AdminPlanListResponse)
async def list_subscription_plans(
    _: Optional[bool] = Depends(verify_admin_user_optional)
):
    """
    Retrieve all subscription plan tiers and specifications.
    """
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        
        # Monthly Plans
        cursor.execute("""
            SELECT id, plan_name, plan_key, price_usd, price_inr, credits_included, max_concurrency, monthly_product_id_inr, monthly_product_id_usd 
            FROM monthly_subscription_plans 
            ORDER BY id ASC
        """)
        monthly_rows = cursor.fetchall()
        
        # Yearly Plans
        cursor.execute("""
            SELECT id, plan_name, plan_key, price_usd, price_inr, credits_included, max_concurrency, yearly_product_id_inr, yearly_product_id_usd 
            FROM yearly_subscription_plans 
            ORDER BY id ASC
        """)
        yearly_rows = cursor.fetchall()
        cursor.close()

        monthly_plans = [
            AdminPlanResponse(
                id=row['id'],
                plan_name=row['plan_name'],
                plan_key=row['plan_key'],
                price_usd=row['price_usd'],
                price_inr=row['price_inr'],
                credits_included=row['credits_included'],
                max_concurrency=row['max_concurrency'],
                monthly_product_id_inr=row['monthly_product_id_inr'],
                monthly_product_id_usd=row['monthly_product_id_usd']
            ) for row in monthly_rows
        ]
        
        yearly_plans = [
            AdminPlanResponse(
                id=row['id'],
                plan_name=row['plan_name'],
                plan_key=row['plan_key'],
                price_usd=row['price_usd'],
                price_inr=row['price_inr'],
                credits_included=row['credits_included'],
                max_concurrency=row['max_concurrency'],
                yearly_product_id_inr=row['yearly_product_id_inr'],
                yearly_product_id_usd=row['yearly_product_id_usd']
            ) for row in yearly_rows
        ]

        from api.models.payloads import AdminPlansData
        return AdminPlanListResponse(
            success=True,
            data=AdminPlansData(monthly=monthly_plans, yearly=yearly_plans)
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
    cycle: str = Query('monthly', enum=['monthly', 'yearly']),
    _: bool = Depends(verify_admin_user)
):
    """
    Update details for a specific subscription plan tier template.
    """
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        table_name = "monthly_subscription_plans" if cycle == 'monthly' else "yearly_subscription_plans"
        
        # Check plan existence
        cursor.execute(f"SELECT id, plan_name FROM {table_name} WHERE id = %s", (plan_id,))
        row = cursor.fetchone()
        if not row:
            cursor.close()
            raise HTTPException(status_code=404, detail=f"Subscription plan not found in {cycle} plans.")

        updates = []
        params = []
        if request.price_usd is not None:
            updates.append("price_usd = %s")
            params.append(request.price_usd)
        if request.price_inr is not None:
            updates.append("price_inr = %s")
            params.append(request.price_inr)
        if request.credits_included is not None:
            updates.append("credits_included = %s")
            params.append(request.credits_included)
        if request.max_concurrency is not None:
            updates.append("max_concurrency = %s")
            params.append(request.max_concurrency)
            
        if cycle == 'monthly':
            if request.monthly_product_id_inr is not None:
                updates.append("monthly_product_id_inr = %s")
                params.append(request.monthly_product_id_inr)
            if request.monthly_product_id_usd is not None:
                updates.append("monthly_product_id_usd = %s")
                params.append(request.monthly_product_id_usd)
        if cycle == 'yearly':
            if request.yearly_product_id_inr is not None:
                updates.append("yearly_product_id_inr = %s")
                params.append(request.yearly_product_id_inr)
            if request.yearly_product_id_usd is not None:
                updates.append("yearly_product_id_usd = %s")
                params.append(request.yearly_product_id_usd)

        if updates:
            updates.append("updated_at = CURRENT_TIMESTAMP")
            query = f"UPDATE {table_name} SET {', '.join(updates)} WHERE id = %s"
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


@router.post("/plans", response_model=StandardResponse)
async def create_subscription_plan(
    request: CreatePlanRequest,
    cycle: str = Query('monthly', enum=['monthly', 'yearly']),
    _: bool = Depends(verify_admin_user)
):
    """
    Create a new subscription plan tier template.
    """
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        table_name = "monthly_subscription_plans" if cycle == 'monthly' else "yearly_subscription_plans"
        
        # Check if plan_key or plan_name already exists to avoid duplicate constraint errors
        cursor.execute(f"SELECT id FROM {table_name} WHERE plan_key = %s OR plan_name = %s", (request.plan_key, request.plan_name))
        if cursor.fetchone():
            cursor.close()
            raise HTTPException(status_code=400, detail=f"A plan with plan_key '{request.plan_key}' or plan_name '{request.plan_name}' already exists in {cycle} plans.")

        # Determine product ID column and value
        if cycle == 'monthly':
            query = f"""
                INSERT INTO {table_name} (plan_name, plan_key, price_usd, price_inr, credits_included, max_concurrency, monthly_product_id_inr, monthly_product_id_usd)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """
            params = (request.plan_name, request.plan_key, request.price_usd, request.price_inr, request.credits_included, request.max_concurrency, request.monthly_product_id_inr, request.monthly_product_id_usd)
        else:
            query = f"""
                INSERT INTO {table_name} (plan_name, plan_key, price_usd, price_inr, credits_included, max_concurrency, yearly_product_id_inr, yearly_product_id_usd)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """
            params = (request.plan_name, request.plan_key, request.price_usd, request.price_inr, request.credits_included, request.max_concurrency, request.yearly_product_id_inr, request.yearly_product_id_usd)

        cursor.execute(query, params)
        conn.commit()
        cursor.close()
        
        return StandardResponse(
            success=True,
            message=f"New plan '{request.plan_name}' created successfully in {cycle} plans."
        )
    except HTTPException:
        raise
    except Exception as e:
        if conn:
            conn.rollback()
        logger.error(f"Error creating subscription plan: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to create subscription plan: {str(e)}")
    finally:
        if conn:
            conn.close()


@router.delete("/plans/{plan_id}", response_model=StandardResponse)
async def delete_subscription_plan(
    plan_id: int,
    cycle: str = Query('monthly', enum=['monthly', 'yearly']),
    _: bool = Depends(verify_admin_user)
):
    """
    Delete a specific subscription plan tier template.
    """
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        table_name = "monthly_subscription_plans" if cycle == 'monthly' else "yearly_subscription_plans"
        
        # Check plan existence
        cursor.execute(f"SELECT plan_name FROM {table_name} WHERE id = %s", (plan_id,))
        row = cursor.fetchone()
        if not row:
            cursor.close()
            raise HTTPException(status_code=404, detail=f"Subscription plan with ID {plan_id} not found in {cycle} plans.")

        plan_name = row[0]
        
        # Delete plan
        cursor.execute(f"DELETE FROM {table_name} WHERE id = %s", (plan_id,))
        conn.commit()
        cursor.close()
        
        return StandardResponse(
            success=True,
            message=f"Subscription plan '{plan_name}' (ID {plan_id}) deleted successfully from {cycle} plans."
        )
    except HTTPException:
        raise
    except Exception as e:
        if conn:
            conn.rollback()
        logger.error(f"Error deleting subscription plan {plan_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to delete subscription plan: {str(e)}")
    finally:
        if conn:
            conn.close()
