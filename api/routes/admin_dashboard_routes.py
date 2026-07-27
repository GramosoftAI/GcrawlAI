#!/usr/bin/env python3
"""
Admin Dashboard Statistics Routes
Provides stats and health cards.
"""
import logging
from fastapi import APIRouter, HTTPException, Depends
from api.core.database import get_db_connection
from api.routes.admin_users_routes import verify_admin_user
from api.models.payloads import (
    AdminDashboardStatsResponse,
    DashboardStatCard
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/admin", tags=["Admin User Management"])

def format_calls_count(count: int) -> str:
    """Format total calls count into human-readable notation (e.g. 1.2M, 800K, 0)"""
    if count >= 1_000_000:
        return f"{count / 1_000_000:.1f}M".replace(".0M", "M")
    elif count >= 1_000:
        return f"{count / 1_000:.0f}K"
    return str(count)

@router.get("/stats", response_model=AdminDashboardStatsResponse)
async def get_admin_dashboard_stats(
    _: bool = Depends(verify_admin_user)
):
    """
    Retrieve global platform overview statistics for the Admin Dashboard.
    """
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # 1. Query Total Users and Weekly Change
        cursor.execute("SELECT COUNT(*) FROM users")
        total_users = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM users WHERE created_at >= NOW() - INTERVAL '7 days'")
        weekly_users = cursor.fetchone()[0]
        
        # 2. Query Active Jobs (Crawl & Search tasks count)
        cursor.execute("SELECT COUNT(*) FROM crawl_jobs")
        crawl_jobs_count = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM search_jobs")
        search_jobs_count = cursor.fetchone()[0]
        
        total_jobs = crawl_jobs_count + search_jobs_count
        
        # 3. Query Total API Calls from activity_logs
        cursor.execute("SELECT COUNT(*) FROM activity_logs")
        total_api_calls = cursor.fetchone()[0]
        
        # 4. Query System Health dynamically from api_endpoints status
        cursor.execute("SELECT COUNT(*), SUM(CASE WHEN is_active = TRUE THEN 1 ELSE 0 END) FROM api_endpoints")
        health_row = cursor.fetchone()
        
        total_endpoints = health_row[0] or 0
        active_endpoints = health_row[1] or 0
        
        cursor.close()
        
        # System Health percentage calculation logic
        if total_endpoints == 0:
            health_str = "100%"
            health_sublabel = "All systems operational"
        else:
            ratio = active_endpoints / total_endpoints
            if ratio == 1.0:
                health_str = "99.9%"
                health_sublabel = "All systems operational"
            else:
                health_str = f"{ratio * 100:.1f}%"
                down_count = total_endpoints - active_endpoints
                health_sublabel = f"{down_count} API Endpoint(s) under maintenance"
                
        return AdminDashboardStatsResponse(
            success=True,
            total_users=DashboardStatCard(
                value=f"{total_users:,}",
                change=f"+{weekly_users} this week"
            ),
            active_endpoints=DashboardStatCard(
                value=f"{total_jobs:,}",
                sublabel="Live scraping jobs"
            ),
            total_api_calls=DashboardStatCard(
                value=format_calls_count(total_api_calls),
                sublabel="Current billing cycle"
            ),
            system_health=DashboardStatCard(
                value=health_str,
                sublabel=health_sublabel
            )
        )
    except Exception as e:
        logger.error(f"Error fetching admin dashboard statistics: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to fetch dashboard statistics: {str(e)}")
    finally:
        if conn:
            conn.close()
