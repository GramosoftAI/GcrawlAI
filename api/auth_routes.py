#!/usr/bin/env python3

"""
Authentication Routes for FastAPI Application

Complete authentication API with all endpoints, models, and FastAPI app.
Provides REST API endpoints for user authentication including:
- OTP-based signup (send OTP and verify OTP)
- User signin with JWT token generation
- Password reset with encrypted token
- Current user information retrieval

All business logic is delegated to AuthManager.
"""

import logging
from fastapi import FastAPI, HTTPException, Depends, Form
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr, field_validator
from typing import Optional
import uvicorn

from api.auth_manager import AuthManager

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Security scheme for JWT
security = HTTPBearer()

# ==================== REQUEST/RESPONSE MODELS ====================

class SignupOTPRequest(BaseModel):
    """Request model for sending signup OTP"""
    name: str
    email: EmailStr
    password: str
    
    @field_validator('name')
    @classmethod
    def validate_name(cls, v: str) -> str:
        if not v or len(v.strip()) < 2:
            raise ValueError('Name must be at least 2 characters long')
        return v.strip()
    
    @field_validator('password')
    @classmethod
    def validate_password(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError('Password must be at least 8 characters long')
        return v


class VerifyOTPRequest(BaseModel):
    """Request model for verifying OTP"""
    email: EmailStr
    otp: str
    
    @field_validator('otp')
    @classmethod
    def validate_otp(cls, v: str) -> str:
        if not v or len(v) != 5 or not v.isdigit():
            raise ValueError('OTP must be exactly 5 digits')
        return v


class SignInRequest(BaseModel):
    """Request model for user signin"""
    email: EmailStr
    password: str


class ForgotPasswordRequest(BaseModel):
    """Request model for forgot password"""
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    """Request model for password reset"""
    token: str
    new_password: str
    
    @field_validator('new_password')
    @classmethod
    def validate_new_password(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError('Password must be at least 8 characters long')
        return v


class UserResponse(BaseModel):
    """User information response model"""
    user_id: int
    name: str
    email: str
    created_at: str
    is_active: bool


class AuthResponse(BaseModel):
    """Authentication response model"""
    success: bool
    message: str
    access_token: Optional[str] = None
    user: Optional[UserResponse] = None
    expires_in: Optional[int] = None


class OTPResponse(BaseModel):
    """OTP generation response model"""
    success: bool
    message: str
    otp: Optional[str] = None


class StandardResponse(BaseModel):
    """Standard API response model"""
    success: bool
    message: str


class CurrentUserResponse(BaseModel):
    """Current user info response model"""
    success: bool
    user: UserResponse


# ==================== FASTAPI APPLICATION ====================

# Create FastAPI app
app = FastAPI(
    title="Authentication API",
    description="User authentication system with OTP-based signup and JWT tokens",
    version="1.0.0"
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure as needed
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize AuthManager (global instance)
auth_manager: Optional[AuthManager] = None


@app.on_event("startup")
async def startup_event():
    """Initialize authentication manager on startup"""
    global auth_manager
    try:
        auth_manager = AuthManager("config.yaml")
        logger.info("✓ Authentication manager initialized successfully")
    except Exception as e:
        logger.error(f"✗ Failed to initialize authentication manager: {e}")
        raise


@app.on_event("shutdown")
async def shutdown_event():
    """Cleanup on shutdown"""
    logger.info("Shutting down authentication API")


# ==================== HEALTH CHECK ====================

@app.get("/", tags=["Health"])
async def root():
    """API health check endpoint"""
    return {
        "status": "running",
        "service": "Authentication API",
        "version": "1.0.0"
    }


@app.get("/health", tags=["Health"])
async def health_check():
    """Detailed health check"""
    return {
        "status": "healthy",
        "auth_manager": "initialized" if auth_manager else "not initialized"
    }


# ==================== AUTHENTICATION ENDPOINTS ====================

@app.post("/auth/signup/send-otp", tags=["Authentication"], response_model=OTPResponse)
async def send_signup_otp(request: SignupOTPRequest):
    """
    Send OTP for email verification (Step 1 of signup)
    
    Args:
        request: User signup details (name, email, password)
    
    Returns:
        OTPResponse with success status and OTP (for testing if email not configured)
    
    Example:
```json
        {
            "name": "John Doe",
            "email": "john@example.com",
            "password": "SecurePass123"
        }
```
    """
    try:
        if not auth_manager:
            raise HTTPException(
                status_code=503,
                detail="Authentication service not initialized"
            )
        
        success, message, otp = auth_manager.generate_signup_otp(
            request.name,
            request.email,
            request.password
        )
        
        if not success:
            raise HTTPException(status_code=400, detail=message)
        
        logger.info(f"OTP sent successfully to {request.email}")
        
        return OTPResponse(
            success=success,
            message=message,
            otp=otp
        )
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Send OTP error: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to send OTP: {str(e)}"
        )


@app.post("/auth/signup/verify-otp", tags=["Authentication"], response_model=AuthResponse)
async def verify_signup_otp(request: VerifyOTPRequest):
    """
    Verify OTP and complete signup (Step 2 of signup)
    
    Args:
        request: Email and 5-digit OTP code
    
    Returns:
        AuthResponse with access token and user details
    
    Example:
```json
        {
            "email": "john@example.com",
            "otp": "12345"
        }
```
    """
    try:
        if not auth_manager:
            raise HTTPException(
                status_code=503,
                detail="Authentication service not initialized"
            )
        
        response = auth_manager.verify_signup_otp(
            request.email,
            request.otp
        )
        
        if not response['success']:
            raise HTTPException(status_code=400, detail=response['message'])
        
        logger.info(f"OTP verified successfully for {request.email}")
        
        return AuthResponse(**response)
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Verify OTP error: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Verification failed: {str(e)}"
        )


@app.post("/auth/signin", tags=["Authentication"], response_model=AuthResponse)
async def sign_in(request: SignInRequest):
    """
    Authenticate user and get access token
    
    Args:
        request: User credentials (email and password)
    
    Returns:
        AuthResponse with access token and user details
    
    Example:
```json
        {
            "email": "john@example.com",
            "password": "SecurePass123"
        }
```
    """
    try:
        if not auth_manager:
            raise HTTPException(
                status_code=503,
                detail="Authentication service not initialized"
            )
        
        response = auth_manager.sign_in(
            request.email,
            request.password
        )
        
        if not response['success']:
            raise HTTPException(status_code=401, detail=response['message'])
        
        logger.info(f"User signed in successfully: {request.email}")
        
        return AuthResponse(**response)
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Sign in error: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Authentication failed: {str(e)}"
        )


