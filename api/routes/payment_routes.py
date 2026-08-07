import os
from fastapi import APIRouter, HTTPException, Depends, Request, Header
from pydantic import BaseModel, Field
from typing import Dict, Any, Optional
import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime, timedelta
import logging
from api.core.database import get_db_connection
from api.core.security import get_current_user_from_token
from dodopayments import AsyncDodoPayments

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/payment", tags=["Payments"])

# Plan Definitions

class CheckoutSessionRequest(BaseModel):
    product_id: str = Field(..., description="Dodo Payments product ID")
    plan_type: str = Field(..., description="Plan name (e.g. starter, growth, pro)")
    billing_cycle: str = Field(..., description="Billing cycle: MONTHLY or YEARLY")
    return_url: Optional[str] = Field(None, description="Dynamic redirect URL after successful payment")
    billing_currency: Optional[str] = Field(None, description="Billing currency (e.g. USD, INR)")


@router.post("/create-checkout-session")
async def create_checkout_session(
    request: CheckoutSessionRequest,
    current_user: Dict[str, Any] = Depends(get_current_user_from_token)
):
    """
    Creates a Dodo Payments checkout session and returns the checkout URL.
    """
    api_key = os.getenv("DODO_PAYMENTS_API_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="Dodo Payments API Key is not configured.")

    plan = request.plan_type.lower()
    cycle = request.billing_cycle.upper()

    if cycle not in ["MONTHLY", "YEARLY"]:
        raise HTTPException(status_code=400, detail="Invalid billing cycle. Must be MONTHLY or YEARLY")

    user_id = current_user.get('user_id')
    user_email = current_user.get('email')

    # Resolve return URL dynamically or use default
    target_return_url = request.return_url or "https://gcrawlai.com/summary?payment=success"

    try:
        env = os.getenv("DODO_PAYMENTS_ENVIRONMENT")
        if not env:
            api_env = os.getenv("API_ENV", "development").lower()
            env = "live_mode" if api_env == "production" else "test_mode"
        client = AsyncDodoPayments(bearer_token=api_key, environment=env)

        # Check if the customer already exists in Dodo Payments to enable autofill
        customer_id = None
        try:
            customers_page = await client.customers.list(email=user_email)
            existing_customer = None
            if hasattr(customers_page, "items") and customers_page.items:
                existing_customer = customers_page.items[0]
            elif isinstance(customers_page, list) and customers_page:
                existing_customer = customers_page[0]

            if existing_customer:
                customer_id = getattr(existing_customer, "customer_id", None) or getattr(existing_customer, "id", None)
                logger.info(f"Resolved existing Dodo customer_id: {customer_id} for email: {user_email}")
        except Exception as list_err:
            logger.warning(f"Failed to check existing customer in Dodo Payments: {list_err}")

        session_args = {
            "product_cart": [
                {
                    "product_id": request.product_id,
                    "quantity": 1
                }
            ],
            "customer": {
                "customer_id": customer_id
            } if customer_id else {
                "email": user_email
            },
            "return_url": target_return_url,
            "metadata": {
                "user_id": str(user_id),
                "plan_type": plan,
                "billing_cycle": cycle
            }
        }

        if request.billing_currency:
            session_args["billing_currency"] = request.billing_currency.upper()

        session = await client.checkout_sessions.create(**session_args)

        return {
            "success": True,
            "checkout_url": session.checkout_url,
            "session_id": session.session_id
        }

    except Exception as e:
        logger.error(f"Error creating checkout session: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to create checkout session.")



@router.get("/subscription-summary/{subscription_id}")
async def get_subscription_summary(
    subscription_id: str,
    current_user: Dict[str, Any] = Depends(get_current_user_from_token)
):
    """
    Retrieves the billing and transaction details for a specific Subscription ID.
    """
    api_key = os.getenv("DODO_PAYMENTS_API_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="Dodo Payments API Key is not configured.")

    try:
        env = os.getenv("DODO_PAYMENTS_ENVIRONMENT")
        if not env:
            api_env = os.getenv("API_ENV", "development").lower()
            env = "live_mode" if api_env == "production" else "test_mode"
            
        client = AsyncDodoPayments(bearer_token=api_key, environment=env)
        
        # 1. Fetch subscription details
        subscription = await client.subscriptions.retrieve(subscription_id)
        
        summary = {
            "subscription_id": subscription_id,
            "status": subscription.status,
            "customer": {
                "name": current_user.get("username"),
                "email": current_user.get("email"),
                "phone": None
            },
            "billing_address": None,
            "amount_details": None
        }
        
        # Update customer details from subscription object if they exist
        if subscription.customer:
            summary["customer"]["name"] = subscription.customer.name or summary["customer"]["name"]
            summary["customer"]["email"] = subscription.customer.email or summary["customer"]["email"]
            
        # Extract billing address
        if getattr(subscription, "billing", None):
            b = subscription.billing
            summary["billing_address"] = {
                "street": getattr(b, "street", None),
                "city": getattr(b, "city", None),
                "state": getattr(b, "state", None),
                "country": getattr(b, "country", None),
                "zipcode": getattr(b, "zipcode", None)
            }
            
        # 2. Fetch payments list to get amount details
        payments_list = await client.payments.list(subscription_id=subscription_id)
        if payments_list and payments_list.items:
            latest_payment_summary = payments_list.items[0]
            
            # Retrieve full payment details to get billing address and tax breakdown
            payment = await client.payments.retrieve(latest_payment_summary.payment_id)
            
            # Extract customer info from payment if available
            if payment.customer:
                summary["customer"]["name"] = payment.customer.name or summary["customer"]["name"]
                summary["customer"]["email"] = payment.customer.email or summary["customer"]["email"]
                summary["customer"]["phone"] = payment.customer.phone_number
 
            # Extract billing address from payment if not set
            if payment.billing and not summary["billing_address"]:
                b = payment.billing
                summary["billing_address"] = {
                    "street": b.street,
                    "city": b.city,
                    "state": b.state,
                    "country": b.country,
                    "zipcode": b.zipcode
                }
 
            # Extract breakdown and convert cents to major currency unit
            total = (payment.total_amount or 0) / 100
            tax = (payment.tax or 0) / 100
            subtotal = total - tax
            
            summary["amount_details"] = {
                "subtotal": round(subtotal, 2),
                "tax_gst": round(tax, 2),
                "total": round(total, 2),
                "currency": payment.currency
            }
            
        return {
            "success": True,
            "data": summary
        }

    except Exception as e:
        logger.error(f"Error fetching subscription summary for {subscription_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to fetch subscription summary.")



@router.post("/webhook")
async def dodo_webhook(
    request: Request,
    webhook_signature: str = Header(..., alias="webhook-signature")
):
    """
    Webhook receiver for Dodo Payments.
    Verifies the signature and updates the user plan when checkout completes.
    """
    webhook_secret = os.getenv("DODO_PAYMENTS_WEBHOOK_SECRET")
    if not webhook_secret:
        logger.error("Dodo Payments Webhook Secret is not configured.")
        raise HTTPException(status_code=500, detail="Webhook Secret is not configured.")

    payload = await request.body()
    payload_str = payload.decode("utf-8")

    # 1. Verify and Parse Webhook Event
    try:
        api_key = os.getenv("DODO_PAYMENTS_API_KEY") or "dummy"
        env = os.getenv("DODO_PAYMENTS_ENVIRONMENT")
        if not env:
            api_env = os.getenv("API_ENV", "development").lower()
            env = "live_mode" if api_env == "production" else "test_mode"
        client = AsyncDodoPayments(bearer_token=api_key, environment=env)
        # Note: We must convert headers to a plain dict for the verify helper
        headers = dict(request.headers)
        event = client.webhooks.unwrap(payload_str, headers=headers, key=webhook_secret)
        
        # Convert Pydantic object to dict for safe access
        if hasattr(event, "model_dump"):
            event_dict = event.model_dump()
        else:
            event_dict = event.dict()
    except Exception as verify_err:
        logger.warning(f"Webhook verification failed: {verify_err}")
        raise HTTPException(status_code=400, detail="Invalid signature or payload")

    event_type = event_dict.get("type")
    if event_type != "payment.succeeded":
        # Return 200 OK so Dodo Payments knows we received it, even if we ignore it
        return {"success": True, "message": f"Ignored event type: {event_type}"}

    data = event_dict.get("data", {})
    
    # Option 1: Sync the latest phone number from checkout form to Dodo Payments Customer profile
    customer = data.get("customer") if isinstance(data, dict) else None
    if isinstance(customer, dict):
        customer_id = customer.get("customer_id") or customer.get("id")
        phone_number = customer.get("phone_number")
        if customer_id and phone_number:
            try:
                await client.customers.update(
                    customer_id=customer_id,
                    phone_number=phone_number
                )
                logger.info(f"Updated customer {customer_id} phone number to {phone_number} on Dodo Payments")
            except Exception as customer_update_err:
                logger.warning(f"Failed to update customer {customer_id} phone number on Dodo Payments: {customer_update_err}")

    metadata = data.get("metadata", {}) or {}
    
    user_id = metadata.get("user_id")
    plan = metadata.get("plan_type")
    cycle = metadata.get("billing_cycle")
    
    # Convert amount from cents to USD
    amount = data.get("total_amount", 0) / 100

    if not user_id or not plan or not cycle:
        logger.error(f"Webhook metadata missing: user_id={user_id}, plan={plan}, cycle={cycle}")
        raise HTTPException(status_code=400, detail="Missing required metadata")

    plan = plan.lower()
    cycle = cycle.upper()

    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        # Query target plan specifications dynamically from subscription_plans
        if cycle == 'YEARLY':
            cursor.execute("SELECT credits_included, max_concurrency FROM yearly_subscription_plans WHERE plan_key = %s", (plan,))
        else:
            cursor.execute("SELECT credits_included, max_concurrency FROM monthly_subscription_plans WHERE plan_key = %s", (plan,))
        plan_row = cursor.fetchone()
        if not plan_row:
            logger.error(f"Invalid plan type '{plan}' received in webhook metadata.")
            raise HTTPException(status_code=400, detail=f"Invalid plan type: {plan}")

        credits_val = plan_row[0]
        concurrency_val = plan_row[1]

        # 1. Insert into payment_requests (Transaction Log)
        cursor.execute("""
            INSERT INTO payment_requests 
            (user_id, plan_type, subscript_type, amount, currency, status)
            VALUES (%s, %s, %s, %s, 'USD', 'success')
        """, (user_id, plan, cycle, amount))

        # 1.5 Rollover Logic: Save remaining credits from old paid plan
        cursor.execute("""
            SELECT p.plan_type, p.used_requests, e.expiry_date, e.subscript_type
            FROM user_plans p 
            JOIN plan_expiry e ON p.user_id = e.user_id 
            WHERE p.user_id = %s AND e.expiry_date > CURRENT_TIMESTAMP
        """, (user_id,))
        old_plan_data = cursor.fetchone()
        
        if old_plan_data:
            old_plan_type, old_used, old_expiry, old_cycle = old_plan_data
            if old_plan_type != 'free':
                if old_cycle == 'YEARLY':
                    cursor.execute("SELECT credits_included FROM yearly_subscription_plans WHERE plan_key = %s", (old_plan_type,))
                else:
                    cursor.execute("SELECT credits_included FROM monthly_subscription_plans WHERE plan_key = %s", (old_plan_type,))
                old_plan_row = cursor.fetchone()
                
                if old_plan_row:
                    old_limit = old_plan_row[0]
                    remaining = old_limit - old_used
                    if remaining > 0:
                        cursor.execute("""
                            INSERT INTO rollover_credits (user_id, credits, expiry_date)
                            VALUES (%s, %s, %s)
                        """, (user_id, remaining, old_expiry))

        # 2. Update or Insert into user_plans (UPSERT)
        cursor.execute("""
            INSERT INTO user_plans (user_id, plan_type, used_requests, updated_at)
            VALUES (%s, %s, 0, CURRENT_TIMESTAMP)
            ON CONFLICT (user_id) DO UPDATE SET 
                plan_type = EXCLUDED.plan_type, 
                used_requests = EXCLUDED.used_requests, 
                updated_at = EXCLUDED.updated_at
        """, (user_id, plan))

        # 3. Update or Insert into plan_expiry (UPSERT)
        days = 30 if cycle == "MONTHLY" else 365
        cursor.execute("""
            INSERT INTO plan_expiry (user_id, plan_type, subscript_type, expiry_date, is_active, updated_at)
            VALUES (%s, %s, %s, CURRENT_TIMESTAMP + (%s * interval '1 day'), TRUE, CURRENT_TIMESTAMP)
            ON CONFLICT (user_id) DO UPDATE SET
                plan_type = EXCLUDED.plan_type,
                subscript_type = EXCLUDED.subscript_type,
                expiry_date = EXCLUDED.expiry_date,
                is_active = EXCLUDED.is_active,
                updated_at = EXCLUDED.updated_at
        """, (user_id, plan, cycle, days))

        conn.commit()
        cursor.close()

        logger.info(f"✅ User {user_id} successfully upgraded to {plan} ({cycle}) via Dodo Payments Webhook")
        return {"success": True, "message": f"Successfully upgraded user {user_id} to {plan} plan."}

    except Exception as e:
        if conn:
            conn.rollback()
        logger.error(f"Error processing webhook database update: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to process webhook upgrade.")
    finally:
        if conn:
            conn.close()

@router.get("/my-plan")

async def get_my_plan(
    request: Request,
    authorization: Optional[str] = Header(None, description="Authorization: Bearer <token>"),
    x_api_key: Optional[str] = Header(None, alias="X-API-Key", description="API key for client access")

):

    """
    Fetch the active subscription plan, request limits, and expiration date for the authenticated user.
    """
    from api.core.security import validate_recaptcha_or_jwt

    try:
        user_id = validate_recaptcha_or_jwt(
            auth_header=authorization,
            recaptcha_header=None,
            api_key_header=x_api_key or request.headers.get("x-api-key") or request.headers.get("api_key") or request.headers.get("api-key") or request.headers.get("apikey")
        )

    except Exception as e:
        raise HTTPException(status_code=401, detail=f"Authentication failed: {str(e)}")
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        cursor.execute("""
            SELECT p.plan_type, 
                   CASE WHEN e.subscript_type = 'YEARLY' THEN COALESCE(ys.credits_included, ms.credits_included, 500) ELSE COALESCE(ms.credits_included, 500) END as total_requests, 
                   p.used_requests, e.expiry_date, e.subscript_type
            FROM user_plans p
            LEFT JOIN plan_expiry e ON p.user_id = e.user_id
            LEFT JOIN monthly_subscription_plans ms ON p.plan_type = ms.plan_key
            LEFT JOIN yearly_subscription_plans ys ON p.plan_type = ys.plan_key
            WHERE p.user_id = %s
        """, (user_id,))

        result = cursor.fetchone()

        if not result:
            cursor.close()
            raise HTTPException(status_code=404, detail="Plan details not found for this user.")

        # Fetch non-expired rollover credit pools ordered by earliest expiry
        cursor.execute("""
            SELECT id, credits, expiry_date
            FROM rollover_credits
            WHERE user_id = %s AND expiry_date > CURRENT_TIMESTAMP
            ORDER BY expiry_date ASC
        """, (user_id,))
        rollover_rows = cursor.fetchall()
        cursor.close()

        total_rollover = sum(row["credits"] for row in rollover_rows)
        rollover_breakdown = [
            {
                "rollover_id": row["id"],
                "credits": row["credits"],
                "expires_at": row["expiry_date"].isoformat() if row["expiry_date"] else None
            }
            for row in rollover_rows
        ]

        return {
            "plan_type": result["plan_type"],
            "total_requests": result["total_requests"],
            "used_requests": result["used_requests"],
            "expiry_date": result["expiry_date"].isoformat() if result["expiry_date"] else None,
            "subscript_type": result["subscript_type"],
            "rollover_credits_for_old_plans": {
                "total_rollover_credits": total_rollover,
                "pools": rollover_breakdown
            }
        }

    except HTTPException:
        raise

    except Exception as e:
        logger.error(f"Error fetching user plan details: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to fetch plan details.")

    finally:
        if conn:
            conn.close()

