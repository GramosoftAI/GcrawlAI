from fastapi import APIRouter, HTTPException, Header, Request
from typing import Optional, List, Dict
import traceback
from datetime import datetime

from api.core.database import get_activity_logs, get_usage_summary, get_user_remaining_credits
from api.core.security import validate_recaptcha_or_jwt

router = APIRouter(prefix="/activity_log", tags=["Activity Logs"])

@router.get("", response_model=List[Dict])
def fetch_activity_logs(
    request: Request,
    authorization: Optional[str] = Header(None, description="Authorization: Bearer <token>"),
    x_api_key: Optional[str] = Header(None, alias="X-API-Key", description="API key for client access"),
    days: int = 7,
    endpoint: Optional[str] = None,
    page: int = 1,
    limit: int = 20
):
    """Fetch and return activity logs with pagination."""
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
                
        logs = get_activity_logs(user_id, days=days, endpoint=endpoint, page=page, limit=limit)
        
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
                "TIME_TAKEN": log.get("time_taken", ""),
                "JSON_CONTENT": log.get("json_content")
            })
            
        return formatted_logs
        
    except HTTPException:
        raise
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/summary")
def fetch_activity_summary(
    request: Request,
    authorization: Optional[str] = Header(None, description="Authorization: Bearer <token>"),
    range_type: str = "7",
    start_date: Optional[str] = None,
    end_date: Optional[str] = None
):
    """Fetch and return activity summary."""
    import datetime
    try:
        user_id = validate_recaptcha_or_jwt(
            auth_header=authorization,
            recaptcha_header=None,
            api_key_header=None
        )
        
        today = datetime.date.today()
        
        if range_type == "1":
            start_dt = today
            end_dt = today
        elif range_type == "7":
            start_dt = today - datetime.timedelta(days=6)
            end_dt = today
        elif range_type == "30":
            start_dt = today - datetime.timedelta(days=29)
            end_dt = today
        elif range_type == "custom":
            if not start_date or not end_date:
                raise HTTPException(status_code=400, detail="start_date and end_date are required for custom range")
            try:
                start_dt = datetime.datetime.strptime(start_date, "%Y-%m-%d").date()
                end_dt = datetime.datetime.strptime(end_date, "%Y-%m-%d").date()
            except ValueError:
                raise HTTPException(status_code=400, detail="Invalid date format. Expected YYYY-MM-DD")
        else:
            # Default to 7 days
            start_dt = today - datetime.timedelta(days=6)
            end_dt = today

        if start_dt > end_dt:
            start_dt, end_dt = end_dt, start_dt
            
        delta = end_dt - start_dt
        if delta.days > 365:
            raise HTTPException(status_code=400, detail="Date range cannot exceed 365 days")

        # Generate continuous list of dates
        date_map = {}
        for i in range(delta.days + 1):
            curr_date = start_dt + datetime.timedelta(days=i)
            date_str = curr_date.strftime("%Y-%m-%d")
            date_map[date_str] = {
                "date": date_str,
                "scrape_count": 0,
                "crawl_count": 0,
                "scearch_count": 0,
                "screenshot_count": 0,
                "links_count": 0,
                "extractors_count": 0,
                "total_count": 0
            }

        # Query database usage counts
        db_summary = get_usage_summary(user_id, start_dt, end_dt)
        for entry in db_summary:
            d_str = entry.get("date")
            if d_str in date_map:
                date_map[d_str].update({
                    "scrape_count": entry.get("scrape_count", 0),
                    "crawl_count": entry.get("crawl_count", 0),
                    "scearch_count": entry.get("search_count", 0),
                    "screenshot_count": entry.get("screenshot_count", 0),
                    "links_count": entry.get("links_count", 0),
                    "extractors_count": entry.get("extractors_count", 0),
                    "total_count": entry.get("total_count", 0)
                })

        # Query remaining credits
        remaining_credits = get_user_remaining_credits(user_id)

        # Format output list sorted by date
        usage_list = list(date_map.values())
        usage_list.sort(key=lambda x: x["date"])

        return {
            "remaining_credits": remaining_credits,
            "usage": usage_list
        }
    except HTTPException:
        raise
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))
