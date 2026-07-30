#!/usr/bin/env python3
"""
Admin Routes Hub
Aggregates split admin routes.
"""
from fastapi import APIRouter
from api.routes.admin_dashboard_routes import router as dashboard_router
from api.routes.admin_plans_routes import router as plans_router
from api.routes.admin_endpoints_routes import router as endpoints_router
from api.routes.admin_users_routes import router as users_router
from api.routes.admin_error_logs_routes import router as error_logs_router
from api.routes.admin_email_routes import router as email_router
from api.routes.admin_overall_logs_routes import router as overall_logs_router

router = APIRouter()
router.include_router(dashboard_router)
router.include_router(plans_router)
router.include_router(endpoints_router)
router.include_router(users_router)
router.include_router(error_logs_router)
router.include_router(email_router)
router.include_router(overall_logs_router)
