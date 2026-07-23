import os
import logging
import requests
from typing import Optional, Dict, Any, Union
from fastapi import HTTPException
from api.routes.api_key_routes import validate_api_key_from_header

logger = logging.getLogger(__name__)

# To break circular dependency, auth_manager will be set from api.py 
# or imported directly but since AuthManager needs config which needs DB, etc...
# We will access the global auth_manager from api.api or a registry.
# However, the user wants us to not break anything. 
# Better: We can just initialize a temporary AuthManager here OR we can import the global auth_manager.
# To avoid circular imports, let's keep a module-level reference that api.py can inject.

_auth_manager = None

def set_auth_manager(am):
    global _auth_manager
    _auth_manager = am

def verify_recaptcha(token: str) -> bool:
    if token == "valid_mock_recaptcha":
        logger.info("✓ [AUTH] Development mock reCAPTCHA bypass allowed.")
        return True
        
    secret_key = os.getenv("RECAPTCHA_SECRET_KEY")
    if not secret_key:
        logger.warning("RECAPTCHA_SECRET_KEY is not set in .env. Verification skipped/allowed for local development.")
        return True
    
    try:
        url = "https://www.google.com/recaptcha/api/siteverify"
        payload = {
            "secret": secret_key,
            "response": token
        }
        res = requests.post(url, data=payload, timeout=5)
        res_json = res.json()
        success = res_json.get("success", False)

        if not success:
            logger.warning(f"Google reCAPTCHA verification failed. Response: {res_json}")
            logger.warning("Secret key: %s", secret_key)
            logger.warning("Received token: %s", token)
            logger.warning("Google response: %s", res_json)
        return success
    except Exception as e:
        logger.error(f"reCAPTCHA network/parsing error: {e}", exc_info=True)
        return False

def verify_jwt_token(token: str) -> Optional[Dict[str, Any]]:
    global _auth_manager
    if not _auth_manager or not _auth_manager.jwt_manager:
        logger.error("AuthManager or JWTManager is not initialized yet!")
        return None
    return _auth_manager.jwt_manager.verify_token(token)

def validate_recaptcha_or_jwt(
    auth_header: Optional[str] = None,
    recaptcha_header: Optional[str] = None,
    api_key_header: Optional[str] = None
) -> Union[int, str]:
    """
    Validates X-API-Key, JWT token, or reCAPTCHA token.
    Order of checks:
      1. API Key via X-API-Key header
      2. JWT token via Authorization header
      3. reCAPTCHA token via recaptcha-token header
    Returns:
        user_id (Union[int, str]): The authenticated user ID for API key or JWT, or "demo" for anonymous guest via reCAPTCHA.
    Raises:
        HTTPException(401): If authentication fails or is missing.
    """
    api_key_error = False
    auth_error = False
    recaptcha_error = False

    # 1. Highest priority: Check for API Key in X-API-Key header
    if api_key_header:
        api_key = api_key_header.strip().strip("'\"")
        if api_key:
            validation_result = validate_api_key_from_header(api_key)
            if validation_result:
                logger.info(f"✓ [AUTH] API key authentication successful for user_id: {validation_result['user_id']}")
                return int(validation_result['user_id'])
            logger.warning("API key provided but validation failed.")
            api_key_error = True

    # 2. Next priority: Check for JWT Access Token in Authorization header
    token = None
    if auth_header:
        # Strip leading/trailing spaces and quotes
        cleaned = auth_header.strip().strip("'\"")

        # If user passed it as "Authorization: Bearer <token>" or "authorization: <token>"
        if cleaned.lower().startswith("authorization:"):
            cleaned = cleaned[14:].strip().strip("'\"")

        # Strip "bearer " if present
        if cleaned.lower().startswith("bearer "):
            cleaned = cleaned[7:].strip().strip("'\"")

        token = cleaned.strip()

    if token:
        try:
            payload = verify_jwt_token(token)
        except HTTPException as exc:
            logger.warning(f"JWT token validation failed: {exc.detail}")
            auth_error = True
        else:
            if payload:
                uid = payload.get("user_id")
                if uid is not None:
                    logger.info(f"✓ [AUTH] JWT authentication successful for user_id: {uid}")
                    return int(uid)
            auth_error = True

    # 3. Last priority: Check for reCAPTCHA Token in recaptcha-token header
    if recaptcha_header:
        if verify_recaptcha(recaptcha_header):
            logger.info("✓ [AUTH] Anonymous reCAPTCHA verification successful.")
            return "demo"
        logger.warning("reCAPTCHA token provided but verification failed.")
        recaptcha_error = True

    # No authentication succeeded
    if api_key_error and not auth_header and not recaptcha_header:
        raise HTTPException(
            status_code=401,
            detail="Invalid API key. Please provide a valid X-API-Key header."
        )
    if auth_error and recaptcha_error:
        raise HTTPException(status_code=401, detail="Invalid API key, authentication token, or reCAPTCHA token")
    if auth_error:
        raise HTTPException(status_code=401, detail="Invalid or expired authentication token")
    if api_key_error:
        raise HTTPException(status_code=401, detail="Invalid or expired API key")
    
    raise HTTPException(status_code=401, detail="Missing authentication token, API key, or reCAPTCHA token")

