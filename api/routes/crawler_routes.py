import os

import uuid

import pytz

import logging

import traceback

import threading

from datetime import datetime

from typing import Optional

from concurrent.futures import ThreadPoolExecutor



from fastapi import APIRouter, HTTPException, Header, Request



from api.models.payloads import ScrapeRequest, MultiCrawlRequest, LinksRequest, ScreenshotRequest, CrawlResponse

from api.core.config_setup import setup_crawl_config

from api.core.database import get_pooled_connection, log_activity

from api.core.security import validate_recaptcha_or_jwt



from web_crawler.crawler.crawler import main as crawl_main

from web_crawler.common.config import CrawlConfig

from web_crawler.crawler.celery_tasks import crawl_website



logger = logging.getLogger(__name__)



router = APIRouter()



# Dedicated thread pool for single & links background crawls

GLOBAL_BROWSER_POOL = int(os.getenv("GLOBAL_BROWSER_POOL", 100))

def pre_warm_crawler_workers():

    from api.services.queue_manager import queue_manager

    for _ in range(GLOBAL_BROWSER_POOL):

        queue_manager.thread_pool.submit(_pre_warm_worker)



def _pre_warm_worker():

    """Initializes the browser pool inside an executor thread."""

    from web_crawler.crawler.page.page_crawler1 import browser_manager

    config = CrawlConfig(headless=True, use_stealth=True)

    logger.info(f"Pre-warming browser manager on thread {threading.get_ident()}...")

    try:

        browser_manager.get_clock_browser(config, direct=False)

        browser_manager.get_clock_browser(config, direct=True)

        logger.info(f"✓ Thread {threading.get_ident()} pre-warmed successfully!")

    except Exception as e:

        logger.warning(f"Failed to pre-warm thread {threading.get_ident()}: {e}")





async def keep_alive_browsers_loop():

    """Runs a background loop every 5 minutes to keep browser instances hot in RAM."""

    logger.info("Starting background keep-alive loop for pre-warmed browsers...")

    import asyncio

    while True:

        await asyncio.sleep(300)  # Sleep for 5 minutes (300 seconds)

        logger.info("Executing keep-alive ping for pre-warmed browsers...")

        from api.services.queue_manager import queue_manager

        try:

            # Submit keep-alive touch task to all worker threads

            for _ in range(GLOBAL_BROWSER_POOL):

                queue_manager.thread_pool.submit(_ping_browser_worker)

        except Exception as err:

            logger.warning(f"Error submitting keep-alive task: {err}")





def _ping_browser_worker():

    """Wakes up the thread-local browser instance by executing a tiny page action to touch RAM."""

    from web_crawler.crawler.page.page_crawler1 import browser_manager

    from web_crawler.common.config import CrawlConfig

    config = CrawlConfig(headless=True, use_stealth=True)

    try:

        # Resolve/ensure browser instances are open

        browser_nodirect = browser_manager.get_clock_browser(config, direct=False)

        browser_direct = browser_manager.get_clock_browser(config, direct=True)

        

        # Perform minor page operations to touch Chromium process memory and keep it active in RAM

        for browser in [browser_nodirect, browser_direct]:

            if browser and browser.is_connected():

                try:

                    page = browser.new_page()

                    page.goto("about:blank", timeout=5000)

                    page.close()

                except Exception as p_err:

                    logger.debug(f"Failed to touch browser page: {p_err}")

    except Exception as e:

        logger.debug(f"Failed to run keep-alive ping: {e}")



