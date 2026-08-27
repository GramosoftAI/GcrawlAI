import logging
import os
from typing import Optional
from urllib.parse import quote, unquote
from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import RedirectResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import httpx

from api.models.gcrawl_payloads import (
    SignupOTPRequest,
    VerifyOTPRequest,
    SignInRequest,
    ForgotPasswordRequest,
    ResetPasswordRequest,
    OTPResponse,
    AuthResponse,
    StandardResponse,
    CurrentUserResponse,
    UserResponse
)
from api.core.security import _auth_manager

logger = logging.getLogger(__name__)

router = APIRouter()
security = HTTPBearer(auto_error=False)

def get_auth_manager():
    """Return auth manager."""
    from api.core.security import _auth_manager
    if not _auth_manager:
        raise HTTPException(
            status_code=503,
            detail="Authentication service not initialized"
        )
    return _auth_manager

@router.post("/auth/signup/send-otp", tags=["Authentication"], response_model=OTPResponse)
async def send_signup_otp(request: SignupOTPRequest):
    """Send signup otp."""
    try:
        am = get_auth_manager()
        success, message, otp, status_code = am.generate_signup_otp(
            request.name,
            request.email,
            request.password
        )
        if not success:
            raise HTTPException(status_code=status_code, detail=message)
        logger.info(f"OTP sent successfully to {request.email}")
        return OTPResponse(success=success, message=message)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Send OTP error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to send OTP: {str(e)}")

@router.post("/auth/signup/verify-otp", tags=["Authentication"], response_model=AuthResponse)
async def verify_signup_otp(request: VerifyOTPRequest):
    """Verify signup otp."""
    try:
        am = get_auth_manager()
        response = am.verify_signup_otp(request.email, request.otp)
        if not response['success']:
            raise HTTPException(status_code=response.get('status_code', 400), detail=response['message'])
        logger.info(f"OTP verified successfully for {request.email}")
        return AuthResponse(**response)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Verify OTP error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Verification failed: {str(e)}")

@router.post("/auth/signin", tags=["Authentication"], response_model=AuthResponse)
async def sign_in(request: SignInRequest):
    """Sign in."""
    try:
        am = get_auth_manager()
        response = am.sign_in(request.email, request.password)
        if not response['success']:
            raise HTTPException(status_code=response.get('status_code', 401), detail=response['message'])
        logger.info(f"User signed in successfully: {request.email}")
        return AuthResponse(**response)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Sign in error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Authentication failed: {str(e)}")

@router.post("/auth/forgot-password", tags=["Authentication"], response_model=StandardResponse)
async def forgot_password(request: ForgotPasswordRequest):
    """Forgot password."""
    try:
        am = get_auth_manager()
        success, message, encrypted_token, status_code = am.request_password_reset(request.email)
        if success and encrypted_token:
            logger.info(f"Password reset token generated for {request.email}")
        return StandardResponse(success=success, message=message)
    except Exception as e:
        logger.error(f"Forgot password error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Password reset request failed: {str(e)}")

@router.post("/auth/reset-password", tags=["Authentication"], response_model=StandardResponse)
async def reset_password(request: ResetPasswordRequest):
    """Reset password."""
    try:
        am = get_auth_manager()
        success, message, status_code = am.reset_password_with_token(request.token, request.new_password)
        if not success:
            raise HTTPException(status_code=status_code, detail=message)
        logger.info("Password reset successful via encrypted token")
        return StandardResponse(success=True, message=message)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Reset password error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Password reset failed: {str(e)}")

