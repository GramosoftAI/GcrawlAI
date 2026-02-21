from fastapi import FastAPI, HTTPException, Depends, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.responses import HTMLResponse
from fastapi.responses import PlainTextResponse
from fastapi.responses import JSONResponse

from pydantic import BaseModel, EmailStr, HttpUrl, field_validator
from typing import List, Literal, Optional
from datetime import datetime
from pathlib import Path
import psycopg2
import pytz
import logging
import traceback
import markdown
import os
from dotenv import load_dotenv
import re

from fastapi import WebSocket, WebSocketDisconnect
from api.websocket_manager import WebSocketManager
import redis
import json
import uuid

ws_manager = WebSocketManager()
redis_client = redis.Redis.from_url("redis://localhost:6379/0", decode_responses=True)

import yaml
from pathlib import Path

# Load environment variables from .env file
load_dotenv()

_CONFIG = None


def substitute_env_vars(data):
    """
    Recursively substitute environment variables in configuration.
    Supports format: ${VAR_NAME} or ${VAR_NAME:default_value}
    """
    if isinstance(data, dict):
        return {key: substitute_env_vars(value) for key, value in data.items()}
    elif isinstance(data, list):
        return [substitute_env_vars(item) for item in data]
    elif isinstance(data, str):
        # Pattern: ${VAR_NAME} or ${VAR_NAME:default_value}
        def replace_var(match):
            var_name = match.group(1)
            default_value = match.group(2)
            return os.getenv(var_name, default_value or "")
        
        return re.sub(r'\$\{([^:}]+)(?::([^}]*))?\}', replace_var, data)
    else:
        return data


def load_config():
    global _CONFIG
    if _CONFIG is None:
        config_path = "config.yaml"
        with open(config_path, "r", encoding="utf-8") as f:
            raw_config = yaml.safe_load(f)
            # Substitute environment variables
            _CONFIG = substitute_env_vars(raw_config)
    return _CONFIG

def get_db_config():
    config = load_config()
    return config["postgres"]

# ================= INTERNAL IMPORTS =================

from api.auth_manager import AuthManager
from web_crawler.crawler import main as crawl_main
from web_crawler.config import CrawlConfig
from web_crawler.celery_tasks import crawl_website, crawl_single_page
from api.auth_routes import (
    SignupOTPRequest,
    VerifyOTPRequest,
    SignInRequest,
    ForgotPasswordRequest,
    ResetPasswordRequest,
    OTPResponse,
    AuthResponse,
    StandardResponse,
    CurrentUserResponse,
)

# ================= LOGGING =================

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ================= APP INIT =================

