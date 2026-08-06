from pydantic import BaseModel, HttpUrl, StrictBool, StrictInt, StrictStr
from typing import List, Optional, Union
from datetime import datetime
class ProxyConfig(BaseModel):
    geo: Optional[StrictStr] = None

class MarkdownConfig(BaseModel):
    enabled: StrictBool
    clean: Optional[StrictBool] = True

class HtmlConfig(BaseModel):
    enabled: StrictBool
    clean: Optional[StrictBool] = True
    remove_external_links: Optional[StrictBool] = False
    relative_to_absolute_links: Optional[StrictBool] = True
    remove_data_images: Optional[StrictBool] = False
    ignore_tags: Optional[List[StrictStr]] = []

class ScreenshotConfig(BaseModel):
    enabled: StrictBool
    full_page: Optional[StrictBool] = False
    format: Optional[StrictStr] = "png"
    quality: Optional[StrictInt] = 90
    js_render: Optional[StrictBool] = False
    render_timeout: Optional[StrictInt] = 30000
    auto_scroll: Optional[StrictBool] = True
    scroll_delay: Optional[StrictInt] = 500
    max_scrolls: Optional[StrictInt] = 2

class SeoConfig(BaseModel):
    enabled: StrictBool

class ImagesConfig(BaseModel):
    enabled: StrictBool

class CrawlOptions(BaseModel):
    max_pages: Optional[Union[StrictInt, StrictStr]] = 10
    same_domain_only: Optional[StrictBool] = True
    include_subdomains: Optional[StrictBool] = False

class ScrapeRequest(BaseModel):
    url: HttpUrl
    proxy: Optional[ProxyConfig] = None
    markdown: Optional[MarkdownConfig] = None
    html: Optional[HtmlConfig] = None    
    screenshot: Optional[ScreenshotConfig] = None
    seo: Optional[SeoConfig] = None
    images: Optional[ImagesConfig] = None

class ScreenshotRequest(BaseModel):
    url: HttpUrl
    proxy: Optional[ProxyConfig] = None
    screenshot: ScreenshotConfig

class MultiCrawlRequest(BaseModel):
    url: HttpUrl
    crawl: Optional[CrawlOptions] = None
    proxy: Optional[ProxyConfig] = None
    markdown: Optional[MarkdownConfig] = None
    html: Optional[HtmlConfig] = None
    screenshot: Optional[ScreenshotConfig] = None
    seo: Optional[SeoConfig] = None
    images: Optional[ImagesConfig] = None

class LinksOptions(BaseModel):
    limit: Optional[Union[StrictInt, StrictStr]] = 100
    same_domain_only: Optional[bool] = True
    include_subdomains: Optional[bool] = False

class LinksRequest(BaseModel):
    url: HttpUrl
    links: Optional[LinksOptions] = None
    proxy: Optional[ProxyConfig] = None

class CrawlResponse(BaseModel):
    status_code: int = 200
    crawl_id: str
    url: str
    crawl_mode: str
    created_at: str
    task_id: Optional[str] = None
    SEO: bool
    HTML: bool
    Screenshot: bool
    Markdown: bool
    Images: bool
    status: str
    user_id: Optional[Union[int, str]] = None
    task_url: Optional[str] = None

class CrawlPathsResponse(BaseModel):
    status_code: int = 200
    status: str = "success"
    crawl_id: str
    summary_files: List[str]

class UserCrawlJobResponse(BaseModel):
    user_id: Optional[Union[int, str]] = None
    crawl_id: str
    url: str
    crawl_mode: str
    seo: bool
    html: bool
    screenshot: bool
    markdown: bool
    images: bool
    links: bool
    created_at: datetime

class UserCrawlsResponse(BaseModel):
    status_code: int = 200
    status: str = "success"
    crawls: List[UserCrawlJobResponse]

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
        """Validate name."""
        if not v or len(v.strip()) < 2:
            raise ValueError('Name must be at least 2 characters long')
        return v.strip()

    @field_validator('password')
    @classmethod
    def validate_password(cls, v: str) -> str:
        """Validate password."""
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
        """Validate otp."""
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
        """Validate new password."""
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
    admin_login: bool = False

class AuthResponse(BaseModel):
    """Authentication response model"""
    status_code: int = 200
    status: str = "success"
    success: bool
    message: str
    access_token: Optional[str] = None
    user: Optional[UserResponse] = None
    expires_in: Optional[str] = None

class OTPResponse(BaseModel):
    """OTP generation response model"""
    status_code: int = 200
    status: str = "success"
    success: bool
    message: str
    otp: Optional[str] = None

class StandardResponse(BaseModel):
    """Standard API response model"""
    status_code: int = 200
    status: str = "success"
    success: bool
    message: str

class CurrentUserResponse(BaseModel):
    """Current user info response model"""
    status_code: int = 200
    status: str = "success"
    success: bool
    user: UserResponse

class AdminUserResponse(BaseModel):
    """Response model for a single user detail in admin page"""
    user_id: int
    formatted_user_id: str
    name: str
    email: str
    plan_type: str
    subscript_type: str
    total_requests: int
    used_requests: int
    status: str  # "Active" or "Suspended"
    created_at: str
    last_login: Optional[str] = None

class AdminUserListResponse(BaseModel):
    """Response model for listing users in admin page"""
    status_code: int = 200
    status: str = "success"
    success: bool
    users: List[AdminUserResponse]
    total_count: int

class AdminUserUpdateRequest(BaseModel):
    """Request model for updating a user in admin page"""
    name: Optional[str] = None
    email: Optional[str] = None
    plan_type: Optional[str] = None
    subscript_type: Optional[str] = None
    used_requests: Optional[int] = None
    status: Optional[str] = None  # "Active" or "Suspended"
    is_active: Optional[bool] = None

