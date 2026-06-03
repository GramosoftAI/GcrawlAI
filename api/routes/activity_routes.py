from fastapi import APIRouter, HTTPException, Header, Request
from typing import Optional, List, Dict
import traceback
from datetime import datetime

from api.core.database import get_activity_logs
from api.core.security import validate_recaptcha_or_jwt

router = APIRouter(prefix="/activity_log", tags=["Activity Logs"])

@router.get("", response_model=List[Dict])
def fetch_activity_logs(
    request: Request,
    authorization: Optional[str] = Header(None, description="Authorization: Bearer <token>"),
    x_api_key: Optional[str] = Header(None, alias="X-API-Key", description="API key for client access"),
    days: int = 7,
    endpoint: Optional[str] = None
):
    try:
        user_id = validate_recaptcha_or_jwt(
            auth_header=authorization,
            recaptcha_header=None,
            api_key_header=x_api_key or request.headers.get("x-api-key") or request.headers.get("api_key") or request.headers.get("api-key") or request.headers.get("apikey")
        )
        if endpoint:
            endpoint = endpoint.upper()
            if not endpoint.startswith("/"):
                endpoint = f"/{endpoint}"
                
        logs = get_activity_logs(user_id, days=days, endpoint=endpoint)
        
        # Format the timestamp for the frontend
        formatted_logs = []
        for log in logs:
            if isinstance(log.get("created_at"), datetime):
                time_str = log["created_at"].strftime("%b %d, %y %I:%M %p")
            else:
                time_str = str(log.get("created_at"))
                
            formatted_logs.append({
                "JOB_ID": log.get("job_id", ""),
                "ENDPOINT": log.get("endpoint", ""),
                "URL": log.get("url", ""),
                "STATUS": log.get("status", ""),
                "TIME": time_str,
                "JSON_CONTENT": log.get("json_content")
            })
            
        return formatted_logs
        
    except HTTPException:
        raise
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))