def _run_background_crawl_task(client_id: str, **kwargs):

    """Wrapper to run synchronous crawls (single, links) and persist their completion to DB."""

    summary = crawl_main(client_id=client_id, **kwargs)

    

    try:

        with get_pooled_connection() as conn:

            cur = conn.cursor()

            cur.execute(

                "UPDATE crawl_jobs SET updated_at = %s WHERE crawl_id = %s",

                (datetime.now(), client_id)

            )



            conn.commit()

            cur.close()

    except Exception as e:

        logger.error(f"Failed to persist BG crawl completion for {client_id}: {e}")



    try:

        from api.core.database import update_activity_log_time

        update_activity_log_time(client_id, summary.get("time_taken"))
        status = "FAILED" if summary.get("status") == "failed" else "COMPLETED"
        from api.core.database import update_activity_log_status
        update_activity_log_status(client_id, status)

    except Exception as e:

        logger.error(f"Failed to update activity log time for {client_id}: {e}")

        

    try:

        from web_crawler.common.redis_events import publish_event

        publish_event(

            crawl_id=client_id,

            payload={

                "type": "page_processed",

                "page": 1,

                "url": summary.get("start_url", ""),

                "title": summary.get("title", "Scraped Page"),

            }

        )

        

        publish_event(

            crawl_id=client_id,

            payload={

                "type": "crawl_completed",

                "summary": summary

            }

        )

    except Exception as e:

        logger.error(f"Failed to publish Redis event for BG crawl completion for {client_id}: {e}")

    return summary



@router.post("/scrape", response_model=CrawlResponse)

async def run_scrape(

    payload: ScrapeRequest,

    request: Request,

    authorization: Optional[str] = Header(None, description="Authorization: Bearer <token>"),

    recaptcha_token: Optional[str] = Header(None),

    x_api_key: Optional[str] = Header(None, alias="X-API-Key", description="API key for client access")

):

    try:

        if payload.screenshot and payload.screenshot.js_render:

            r = payload.screenshot

            if (r.render_timeout is None or 

                r.auto_scroll is None or 

                r.scroll_delay is None or 

                r.max_scrolls is None):

                raise HTTPException(

                    status_code=400,

                    detail="When js_render is True, rendering fields (render_timeout, auto_scroll, scroll_delay, max_scrolls) are required inside screenshot object."

                )



        user_id = validate_recaptcha_or_jwt(

            auth_header=authorization,

            recaptcha_header=recaptcha_token,

            api_key_header=x_api_key or request.headers.get("x-api-key") or request.headers.get("api_key") or request.headers.get("api-key") or request.headers.get("apikey")

        )

        

        from api.core.security import check_plan_limits_and_get_details, increment_used_requests, check_endpoint_active

        check_endpoint_active("Scrape API")

        plan_type, concurrency_limit = check_plan_limits_and_get_details(user_id)



        import socket

        from urllib.parse import urlparse

        

        parsed_url = urlparse(str(payload.url))

        hostname = parsed_url.hostname

        if hostname:

            try:

                socket.gethostbyname(hostname)

            except socket.gaierror:

                raise HTTPException(

                    status_code=400,

                    detail=f'DNS resolution failed for hostname "{hostname}". Please verify the URL is correct and the website exists.'

                )



        ist = pytz.timezone("Asia/Kolkata")

        created_at = datetime.now(ist)



        config = setup_crawl_config(payload, default_max_pages=10, concurrency_limit=concurrency_limit)
        import json
        config.raw_payload = json.loads(payload.json())



        enable_md = payload.markdown.enabled if payload.markdown else False

        enable_html = payload.html.enabled if payload.html else False

        enable_ss = payload.screenshot.enabled if payload.screenshot else False

        enable_seo = payload.seo.enabled if payload.seo else False

        enable_images = payload.images.enabled if payload.images else False



        if not any([enable_md, enable_html, enable_ss, enable_seo, enable_images]):

            raise HTTPException(

                status_code=400,

                detail="Please select at least one format"

            )



        crawl_id = uuid.uuid4().hex



        from api.services.queue_manager import queue_manager

        

        def _wrapper(**kw):

            _run_background_crawl_task(user_id=user_id, **kw)

            increment_used_requests(user_id, amount=1)



        await queue_manager.submit_background_task(

            user_id=user_id,

            plan_type=plan_type,

            user_limit=concurrency_limit,

            func=_wrapper,

            client_id=crawl_id,

            start_url=str(payload.url),

            crawl_mode="single",

            enable_links=True,

            enable_md=enable_md,

            enable_html=enable_html,

            enable_ss=enable_ss,

            enable_seo=enable_seo,

            enable_images=enable_images,

            config=config

        )



        with get_pooled_connection() as conn:

            cur = conn.cursor()

            cur.execute(

                """

                INSERT INTO crawl_jobs

                (crawl_id, url, crawl_mode, created_at, SEO, HTML, Screenshot, Markdown, Images, links, user_id)

                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)

                """,

                (

                    crawl_id,

                    str(payload.url),

                    "single",

                    created_at,

                    enable_seo,

                    enable_html,

                    enable_ss,

                    enable_md,

                    enable_images,

                    False, # enable_links false for single scrape explicitly

                    user_id

                )

            )

            conn.commit()

            cur.close()



        log_activity(user_id, "/SCRAPE", str(payload.url), "COMPLETED", job_id=crawl_id)

        return {

            "status_code": 200,

            "crawl_id": crawl_id,

            "polling_url": f"https://gcrawlai.com/gc/crawler/data/{crawl_id}",

            "url": str(payload.url),

            "crawl_mode": "single",

            "created_at": created_at.isoformat(),

            "task_id": None,

            "SEO": enable_seo,

            "HTML": enable_html,

            "Screenshot": enable_ss,

            "Markdown": enable_md,

            "Images": enable_images,

            "status": "queued",

            "user_id": user_id

        }



    except HTTPException:

        raise

    except Exception as e:

        traceback.print_exc()

        try:

            auth_key = x_api_key or request.headers.get("x-api-key") or request.headers.get("api_key") or request.headers.get("api-key") or request.headers.get("apikey")

            user_id = validate_recaptcha_or_jwt(

                auth_header=authorization,

                recaptcha_header=recaptcha_token,

                api_key_header=auth_key

            )

            log_activity(user_id, "/SCRAPE", str(payload.url), "FAILED", job_id=crawl_id if 'crawl_id' in locals() else None)

        except Exception:

            pass

        raise HTTPException(status_code=500, detail=str(e))