@app.post("/auth/forgot-password", tags=["Authentication"], response_model=StandardResponse)
async def forgot_password(request: ForgotPasswordRequest):
    """
    Request password reset with encrypted token
    
    Generates an encrypted token and sends password reset email.
    The token contains the user's email encrypted for security.
    
    Args:
        request: User email address
    
    Returns:
        StandardResponse with success status
    
    Example:
```json
        {
            "email": "john@example.com"
        }
```
    """
    try:
        if not auth_manager:
            raise HTTPException(
                status_code=503,
                detail="Authentication service not initialized"
            )
        
        success, message, encrypted_token = auth_manager.request_password_reset(
            request.email
        )
        
        if success and encrypted_token:
            logger.info(f"Password reset token generated for {request.email}")
        
        return StandardResponse(
            success=success,
            message=message
        )
    
    except Exception as e:
        logger.error(f"Forgot password error: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Password reset request failed: {str(e)}"
        )


@app.post("/auth/reset-password", tags=["Authentication"], response_model=StandardResponse)
async def reset_password(request: ResetPasswordRequest):
    """
    Reset password using encrypted token
    
    Decrypts the token to extract user email and updates password.
    Token must be valid and not expired.
    
    Args:
        request: Encrypted token and new password
    
    Returns:
        StandardResponse with success status
    
    Example:
```json
        {
            "token": "encrypted_token_here",
            "new_password": "NewSecurePass123"
        }
```
    """
    try:
        if not auth_manager:
            raise HTTPException(
                status_code=503,
                detail="Authentication service not initialized"
            )
        
        success, message = auth_manager.reset_password_with_token(
            request.token,
            request.new_password
        )
        
        if not success:
            raise HTTPException(status_code=400, detail=message)
        
        logger.info("Password reset successful via encrypted token")
        
        return StandardResponse(
            success=True,
            message=message
        )
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Reset password error: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Password reset failed: {str(e)}"
        )


@app.get("/auth/me", tags=["Authentication"], response_model=CurrentUserResponse)
async def get_current_user_info(
    credentials: HTTPAuthorizationCredentials = Depends(security)
):
    """
    Get current authenticated user information
    
    Requires valid JWT token in Authorization header.
    Token must be in format: "Bearer <token>"
    
    Args:
        credentials: JWT token from Authorization header
    
    Returns:
        CurrentUserResponse with user details
    
    Headers:
        Authorization: Bearer <your_jwt_token>
    """
    try:
        if not auth_manager:
            raise HTTPException(
                status_code=503,
                detail="Authentication service not initialized"
            )
        
        token = credentials.credentials
        
        # Verify token and extract user data
        token_data = auth_manager.verify_token(token)
        
        if not token_data:
            raise HTTPException(
                status_code=401,
                detail="Invalid or expired token"
            )
        
        user_id = token_data.get('user_id')
        if not user_id:
            raise HTTPException(
                status_code=401,
                detail="Invalid token data"
            )
        
        # Get user information
        user = auth_manager.get_user_by_id(user_id)
        
        if not user:
            raise HTTPException(
                status_code=404,
                detail="User not found"
            )
        
        logger.info(f"User info retrieved for user_id: {user_id}")
        
        return CurrentUserResponse(
            success=True,
            user=UserResponse(**user)
        )
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Get user info error: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get user info: {str(e)}"
        )


# ==================== MAIN EXECUTION ====================

if __name__ == "__main__":
    """Run the FastAPI application"""
    uvicorn.run(
        "auth_routes:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info"
    )