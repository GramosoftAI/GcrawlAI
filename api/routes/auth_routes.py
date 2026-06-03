import logging
from typing import Optional
from fastapi import APIRouter, HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from api.models.payloads import (
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
    from api.core.security import _auth_manager
    if not _auth_manager:
        raise HTTPException(
            status_code=503,
            detail="Authentication service not initialized"
        )
    return _auth_manager

@router.post("/auth/signup/send-otp", tags=["Authentication"], response_model=OTPResponse)
async def send_signup_otp(request: SignupOTPRequest):
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