@router.post("/crawl", response_model=CrawlResponse)

async def run_crawl(

    payload: MultiCrawlRequest,

    request: Request,

    authorization: Optional[str] = Header(None, description="Authorization: Bearer <token>"),

    recaptcha_token: Optional[str] = Header(None),

    x_api_key: Optional[str] = Header(None, alias="X-API-Key", description="API key for client access")

):

    try:

        if payload.screenshot and payload.screenshot.js_render:

            r = payload.screenshot

            if (r.render_timeout is None or 

                r.auto_scroll is None or 

                r.scroll_delay is None or 

                r.max_scrolls is None):

                raise HTTPException(

                    status_code=400,

                    detail="When js_render is True, rendering fields (render_timeout, auto_scroll, scroll_delay, max_scrolls) are required inside screenshot object."

                )



        user_id = validate_recaptcha_or_jwt(

            auth_header=authorization,

            recaptcha_header=recaptcha_token,

            api_key_header=x_api_key or request.headers.get("x-api-key") or request.headers.get("api_key") or request.headers.get("api-key") or request.headers.get("apikey")

        )

        

        from api.core.security import check_plan_limits_and_get_details, increment_used_requests, check_endpoint_active

        check_endpoint_active("Crawl API")

        plan_type, concurrency_limit = check_plan_limits_and_get_details(user_id)



        import socket

        from urllib.parse import urlparse

        

        parsed_url = urlparse(str(payload.url))

        hostname = parsed_url.hostname

        if hostname:

            try:

                socket.gethostbyname(hostname)

            except socket.gaierror:

                raise HTTPException(

                    status_code=400,

                    detail=f'DNS resolution failed for hostname "{hostname}". Please verify the URL is correct and the website exists.'

                )



        ist = pytz.timezone("Asia/Kolkata")

        created_at = datetime.now(ist)



        config = setup_crawl_config(payload, default_max_pages=10, concurrency_limit=concurrency_limit)
        import json
        config.raw_payload = json.loads(payload.json())



        enable_md = payload.markdown.enabled if payload.markdown else False

        enable_html = payload.html.enabled if payload.html else False

        enable_ss = payload.screenshot.enabled if payload.screenshot else False

        enable_seo = payload.seo.enabled if payload.seo else False

        enable_images = payload.images.enabled if payload.images else False



        if not any([enable_md, enable_html, enable_ss, enable_seo, enable_images]):

            raise HTTPException(

                status_code=400,

                detail="Please select at least one format"

            )



        crawl_mode = "all"



        use_celery = os.getenv("USE_CELERY", "false").lower() == "true"

        if not use_celery:

            try:

                from web_crawler.crawler.celery_config import celery_app

                insp = celery_app.control.inspect(timeout=0.2)

                if insp and insp.ping():

                    use_celery = True

            except Exception:

                pass



        if use_celery:

            logger.info("✓ Active Celery worker detected. Offloading crawl task to Celery.")

            task = crawl_website.delay(

                start_url=str(payload.url),

                config_dict = {

                    "max_pages": config.max_pages,

                    "max_workers": config.max_workers,

                    "headless": config.headless,

                    "use_stealth": config.use_stealth,

                    "output_dir": str(config.output_dir),

                    "proxy": config.proxy,



                    "proxy_server": config.proxy_server,

                    "proxy_username": config.proxy_username,

                    "proxy_password": config.proxy_password,

                    "proxy_geo": config.proxy_geo,

                    "proxy_type_custom": config.proxy_type_custom,

                    "js_render": config.js_render,

                    "render_timeout": config.render_timeout,

                    "auto_scroll": config.auto_scroll,

                    "scroll_delay": config.scroll_delay,

                    "max_scrolls": config.max_scrolls,

                    "html_clean": config.html_clean,

                    "html_remove_external_links": config.html_remove_external_links,

                    "html_relative_to_absolute_links": config.html_relative_to_absolute_links,

                    "html_remove_data_images": config.html_remove_data_images,

                    "html_ignore_tags": config.html_ignore_tags,

                    "screenshot_full_page": config.screenshot_full_page,

                    "screenshot_format": config.screenshot_format,

                    "screenshot_quality": config.screenshot_quality,

                    "markdown_clean": config.markdown_clean,

                    "raw_payload": config.raw_payload
                },

                crawl_mode="all",

                enable_md=enable_md,

                enable_html=enable_html,

                enable_ss=enable_ss,

                enable_seo=enable_seo,

                enable_images=enable_images,

                user_id=user_id,

            )

            crawl_id = task.id

            status = "queued"

            task_id = task.id

        else:

            logger.info("⚠ No active Celery worker found. Running crawl task in local background thread pool.")

            crawl_id = uuid.uuid4().hex

            

            from api.services.queue_manager import queue_manager

            def _wrapper(**kw):

                summary = _run_background_crawl_task(user_id=user_id, **kw)
                pages = summary.get("pages_crawled", 1) if (summary and isinstance(summary, dict)) else 1
                increment_used_requests(user_id, amount=min(config.max_pages, pages))

                

            await queue_manager.submit_background_task(

                user_id=user_id,

                plan_type=plan_type,

                user_limit=concurrency_limit,

                func=_wrapper,

                client_id=crawl_id,

                start_url=str(payload.url),

                crawl_mode="all",

                enable_links=True,

                enable_md=enable_md,

                enable_html=enable_html,

                enable_ss=enable_ss,

                enable_seo=enable_seo,

                enable_images=enable_images,

                config=config

            )

            status = "queued"

            task_id = None





        with get_pooled_connection() as conn:

            cur = conn.cursor()

            cur.execute(

                """

                INSERT INTO crawl_jobs

                (crawl_id, url, crawl_mode, created_at, SEO, HTML, Screenshot, Markdown, Images, links, user_id)

                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)

                """,

                (

                    crawl_id,

                    str(payload.url),

                    "all",

                    created_at,

                    enable_seo,

                    enable_html,

                    enable_ss,

                    enable_md,

                    enable_images,

                    False,

                    user_id

                )

            )

            conn.commit()

            cur.close()



        log_activity(user_id, "/CRAWL", str(payload.url), "COMPLETED", job_id=crawl_id)



        return {

            "status_code": 200,

            "crawl_id": crawl_id,

            "polling_url": f"https://gcrawlai.com/gc/crawler/data/{crawl_id}",

            "url": str(payload.url),

            "crawl_mode": "all",

            "created_at": created_at.isoformat(),

            "SEO": enable_seo,

            "HTML": enable_html,

            "Screenshot": enable_ss,

            "Markdown": enable_md,

            "Images": enable_images,

            "status": status,

            "user_id": user_id

        }



    except HTTPException:

        raise

    except Exception as e:

        traceback.print_exc()

        try:

            auth_key = x_api_key or request.headers.get("x-api-key") or request.headers.get("api_key") or request.headers.get("api-key") or request.headers.get("apikey")

            user_id = validate_recaptcha_or_jwt(

                auth_header=authorization,

                recaptcha_header=recaptcha_token,

                api_key_header=auth_key

            )

            log_activity(user_id, "/CRAWL", str(payload.url), "FAILED", job_id=crawl_id if 'crawl_id' in locals() else None)

        except Exception:

            pass

        raise HTTPException(status_code=500, detail=str(e))