class AdminEndpointResponse(BaseModel):
    """Response model representing details of a single API endpoint"""
    id: int
    name: str
    url_path: str
    status: str  # "Active" or "Maintenance"
    avg_latency: str  # e.g., "120ms" or "-"
    total_calls: str  # e.g., "1.2M", "800K", or "0"
    is_active: bool

class AdminEndpointListResponse(BaseModel):
    """Response model listing all monitored API endpoints"""
    status_code: int = 200
    status: str = "success"
    success: bool
    endpoints: List[AdminEndpointResponse]

class UpdateEndpointRequest(BaseModel):
    """Request model for updating an API endpoint status or toggle state"""
    status: Optional[str] = None  # "Active" or "Maintenance"
    is_active: Optional[bool] = None

class AdminPlanResponse(BaseModel):
    """Response model representing details of a single subscription plan tier"""
    id: int
    plan_name: str
    plan_key: str
    price_usd: str
    price_inr: str
    credits_included: int
    max_concurrency: int
    monthly_product_id_inr: Optional[str] = None
    monthly_product_id_usd: Optional[str] = None
    yearly_product_id_inr: Optional[str] = None
    yearly_product_id_usd: Optional[str] = None

class AdminPlansData(BaseModel):
    monthly: List[AdminPlanResponse]
    yearly: List[AdminPlanResponse]

class AdminPlanListResponse(BaseModel):
    """Response model listing all subscription plan tiers"""
    status_code: int = 200
    status: str = "success"
    success: bool
    data: AdminPlansData

class UpdatePlanRequest(BaseModel):
    """Request model for updating subscription plan settings"""
    price_usd: Optional[str] = None
    price_inr: Optional[str] = None
    credits_included: Optional[int] = None
    max_concurrency: Optional[int] = None
    monthly_product_id_inr: Optional[str] = None
    monthly_product_id_usd: Optional[str] = None
    yearly_product_id_inr: Optional[str] = None
    yearly_product_id_usd: Optional[str] = None

class DashboardStatCard(BaseModel):
    value: str
    change: Optional[str] = None
    sublabel: Optional[str] = None

class AdminDashboardStatsResponse(BaseModel):
    status_code: int = 200
    status: str = "success"
    success: bool
    total_users: DashboardStatCard
    active_endpoints: DashboardStatCard
    total_api_calls: DashboardStatCard
    system_health: DashboardStatCard

class CustomRequestSubmitPayload(BaseModel):
    """Payload for submitting a new custom scraping request"""
    full_name: str
    work_email: EmailStr
    company: Optional[str] = None
    expected_volume: str
    request_type: str
    target_websites: str
    description: str

class CustomRequestAdminResponse(BaseModel):
    """Response model for a single custom request in admin panel"""
    id: int
    formatted_id: str
    full_name: str
    work_email: str
    company: Optional[str] = None
    expected_volume: str
    request_type: str
    target_websites: str
    description: str
    status: str
    created_at: str

class CustomRequestListResponse(BaseModel):
    """Response model for listing custom requests in admin panel"""
    status_code: int = 200
    status: str = "success"
    success: bool
    data: List[CustomRequestAdminResponse]
    total_count: int

class ReportIssueAdminResponse(BaseModel):
    """Response model for a single reported issue in admin panel"""
    id: int
    formatted_id: str
    url_affected: str
    issue_related_to: List[str]
    explanation: str
    email: str
    user_id: Optional[str] = None
    status: str
    created_at: str

class ReportIssueListResponse(BaseModel):
    """Response model for listing reported issues in admin panel"""
    status_code: int = 200
    status: str = "success"
    success: bool
    data: List[ReportIssueAdminResponse]
    total_count: int

class CreatePlanRequest(BaseModel):
    """Request model for creating a new subscription plan tier template"""
    plan_name: str
    plan_key: str
    price_usd: str
    price_inr: str
    credits_included: int
    max_concurrency: int
    monthly_product_id_inr: Optional[str] = None
    monthly_product_id_usd: Optional[str] = None
    yearly_product_id_inr: Optional[str] = None
    yearly_product_id_usd: Optional[str] = None

from typing import Dict, Any

class DynamicFieldSchema(BaseModel):
    label: str
    input_type: str
    options: Optional[List[str]] = None

class CreateAutoRobotRequest(BaseModel):
    title: str
    category: str
    target_platform: str
    status: Optional[str] = "Active"
    sample_url: str
    description: Optional[str] = None
    dynamic_fields: Optional[List[DynamicFieldSchema]] = []
    sample_schema: Optional[Union[List[Any], Dict[str, Any]]] = []

class UpdateAutoRobotRequest(BaseModel):
    title: Optional[str] = None
    category: Optional[str] = None
    target_platform: Optional[str] = None
    status: Optional[str] = None
    sample_url: Optional[str] = None
    description: Optional[str] = None
    dynamic_fields: Optional[List[DynamicFieldSchema]] = None
    sample_schema: Optional[Union[List[Any], Dict[str, Any]]] = None

class AutoRobotResponse(BaseModel):
    id: int
    title: str
    category: str
    target_platform: str
    status: str
    sample_url: str
    description: Optional[str] = None
    dynamic_fields: List[DynamicFieldSchema]
    sample_schema: Union[List[Any], Dict[str, Any]]
    created_at: str
    updated_at: Optional[str] = None

class AutoRobotListResponse(BaseModel):
    status_code: int = 200
    status: str = "success"
    data: List[AutoRobotResponse]
    total_count: int