@router.get("/auth/me", tags=["Authentication"], response_model=CurrentUserResponse)
async def get_current_user_info(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """Return current user info."""
    try:
        am = get_auth_manager()
        if not credentials:
            raise HTTPException(status_code=401, detail="Not authenticated")
            
        token = credentials.credentials
        token_data = am.verify_token(token)
        if not token_data:
            raise HTTPException(status_code=401, detail="Invalid or expired token")
        
        user_id = token_data.get('user_id')
        if not user_id:
            raise HTTPException(status_code=401, detail="Invalid token data")
        
        user = am.get_user_by_id(user_id)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        
        logger.info(f"User info retrieved for user_id: {user_id}")
        return CurrentUserResponse(success=True, user=UserResponse(**user))
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Get user info error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to get user info: {str(e)}")


@router.get("/auth/google", tags=["Authentication"])
async def google_login(redirectUrl: str):
    """
    Initiate Google OAuth login sequence
    """
    google_client_id = os.getenv("GOOGLE_CLIENT_ID")
    google_callback_url = os.getenv("GOOGLE_CALLBACK_URL")
    
    if not google_client_id or not google_callback_url:
        logger.error("Google OAuth configurations missing in environment variables.")
        raise HTTPException(status_code=500, detail="Google OAuth configuration missing on server.")
        
    google_authorization_endpoint = (
        f"https://accounts.google.com/o/oauth2/v2/auth?"
        f"client_id={google_client_id}&"
        f"redirect_uri={quote(google_callback_url)}&"
        f"response_type=code&"
        f"scope=openid%20email%20profile&"
        f"state={quote(redirectUrl)}"
    )
    return RedirectResponse(google_authorization_endpoint)


@router.get("/auth/google/callback", tags=["Authentication"])
async def google_callback(code: str, state: str):
    """
    Google OAuth callback endpoint to exchange code and authenticate user
    """
    # Google state acts as the redirectUrl back to the frontend callback page
    frontend_callback = unquote(state)
    
    google_client_id = os.getenv("GOOGLE_CLIENT_ID")
    google_client_secret = os.getenv("GOOGLE_CLIENT_SECRET")
    google_callback_url = os.getenv("GOOGLE_CALLBACK_URL")
    
    if not google_client_id or not google_client_secret or not google_callback_url:
        logger.error("Google OAuth configurations missing in environment variables during callback.")
        err_msg = quote("Google OAuth server configuration missing")
        return RedirectResponse(f"{frontend_callback}?error={err_msg}")
        
    try:
        # Exchange authorization code for token
        async with httpx.AsyncClient() as client:
            token_resp = await client.post(
                "https://oauth2.googleapis.com/token",
                data={
                    "client_id": google_client_id,
                    "client_secret": google_client_secret,
                    "code": code,
                    "grant_type": "authorization_code",
                    "redirect_uri": google_callback_url
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"}
            )
            
            if token_resp.status_code != 200:
                logger.error(f"Failed token exchange with Google: {token_resp.text}")
                err_msg = quote("Failed token exchange with Google")
                return RedirectResponse(f"{frontend_callback}?error={err_msg}")
                
            token_data = token_resp.json()
            access_token = token_data.get("access_token")
            
            # Fetch user profile using access token
            userinfo_resp = await client.get(
                "https://www.googleapis.com/oauth2/v3/userinfo",
                headers={"Authorization": f"Bearer {access_token}"}
            )
            
            if userinfo_resp.status_code != 200:
                logger.error(f"Failed fetching user profile from Google: {userinfo_resp.text}")
                err_msg = quote("Failed retrieving Google profile info")
                return RedirectResponse(f"{frontend_callback}?error={err_msg}")
                
            profile = userinfo_resp.json()
            email = profile.get("email")
            name = profile.get("name", "Google User")
            
            if not email:
                logger.error("No email returned by Google profile.")
                err_msg = quote("Email not provided by Google account")
                return RedirectResponse(f"{frontend_callback}?error={err_msg}")
                
            # Log in or register user
            am = get_auth_manager()
            user = am.get_user_by_email(email)
            
            if not user:
                # User does not exist, create a new active user account
                user = am.create_oauth_user(name, email)
                if not user:
                    logger.error(f"Failed to create new OAuth user account for {email}")
                    err_msg = quote("Failed to register new account")
                    return RedirectResponse(f"{frontend_callback}?error={err_msg}")
                    
            if not user.get("is_active"):
                err_msg = quote("User account is inactive")
                return RedirectResponse(f"{frontend_callback}?error={err_msg}")
                
            # Generate JWT authentication access token for client
            jwt_token = am.jwt_manager.create_access_token({
                "user_id": user["user_id"],
                "email": user["email"]
            })
            
            logger.info(f"User {email} successfully authenticated via Google OAuth")
            return RedirectResponse(f"{frontend_callback}?token={jwt_token}")
            
    except Exception as e:
        logger.error(f"Exception during Google OAuth callback: {e}", exc_info=True)
        err_msg = quote("An error occurred during authentication")
        return RedirectResponse(f"{frontend_callback}?error={err_msg}")