@router.post("/links", response_model=CrawlResponse)

async def run_links(

    payload: LinksRequest,

    request: Request,

    authorization: Optional[str] = Header(None, description="Authorization: Bearer <token>"),

    recaptcha_token: Optional[str] = Header(None),

    x_api_key: Optional[str] = Header(None, alias="X-API-Key", description="API key for client access")

):

    try:

        user_id = validate_recaptcha_or_jwt(

            auth_header=authorization,

            recaptcha_header=recaptcha_token,

            api_key_header=x_api_key or request.headers.get("x-api-key") or request.headers.get("api_key") or request.headers.get("api-key") or request.headers.get("apikey")

        )

        

        from api.core.security import check_plan_limits_and_get_details, increment_used_requests, check_endpoint_active

        check_endpoint_active("Links API")

        plan_type, concurrency_limit = check_plan_limits_and_get_details(user_id)



        import socket

        from urllib.parse import urlparse

        

        parsed_url = urlparse(str(payload.url))

        hostname = parsed_url.hostname

        if hostname:

            try:

                socket.gethostbyname(hostname)

            except socket.gaierror:

                raise HTTPException(

                    status_code=400,

                    detail=f'DNS resolution failed for hostname "{hostname}". Please verify the URL is correct and the website exists.'

                )



        ist = pytz.timezone("Asia/Kolkata")

        created_at = datetime.now(ist)



        limit_val = 100

        if payload.links and payload.links.limit is not None:

            limit_val = payload.links.limit



        config = CrawlConfig(
            max_pages=limit_val,
            max_workers=min(concurrency_limit, limit_val) if concurrency_limit else 4,
            headless=True,
            use_stealth=True
        )
        import json
        config.raw_payload = json.loads(payload.json())

        if payload.proxy:

            config.proxy_geo = payload.proxy.geo



        use_celery = os.getenv("USE_CELERY", "false").lower() == "true"

        if not use_celery:

            try:

                from web_crawler.crawler.celery_config import celery_app

                insp = celery_app.control.inspect(timeout=0.2)

                if insp and insp.ping():

                    use_celery = True

            except Exception:

                pass



        if use_celery:

            logger.info("✓ Active Celery worker detected. Offloading links task to Celery.")

            task = crawl_website.delay(

                start_url=str(payload.url),

                config_dict = {

                    "max_pages": config.max_pages,

                    "max_workers": config.max_workers,

                    "headless": config.headless,

                    "use_stealth": config.use_stealth,

                    "output_dir": str(config.output_dir),

                    "proxy": config.proxy,



                    "proxy_server": config.proxy_server,

                    "proxy_username": config.proxy_username,

                    "proxy_password": config.proxy_password,

                    "proxy_geo": config.proxy_geo,

                    "proxy_type_custom": config.proxy_type_custom,

                    "raw_payload": config.raw_payload
                },

                crawl_mode="links",

                enable_md=False,

                enable_html=False,

                enable_ss=False,

                enable_seo=False,

                enable_images=False,

                user_id=user_id,

            )

            crawl_id = task.id

            status = "queued"

        else:

            logger.info("⚠ No active Celery worker found. Running links task in local background thread pool.")

            crawl_id = uuid.uuid4().hex

            

            from api.services.queue_manager import queue_manager

            def _wrapper(**kw):

                _run_background_crawl_task(user_id=user_id, **kw)

                increment_used_requests(user_id, amount=1)

                

            await queue_manager.submit_background_task(

                user_id=user_id,

                plan_type=plan_type,

                user_limit=concurrency_limit,

                func=_wrapper,

                client_id=crawl_id,

                start_url=str(payload.url),

                crawl_mode="links",

                enable_links=True,

                enable_md=False,

                enable_html=False,

                enable_ss=False,

                enable_seo=False,

                enable_images=False,

                config=config

            )

            status = "queued"



        with get_pooled_connection() as conn:

            cur = conn.cursor()

            cur.execute(

                """

                INSERT INTO crawl_jobs

                (crawl_id, url, crawl_mode, created_at, SEO, HTML, Screenshot, Markdown, Images, links, user_id)

                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)

                """,

                (

                    crawl_id,

                    str(payload.url),

                    "links",

                    created_at,

                    False,

                    False,

                    False,

                    False,

                    False,

                    True, # links endpoint has links=True

                    user_id

                )

            )

            conn.commit()

            cur.close()



        log_activity(user_id, "/LINKS", str(payload.url), "COMPLETED", job_id=crawl_id)



        return {

            "status_code": 200,

            "crawl_id": crawl_id,

            "polling_url": f"https://gcrawlai.com/gc/crawler/data/{crawl_id}",

            "url": str(payload.url),

            "crawl_mode": "links",

            "created_at": created_at.isoformat(),

            "task_id": crawl_id,

            "SEO": False,

            "HTML": False,

            "Screenshot": False,

            "Markdown": False,

            "Images": False,

            "status": status,

            "user_id": user_id

        }



    except HTTPException:

        raise

    except Exception as e:

        traceback.print_exc()

        try:

            auth_key = x_api_key or request.headers.get("x-api-key") or request.headers.get("api_key") or request.headers.get("api-key") or request.headers.get("apikey")

            user_id = validate_recaptcha_or_jwt(

                auth_header=authorization,

                recaptcha_header=recaptcha_token,

                api_key_header=auth_key

            )

            log_activity(user_id, "/LINKS", str(payload.url), "FAILED", job_id=crawl_id if 'crawl_id' in locals() else None)

        except Exception:

            pass

        raise HTTPException(status_code=500, detail=str(e))