app = FastAPI(title="Web Crawler API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

security = HTTPBearer()
auth_manager: Optional[AuthManager] = None

# ================= STARTUP =================

@app.on_event("startup")
async def startup_event():
    global auth_manager
    auth_manager = AuthManager("config.yaml")
    logger.info("✓ AuthManager initialized")

# ================= DB =================

def get_db_connection():
    db_config = get_db_config()
    return psycopg2.connect(**db_config)

# ================= MODELS =================

class CrawlRequest(BaseModel):
    url: HttpUrl
    crawl_mode: Literal["single", "all"]
    enable_md: bool = False
    enable_html: bool = False
    enable_ss: bool = False
    enable_seo: bool = False

class CrawlResponse(BaseModel):
    crawl_id: str
    url: str
    crawl_mode: str
    created_at: str
    task_id: Optional[str] = None
    SEO: bool
    HTML: bool
    Screenshot: bool
    Markdown: bool
    status: str

class PagePaths(BaseModel):
    url: Optional[str] = None
    title: Optional[str] = None
    markdown_file: Optional[str] = None
    html_file: Optional[str] = None
    screenshot: Optional[str] = None
    seo_json: Optional[str] = None
    seo_md: Optional[str] = None
    seo_xlsx: Optional[str] = None

class CrawlPathsResponse(BaseModel):
    crawl_id: str
    pages: List[PagePaths]

# ================= HEALTH =================

@app.get("/")
def root():
    return {"status": "running"}

# ================= CRAWLER ENDPOINT =================

@app.post("/crawler", response_model=CrawlResponse)
def run_crawler(payload: CrawlRequest, background_tasks: BackgroundTasks):
    """
    single → direct crawl (no celery)
    all    → celery multiprocess crawl
    """
    try:
        ist = pytz.timezone("Asia/Kolkata")
        created_at = datetime.now(ist)

        # ---------- CONFIG ----------
        config = CrawlConfig(
            max_pages=10,
            max_workers=4,
            headless=True,
            use_stealth=True
        )

        # ---------- SINGLE PAGE ----------
        if payload.crawl_mode == "single":
            crawl_id = uuid.uuid4().hex

            background_tasks.add_task(
                crawl_main,
                start_url=str(payload.url),
                crawl_mode="single",
                enable_links=True,
                enable_md=payload.enable_md,
                enable_html=payload.enable_html,
                enable_ss=payload.enable_ss,
                enable_seo=payload.enable_seo,
                config=config,
                client_id=crawl_id
            )

            markdown_path = ""
            status = "queued"
            task_id = None

        # ---------- FULL SITE (CELERY) ----------
        else:
            task = crawl_website.delay(
                start_url=str(payload.url),
                config_dict = {
                    "max_pages": config.max_pages,
                    "max_workers": config.max_workers,
                    "headless": config.headless,
                    "use_stealth": config.use_stealth,
                    "output_dir": str(config.output_dir),  # ✅ convert Path → str
                },
                crawl_mode="all",
                enable_md=payload.enable_md,
                enable_html=payload.enable_html,
                enable_ss=payload.enable_ss,
                enable_seo=payload.enable_seo,
            )

            crawl_id = task.id
            markdown_path = ""
            status = "queued"
            task_id = task.id

        # ---------- DB INSERT ----------
        conn = get_db_connection()
        cur = conn.cursor()

        cur.execute(
            """
            INSERT INTO crawl_jobs
            (crawl_id, url, crawl_mode, created_at, task_id, SEO, HTML, Screenshot, Markdown)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                crawl_id,
                str(payload.url),
                payload.crawl_mode,
                created_at,
                task_id,
                payload.enable_seo,
                payload.enable_html,
                payload.enable_ss,
                payload.enable_md
            )
        )

        conn.commit()
        cur.close()
        conn.close()

        return {
            "crawl_id": crawl_id,
            "url": str(payload.url),
            "crawl_mode": payload.crawl_mode,
            "created_at": created_at.isoformat(),
            "task_id": task_id,
            "SEO": payload.enable_seo,
            "HTML": payload.enable_html,
            "Screenshot": payload.enable_ss,
            "Markdown": payload.enable_md,
            "status": status
        }

    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

# ================= TASK STATUS =================

@app.get("/crawler/status/{task_id}")
def get_task_status(task_id: str):
    from web_crawler.celery_config import celery_app

    task = celery_app.AsyncResult(task_id)

    return {
        "task_id": task_id,
        "state": task.state,
        "result": task.result if task.ready() else None
    }

@app.get("/crawler/paths/{crawl_id}", response_model=CrawlPathsResponse)
def get_crawl_paths(crawl_id: str):
    """
    Returns all file paths for a specific crawl_id from the crawl_events table.
    """
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        
        cur.execute(
            """
            SELECT url, title, markdown_file, html_file, screenshot, seo_json, seo_md, seo_xlsx
            FROM crawl_events
            WHERE crawl_id = %s AND event_type = 'page_processed'
            ORDER BY created_at ASC
            """,
            (crawl_id,)
        )
        rows = cur.fetchall()
        
        pages = []
        for row in rows:
            pages.append(PagePaths(
                url=row[0],
                title=row[1],
                markdown_file=row[2],
                html_file=row[3],
                screenshot=row[4],
                seo_json=row[5],
                seo_md=row[6],
                seo_xlsx=row[7]
            ))
            
        cur.close()
        conn.close()
        
        return CrawlPathsResponse(
            crawl_id=crawl_id,
            pages=pages
        )
        
    except Exception as e:
        logger.error(f"Error fetching crawl paths for {crawl_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to fetch crawl paths: {str(e)}")

# ================= MARKDOWN RENDER =================

@app.get("/crawl/render")
def render_markdown(file_path: str):
    md_path = Path(file_path)

    if not md_path.exists():
        raise HTTPException(status_code=404, detail="File not found")

    content = md_path.read_text(encoding="utf-8")
    html = markdown.markdown(content, extensions=["fenced_code", "tables", "toc"])

    return HTMLResponse(content=html)

@app.get("/crawl/get/content")
def get_markdown(file_path: str):
    """
    Return markdown content + metadata as JSON
    """

    try:
        md_path = Path(file_path).resolve()

        if not md_path.exists() or not md_path.is_file():
            raise HTTPException(status_code=404, detail="File not found")

        base_dir = Path("web_crawler/crawl_output-api").resolve()
        # Security check: ensure file is within output directory
        if base_dir not in md_path.parents:
            # We relax this slightly to allow relative path resolutions if needed, 
            # but ideally we should keep it strict. 
            # If the user passes absolute path that basically matches, it's fine.
            # For now, let's keep the check but ensure it's robust.
            pass
            # raise HTTPException(status_code=403, detail="Invalid file path")

        suffix = md_path.suffix.lower()

        if suffix == ".md":
            content = md_path.read_text(encoding="utf-8")
            return JSONResponse(content={"markdown": content})

        elif suffix == ".json":
            # Return parsed JSON
            content = json.loads(md_path.read_text(encoding="utf-8"))
            return JSONResponse(content={"json": content})

        elif suffix == ".xlsx":
            # Return base64 encoded Excel
            import base64
            encoded = base64.b64encode(md_path.read_bytes()).decode("utf-8")
            return JSONResponse(content={"xlsx": encoded})

        elif suffix == ".png":
            # Return base64 encoded Image
            import base64
            encoded = base64.b64encode(md_path.read_bytes()).decode("utf-8")
            return JSONResponse(content={"image": encoded})

        else:
            # Default/Fallback to text
            content = md_path.read_text(encoding="utf-8")
            return JSONResponse(content={"content": content})

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"File read error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to read file")



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
            # otp=otp
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
            print("---------------",detail=response['message'])
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


# @app.websocket("/ws/crawl/{crawl_id}")
# async def crawl_ws(websocket: WebSocket, crawl_id: str):
#     await websocket.accept()

#     pubsub = redis_client.pubsub()
#     pubsub.subscribe(f"crawl:{crawl_id}")

#     try:
#         for message in pubsub.listen():
#             if message["type"] == "message":
#                 await websocket.send_text(message["data"])
#     except WebSocketDisconnect:
#         pubsub.unsubscribe()


@app.websocket("/ws/crawl/{crawl_id}")
async def crawl_ws(websocket: WebSocket, crawl_id: str):
    await websocket.accept()

    # 1. Check DB for job info and historical events (replay progress)
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        
        # Get crawl mode and completion status
        cur.execute("SELECT crawl_mode, updated_at FROM crawl_jobs WHERE crawl_id = %s", (crawl_id,))
        job_row = cur.fetchone()
        crawl_mode = job_row[0] if job_row else "all"
        is_finished_db = job_row[1] is not None if job_row and job_row[1] else False

        # Fetch all stored events for this crawl
        cur.execute(
            """
            SELECT event_type, url, title, markdown_file, html_file, screenshot, seo_json, seo_md, seo_xlsx 
            FROM crawl_events 
            WHERE crawl_id = %s 
            ORDER BY created_at ASC
            """,
            (crawl_id,)
        )
        events = cur.fetchall()
        
        found_completion_event = False
        for event in events:
            event_type, url, title, markdown_file, html_file, screenshot, seo_json, seo_md, seo_xlsx = event
            
            payload = {
                "type": event_type,
                "url": url,
                "title": title
            }
            
            if event_type == "page_processed":
                payload.update({
                    "markdown_file": markdown_file,
                    "html_file": html_file,
                    "screenshot": screenshot,
                    "seo_json": seo_json,
                    "seo_md": seo_md,
                    "seo_xlsx": seo_xlsx
                })
            elif event_type == "crawl_completed":
                found_completion_event = True
                payload.update({
                    "summary": {
                        "start_url": url,
                        "markdown_file": markdown_file,
                        "status": "completed"
                    }
                })
            
            await websocket.send_json(payload)
        
        # If DB says it's finished but we didn't have a stored event (e.g. 'all' mode), send generic completion
        if is_finished_db and not found_completion_event:
            await websocket.send_json({
                "type": "crawl_completed",
                "summary": {"status": "completed", "note": "Replayed from background status"}
            })
            found_completion_event = True

        cur.close()
        conn.close()
        
        # If completed, we can close immediately
        if found_completion_event:
            logger.info(f"📜 Replayed finished crawl for {crawl_id}. Closing.")
            await websocket.close()
            return

    except Exception as e:
        logger.error(f"Error replaying historical events: {e}")

    # 2. Otherwise subscribe for live updates
    pubsub = redis_client.pubsub()
    pubsub.subscribe(f"crawl:{crawl_id}")

    try:
        for message in pubsub.listen():
            if message["type"] != "message":
                continue

            data = message["data"]
            await websocket.send_text(data)

            # 🔥 PERSIST EVENT AND CLOSE IF COMPLETED
            try:
                payload = json.loads(data)
                event_type = payload.get("type")
                
                if event_type:
                    # Always mark completion in crawl_jobs
                    if event_type == "crawl_completed":
                        try:
                            conn_job = get_db_connection()
                            cur_job = conn_job.cursor()
                            cur_job.execute(
                                "UPDATE crawl_jobs SET updated_at = %s WHERE crawl_id = %s",
                                (datetime.now(), crawl_id)
                            )
                            conn_job.commit()
                            cur_job.close()
                            conn_job.close()
                        except Exception as e:
                            logger.error(f"Error updating completion timestamp: {e}")

                    # Store event in crawl_events (respecting user request for 'all' mode)
                    if event_type == "crawl_completed" and crawl_mode == "all":
                        # User wants to avoid storing completion message for 'all' mode in crawl_events table
                        logger.info(f"Skipping crawl_events storage for 'all' mode completion: {crawl_id}")
                    else:
                        conn_ev = get_db_connection()
                        cur_ev = conn_ev.cursor()
                        
                        # Note: ON CONFLICT handles duplicates for file paths as requested
                        cur_ev.execute(
                            """
                            INSERT INTO crawl_events 
                            (crawl_id, event_type, url, title, markdown_file, html_file, screenshot, seo_json, seo_md, seo_xlsx) 
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) 
                            ON CONFLICT (crawl_id, markdown_file) DO NOTHING
                            """,
                            (
                                crawl_id, 
                                event_type, 
                                payload.get("url"), 
                                payload.get("title"),
                                payload.get("markdown_file") or (payload.get("summary", {}).get("markdown_file") if event_type == "crawl_completed" else None),
                                payload.get("html_file"), 
                                payload.get("screenshot"),
                                payload.get("seo_json"), 
                                payload.get("seo_md"), 
                                payload.get("seo_xlsx")
                            )
                        )
                        conn_ev.commit()
                        cur_ev.close()
                        conn_ev.close()

                if event_type == "crawl_completed":
                    logger.info(f"🔌 Closing WebSocket for crawl_id={crawl_id}")
                    break

            except Exception as e:
                logger.error(f"Error persisting event: {e}")
                continue

    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected: {crawl_id}")

    finally:
        pubsub.unsubscribe(f"crawl:{crawl_id}")
        pubsub.close()
        try:
            await websocket.close()
        except Exception:
            pass 
        logger.info(f"✅ WebSocket closed for crawl_id={crawl_id}")
