import sys

import asyncio

import logging

import traceback

from pathlib import Path

from typing import Optional



if sys.platform == 'win32':

    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())



from fastapi import FastAPI, HTTPException

from fastapi.middleware.cors import CORSMiddleware

from fastapi.responses import JSONResponse

from fastapi.encoders import jsonable_encoder

from fastapi.exceptions import RequestValidationError

from starlette.exceptions import HTTPException as StarletteHTTPException



from api.auth.auth_manager import AuthManager

from api.core.database import _init_db_pool, get_db_config, get_pooled_connection, _db_pool

from api.core.security import set_auth_manager

from api.services.queue_manager import queue_manager



from api.routes.crawler_routes import router as crawler_router, pre_warm_crawler_workers, keep_alive_browsers_loop

from api.routes.task_routes import router as task_router

from api.routes.auth_routes import router as auth_router

from api.routes.ws_routes import router as ws_router

from api.routes.report_routes import router as report_router



from api.routes.contact_routes import router as contact_router

from api.routes.search_routes import router as search_router

from api.routes.api_key_routes import router as api_key_router

from api.routes.activity_routes import router as activity_router

from api.routes.payment_routes import router as payment_router

from api.routes.admin_routes import router as admin_router





# ================= LOGGING =================

_LOG_FORMAT = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'

_LOG_FILE = Path(__file__).parent.parent / 'output.log'



_file_handler = logging.FileHandler(str(_LOG_FILE), mode='a', encoding='utf-8')

_file_handler.setLevel(logging.DEBUG)

_file_handler.setFormatter(logging.Formatter(_LOG_FORMAT))



_console_handler = logging.StreamHandler(sys.stdout)

_console_handler.setLevel(logging.INFO)

_console_handler.setFormatter(logging.Formatter(_LOG_FORMAT))



_root_logger = logging.getLogger()

_root_logger.setLevel(logging.DEBUG)

_root_logger.handlers.clear()

_root_logger.addHandler(_file_handler)

_root_logger.addHandler(_console_handler)



logging.basicConfig(

    level=logging.DEBUG,

    format=_LOG_FORMAT,

    handlers=[_file_handler, _console_handler],

    force=True

)



logger = logging.getLogger(__name__)

logger.info("=" * 80)

logger.info(f"🚀 API Server Starting - Logging to {_LOG_FILE}")

logger.info("=" * 80)



def _configure_root_logger():

    root = logging.getLogger()

    for handler in root.handlers[:]:

        root.removeHandler(handler)

    root.addHandler(_file_handler)

    root.addHandler(_console_handler)

    

    for module_name in ['web_crawler.search.google_search', 'web_crawler.search.search_engine', 'web_crawler']:

        mod_logger = logging.getLogger(module_name)

        mod_logger.propagate = True

        mod_logger.setLevel(logging.DEBUG)



# ================= APP INIT =================



app = FastAPI(title="Web Crawler API")



app.add_middleware(

    CORSMiddleware,

    allow_origins=["*"],

    allow_credentials=True,

    allow_methods=["*"],

    allow_headers=["*"],

)



# ── Routers ──

app.include_router(auth_router)

app.include_router(crawler_router, prefix="/api/v1", tags=["Crawler"])

app.include_router(task_router, prefix="/crawler", tags=["Tasks"])

# Backwards compatibility for crawls/user

app.include_router(task_router, prefix="/crawls", tags=["Tasks"])

app.include_router(ws_router, tags=["WebSocket"])

app.include_router(report_router, tags=["Report Issue"])



app.include_router(contact_router)

app.include_router(search_router, prefix="/api/v1")

app.include_router(api_key_router)

app.include_router(activity_router, prefix="/api/v1")

app.include_router(payment_router, prefix="/api/v1")

app.include_router(admin_router, prefix="/api/v1")





@app.exception_handler(StarletteHTTPException)

async def http_exception_handler(request, exc):

    return JSONResponse(

        status_code=exc.status_code,

        content=jsonable_encoder({

            "status_code": exc.status_code,

            "status": "error",

            "message": str(exc.detail) if hasattr(exc, "detail") else str(exc)

        }),

    )



@app.exception_handler(RequestValidationError)

async def validation_exception_handler(request, exc):

    return JSONResponse(

        status_code=422,

        content=jsonable_encoder({

            "status_code": 422,

            "status": "error",

            "message": "Validation Error",

            "detail": exc.errors()

        }),

    )



@app.get("/")

def root():

    return {"status": "running"}



# ================= STARTUP =================

@app.on_event("startup")

async def startup_event():

    logger.info("Starting up FastAPI application...")

    _init_db_pool()

    

    try:

        from api.core.db_setup import DatabaseSetup

        db_setup = DatabaseSetup()

        db_setup.create_job_results_table()

        db_setup.create_api_endpoints_table()

        db_setup.create_subscription_plans_table()

        logger.info("✓ job_results, api_endpoints and subscription_plans tables validated/created on startup")

    except Exception as db_setup_err:

        logger.error(f"Failed to check/create database tables on startup: {db_setup_err}")

        

    am = AuthManager()

    set_auth_manager(am)

    

    # Start Global Priority Queue Workers (90 limits)

    queue_manager.start_workers()

    

    # Start the Proactor Thread (Windows support) & Pool for the crawler

    from web_crawler.search.google_search import _get_or_start_proactor_thread

    _get_or_start_proactor_thread()



    # We need to import the global pool to pass to AuthManager if needed

    import api.core.database as core_db

    

    auth_manager = AuthManager("config.yaml", db_pool=core_db._db_pool)

    set_auth_manager(auth_manager)

    logger.info("✓ AuthManager initialized")



    logger.info("Pre-warming background crawler threads...")

    pre_warm_crawler_workers()



@app.on_event("shutdown")

async def shutdown_event():

    queue_manager.stop_workers()



# Reload trigger comment to refresh module cache - triggered