@router.post("/screenshot", response_model=CrawlResponse)

async def run_screenshot(

    payload: ScreenshotRequest,

    request: Request,

    authorization: Optional[str] = Header(None, description="Authorization: Bearer <token>"),

    recaptcha_token: Optional[str] = Header(None),

    x_api_key: Optional[str] = Header(None, alias="X-API-Key", description="API key for client access")

):

    try:

        if payload.screenshot and payload.screenshot.js_render:

            r = payload.screenshot

            if (r.render_timeout is None or 

                r.auto_scroll is None or 

                r.scroll_delay is None or 

                r.max_scrolls is None):

                raise HTTPException(

                    status_code=400,

                    detail="When js_render is True, rendering fields (render_timeout, auto_scroll, scroll_delay, max_scrolls) are required inside screenshot object."

                )



        user_id = validate_recaptcha_or_jwt(

            auth_header=authorization,

            recaptcha_header=recaptcha_token,

            api_key_header=x_api_key or request.headers.get("x-api-key") or request.headers.get("api_key") or request.headers.get("api-key") or request.headers.get("apikey")

        )

        

        from api.core.security import check_plan_limits_and_get_details, increment_used_requests, check_endpoint_active

        check_endpoint_active("Screenshot API")

        plan_type, concurrency_limit = check_plan_limits_and_get_details(user_id)



        import socket

        from urllib.parse import urlparse

        

        parsed_url = urlparse(str(payload.url))

        hostname = parsed_url.hostname

        if hostname:

            try:

                socket.gethostbyname(hostname)

            except socket.gaierror:

                raise HTTPException(

                    status_code=400,

                    detail=f'DNS resolution failed for hostname "{hostname}". Please verify the URL is correct and the website exists.'

                )



        ist = pytz.timezone("Asia/Kolkata")

        created_at = datetime.now(ist)



        config = setup_crawl_config(payload, default_max_pages=10, concurrency_limit=concurrency_limit)
        import json
        config.raw_payload = json.loads(payload.json())
        enable_md = False
        enable_html = False
        enable_ss = payload.screenshot.enabled if payload.screenshot else False
        enable_seo = False
        enable_images = False



        crawl_id = uuid.uuid4().hex



        from api.services.queue_manager import queue_manager

        

        def _wrapper(**kw):

            _run_background_crawl_task(user_id=user_id, **kw)

            increment_used_requests(user_id, amount=1)



        await queue_manager.submit_background_task(

            user_id=user_id,

            plan_type=plan_type,

            user_limit=concurrency_limit,

            func=_wrapper,

            client_id=crawl_id,

            start_url=str(payload.url),

            crawl_mode="screenshot",

            enable_links=True,

            enable_md=enable_md,

            enable_html=enable_html,

            enable_ss=enable_ss,

            enable_seo=enable_seo,

            enable_images=enable_images,

            config=config

        )



        with get_pooled_connection() as conn:

            cur = conn.cursor()

            cur.execute(

                """

                INSERT INTO crawl_jobs

                (crawl_id, url, crawl_mode, created_at, SEO, HTML, Screenshot, Markdown, Images, links, user_id)

                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)

                """,

                (

                    crawl_id,

                    str(payload.url),

                    "screenshot",

                    created_at,

                    enable_seo,

                    enable_html,

                    enable_ss,

                    enable_md,

                    enable_images,

                    False,

                    user_id

                )

            )

            conn.commit()

            cur.close()



        log_activity(user_id, "/SCREENSHOT", str(payload.url), "COMPLETED", job_id=crawl_id)



        return {

            "status_code": 200,

            "crawl_id": crawl_id,

            "polling_url": f"https://gcrawlai.com/gc/crawler/data/{crawl_id}",

            "url": str(payload.url),

            "crawl_mode": "single",

            "created_at": created_at.isoformat(),

            "task_id": None,

            "SEO": enable_seo,

            "HTML": enable_html,

            "Screenshot": enable_ss,

            "Markdown": enable_md,

            "Images": enable_images,

            "status": "queued",

            "user_id": user_id

        }



    except HTTPException:

        raise

    except Exception as e:

        traceback.print_exc()

        try:

            auth_key = x_api_key or request.headers.get("x-api-key") or request.headers.get("api_key") or request.headers.get("api-key") or request.headers.get("apikey")

            user_id = validate_recaptcha_or_jwt(

                auth_header=authorization,

                recaptcha_header=recaptcha_token,

                api_key_header=auth_key

            )

            log_activity(user_id, "/SCREENSHOT", str(payload.url), "FAILED", job_id=crawl_id if 'crawl_id' in locals() else None)

        except Exception:

            pass

        raise HTTPException(status_code=500, detail=str(e))