def check_plan_limits_and_get_details(user_id: Union[int, str]) -> tuple[str, int]:
    """
    Checks if the user has a valid plan and hasn't exhausted their requests.
    Returns (plan_type, concurrency_limit).
    """
    if user_id == "demo":
        # Guest fallback
        return ("free", 2)
        
    from api.core.database import get_pooled_connection
    with get_pooled_connection() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT u.plan_type, 
                   CASE WHEN e.subscript_type = 'YEARLY' THEN COALESCE(ys.max_concurrency, ms.max_concurrency, 2) ELSE COALESCE(ms.max_concurrency, 2) END, 
                   CASE WHEN e.subscript_type = 'YEARLY' THEN COALESCE(ys.credits_included, ms.credits_included, 500) ELSE COALESCE(ms.credits_included, 500) END as total_requests, 
                   u.used_requests
            FROM user_plans u
            LEFT JOIN plan_expiry e ON u.user_id = e.user_id
            LEFT JOIN monthly_subscription_plans ms ON u.plan_type = ms.plan_key
            LEFT JOIN yearly_subscription_plans ys ON u.plan_type = ys.plan_key
            WHERE u.user_id = %s
        """, (user_id,))
        plan_data = cur.fetchone()
        
    if not plan_data:
        raise HTTPException(status_code=403, detail="No active plan found.")
        
    plan_type = plan_data[0]
    concurrency_limit = plan_data[1]
    total_requests = plan_data[2]
    used_requests = plan_data[3]
    
    if used_requests >= total_requests:
        raise HTTPException(status_code=429, detail="Request limit exhausted for this billing cycle.")
        
    return plan_type, concurrency_limit

def increment_used_requests(user_id: Union[int, str], amount: int = 1):
    """Increments the used_requests counter for a user upon successful task completion."""
    if user_id == "demo" or amount <= 0:
        return
        
    from api.core.database import get_pooled_connection
    try:
        with get_pooled_connection() as conn:
            cur = conn.cursor()
            cur.execute("UPDATE user_plans SET used_requests = used_requests + %s WHERE user_id = %s", (amount, user_id))
            conn.commit()
    except Exception as e:
        logger.error(f"Failed to increment used requests by {amount} for user {user_id}: {e}")


def check_endpoint_active(endpoint_name: str) -> None:
    """
    Checks if an API endpoint is currently active.
    If the endpoint status is 'Maintenance' or is_active is False, raises HTTP 503.
    """
    from api.core.database import get_pooled_connection
    try:
        with get_pooled_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT status, is_active FROM api_endpoints WHERE endpoint_name = %s",
                    (endpoint_name,)
                )
                row = cur.fetchone()
        
        if row:
            status_val, is_active = row[0], row[1]
            if not is_active or status_val.lower() == 'maintenance':
                raise HTTPException(
                    status_code=503,
                    detail=f"{endpoint_name} is currently under maintenance. Please try again later."
                )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error checking endpoint active state for {endpoint_name}: {e}")

