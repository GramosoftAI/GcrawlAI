#!/usr/bin/env python3
import logging
import json
import uuid
import asyncio
import os
from typing import Dict, Any, Optional
from fastapi import APIRouter, HTTPException, Header, Request, status
from urllib.parse import urlparse

from api.models.gcrawl_payloads import ScrapeRequest
from api.core.database import get_db_connection
from api.core.config_setup import setup_crawl_config
from api.core.security import validate_recaptcha_or_jwt
from web_crawler.crawler.page.page_crawler3 import PageCrawler

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/auth-sites", tags=["Auth Sites Scraper"])

def format_cookies_for_playwright(cookies_data, target_domain: str) -> dict:
    if not cookies_data:
        return {"cookies": [], "origins": []}

    # Helper to clean individual cookie dictionaries
    def clean_cookie(cookie: dict) -> dict:
        c = dict(cookie)
        if "name" not in c or "value" not in c:
            return c
        
        # Ensure name and value are strings
        c["name"] = str(c["name"]).strip()
        c["value"] = str(c["value"]).strip()
        
        # Ensure path and secure flags are set
        c["path"] = c.get("path") or "/"
        c["secure"] = True  # Must be True for any __Secure- or __Host- prefix, and generally safe for HTTPS
        
        # Handle __Host- prefix constraint (must specify the exact domain without leading dot)
        if c["name"].startswith("__Host-"):
            domain_val = target_domain
            if domain_val.startswith("."):
                domain_val = domain_val[1:]
            c["domain"] = domain_val
        elif "domain" not in c or not c["domain"]:
            c["domain"] = target_domain if target_domain.startswith(".") else f".{target_domain}"
            
        return c

    # 1. Playwright storage_state format
    if isinstance(cookies_data, dict) and "cookies" in cookies_data and isinstance(cookies_data["cookies"], list):
        logger.info("[Auth Scraper] cookies_data is already in storage_state format. Cleaning fields.")
        cleaned_cookies = [clean_cookie(c) for c in cookies_data["cookies"] if isinstance(c, dict)]
        return {
            "cookies": cleaned_cookies,
            "origins": cookies_data.get("origins") or []
        }

    # 2. List of cookie dicts
    if isinstance(cookies_data, list):
        cleaned_cookies = [clean_cookie(c) for c in cookies_data if isinstance(c, dict)]
        return {"cookies": cleaned_cookies, "origins": []}

    # 3. Key-Value dictionary of cookies
    if isinstance(cookies_data, dict):
        playwright_cookies = []
        playwright_origins = []
        
        for name, value in cookies_data.items():
            if name == "localStorage":
                continue
            
            raw_cookie = {
                "name": name,
                "value": value
            }
            playwright_cookies.append(clean_cookie(raw_cookie))
            
        if "localStorage" in cookies_data and isinstance(cookies_data["localStorage"], dict):
            ls_dict = cookies_data["localStorage"]
            ls_entries = []
            for k, v in ls_dict.items():
                if not isinstance(v, str):
                    v = str(v)
                ls_entries.append({
                    "name": k,
                    "value": v
                })
            origin_url = f"https://www.{target_domain}" if not target_domain.startswith("www.") else f"https://{target_domain}"
            playwright_origins.append({
                "origin": origin_url,
                "localStorage": ls_entries
            })
            
        return {
            "cookies": playwright_cookies,
            "origins": playwright_origins
        }

    return {"cookies": [], "origins": []}


class AuthPageCrawler(PageCrawler):
    def __init__(self, config, cookies_to_inject, target_domain: str):
        super().__init__(config)
        self.cookies_to_inject = cookies_to_inject
        self.target_domain = target_domain

    def _load_session_state(self, client_id: str, url: str, context_kwargs: dict, browser_type: str = "cloak"):
        if self.cookies_to_inject:
            formatted_state = format_cookies_for_playwright(self.cookies_to_inject, self.target_domain)
            context_kwargs["storage_state"] = formatted_state
            logger.info("✓ [Auth Scraper] Formatted and injected database cookies into browser context storage_state.")
        else:
            logger.warning("[Auth Scraper] No cookies to inject.")

    def _save_session_state(self, client_id: str, url: str, context, result: dict, browser_type: str = "cloak"):
        # Do not save/update session state in Redis to keep the demo transient as requested
        pass

    def crawl_page(
        self,
        url: str,
        count: int,
        enable_md: bool,
        enable_html: bool,
        enable_ss: bool,
        enable_seo: bool,
        enable_images: bool,
        enable_json: bool,
        client_id: Optional[str],
        websocket_manager,
        crawl_mode: str = "all",
        proxy_type: str = "basic",
    ) -> Optional[Dict]:
        
        # Patch browser_manager.get_clock_browser to intercept context and page creation
        from web_crawler.crawler.page.page_crawler1 import browser_manager
        
        original_get_clock_browser = browser_manager.get_clock_browser
        
        def custom_get_clock_browser(*args_b, **kwargs_b):
            browser = original_get_clock_browser(*args_b, **kwargs_b)
            
            # Wrap browser.new_context if not already wrapped
            if not hasattr(browser, "_original_new_context"):
                browser._original_new_context = browser.new_context
                
                def custom_new_context(*args_c, **kwargs_c):
                    context = browser._original_new_context(*args_c, **kwargs_c)
                    original_new_page = context.new_page
                    
                    def custom_new_page(*args_p, **kwargs_p):
                        page = original_new_page(*args_p, **kwargs_p)
                        
                        original_goto = page.goto
                        original_evaluate = page.evaluate
                        original_content = page.content
                        original_screenshot = page.screenshot
                        
                        def custom_goto(*args_g, **kwargs_g):
                            try:
                                return original_goto(*args_g, **kwargs_g)
                            except Exception as e:
                                err_str = str(e).lower()
                                
                                # If cookies are invalid, a redirect loop occurs.
                                # Clear context cookies and retry the navigation cleanly!
                                if "redirect" in err_str or "too many" in err_str:
                                    logger.warning(f"[Auth Scraper] Redirect loop detected: {e}. Clearing cookies and retrying navigation cleanly.")
                                    try:
                                        context.clear_cookies()
                                    except Exception as clear_err:
                                        logger.warning(f"Failed to clear cookies: {clear_err}")
                                    try:
                                        return original_goto(*args_g, **kwargs_g)
                                    except Exception as retry_err:
                                        logger.error(f"Retry navigation after clearing cookies failed: {retry_err}")
                                        raise retry_err
                                
                                # Bypassing other navigation errors like timeouts
                                logger.warning(f"[Auth Scraper] Caught navigation exception in page.goto: {e}. Bypassing error to proceed with extraction.")
                                try:
                                    page.wait_for_load_state("domcontentloaded", timeout=3000)
                                except Exception:
                                    pass
                                try:
                                    page.wait_for_timeout(2000)
                                except Exception:
                                    pass
                                return None
                                
                        def custom_evaluate(*args_e, **kwargs_e):
                            try:
                                return original_evaluate(*args_e, **kwargs_e)
                            except Exception as e_eval:
                                if "destroyed" in str(e_eval).lower() or "navigation" in str(e_eval).lower():
                                    logger.warning(f"[Auth Scraper] page.evaluate failed: {e_eval}. Returning fallback value.")
                                    js_str = str(args_e[0]) if args_e else ""
                                    if "responseStatus" in js_str:
                                        return 200
                                    return ""
                                raise e_eval
                                
                        def custom_content(*args_c, **kwargs_c):
                            try:
                                return original_content(*args_c, **kwargs_c)
                            except Exception as e_cont:
                                if "destroyed" in str(e_cont).lower() or "navigation" in str(e_cont).lower():
                                    logger.warning(f"[Auth Scraper] page.content failed: {e_cont}. Retrying.")
                                    try:
                                        page.wait_for_timeout(2000)
                                        return original_content(*args_c, **kwargs_c)
                                    except Exception:
                                        return "<html><body>Navigation failed or redirect loop occurred.</body></html>"
                                raise e_cont
                                
                        def custom_screenshot(*args_s, **kwargs_s):
                            try:
                                return original_screenshot(*args_s, **kwargs_s)
                            except Exception as e_ss:
                                logger.warning(f"[Auth Scraper] page.screenshot failed: {e_ss}. Returning empty bytes.")
                                return b""
                        
                        page.goto = custom_goto
                        page.evaluate = custom_evaluate
                        page.content = custom_content
                        page.screenshot = custom_screenshot
                        return page
                        
                    context.new_page = custom_new_page
                    return context
                    
                browser.new_context = custom_new_context
            return browser
            
        browser_manager.get_clock_browser = custom_get_clock_browser
        
        try:
            # Execute standard multi-tier proxy crawl (Nodemaven -> Thordata -> Evomi Core)
            return super().crawl_page(
                url=url,
                count=count,
                enable_md=enable_md,
                enable_html=enable_html,
                enable_ss=enable_ss,
                enable_seo=enable_seo,
                enable_images=enable_images,
                enable_json=enable_json,
                client_id=client_id,
                websocket_manager=websocket_manager,
                crawl_mode=crawl_mode,
                proxy_type=proxy_type
            )
        finally:
            # Restore the original get_clock_browser method to avoid side-effects on subsequent requests
            browser_manager.get_clock_browser = original_get_clock_browser

def get_base_domain(url: str) -> str:
    url_str = str(url)
    if not url_str.startswith(("http://", "https://")):
        url_str = "https://" + url_str
    parsed = urlparse(url_str)
    hostname = parsed.hostname or ""
    if hostname.startswith("www."):
        return hostname[4:].lower()
    return hostname.lower()

@router.post("", response_model=Dict[str, Any])
async def run_auth_scrape(
    payload: ScrapeRequest,
    request: Request,
    authorization: Optional[str] = Header(None, description="Authorization: Bearer <token>"),
    recaptcha_token: Optional[str] = Header(None),
    x_api_key: Optional[str] = Header(None, alias="X-API-Key", description="API key for client access")
):
    """
    Run a scrape task on a page by injecting cookies from the user_cookies database table.
    The response is returned synchronously in the response body.
    """
    try:
        # Validate authentication
        user_id = validate_recaptcha_or_jwt(
            auth_header=authorization,
            recaptcha_header=recaptcha_token,
            api_key_header=x_api_key or request.headers.get("x-api-key") or request.headers.get("api_key") or request.headers.get("api-key") or request.headers.get("apikey")
        )
        
        start_url = str(payload.url)
        target_domain = get_base_domain(start_url)
        if not target_domain:
            raise HTTPException(status_code=400, detail="Invalid URL format.")

        # Query database for user's stored cookies
        cookies_to_inject = None
        conn = None
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT url, cookies_ls FROM user_cookies WHERE user_id = %s", (user_id,))
            rows = cursor.fetchall()
            cursor.close()
        except Exception as db_err:
            logger.error(f"Failed to fetch cookies from db: {db_err}", exc_info=True)
            raise HTTPException(status_code=500, detail="Failed to fetch user cookies from database.")
        finally:
            if conn:
                conn.close()

        # Find matching cookie by domain
        for db_url, cookies_ls in rows:
            db_domain = get_base_domain(db_url)
            if db_domain == target_domain or target_domain.endswith("." + db_domain) or db_domain.endswith("." + target_domain):
                if isinstance(cookies_ls, str):
                    cookies_to_inject = json.loads(cookies_ls)
                else:
                    cookies_to_inject = cookies_ls
                break

        if not cookies_to_inject:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"No cookies found for domain: '{target_domain}'. Please sync your cookies first."
            )

        # Setup crawler configuration
        # For a synchronous single-page scrape, we set concurrency_limit = 1
        config = setup_crawl_config(payload, default_max_pages=1, concurrency_limit=1)
        # Use model_dump_json if available, else json() for fallback compatibility
        if hasattr(payload, 'model_dump_json'):
            config.raw_payload = json.loads(payload.model_dump_json())
        else:
            config.raw_payload = json.loads(payload.json())
        
        enable_md = payload.markdown.enabled if payload.markdown else False
        enable_html = payload.html.enabled if payload.html else False
        enable_ss = payload.screenshot.enabled if payload.screenshot else False
        enable_seo = payload.seo.enabled if payload.seo else False
        enable_images = payload.images.enabled if payload.images else False

        if not any([enable_md, enable_html, enable_ss, enable_seo, enable_images]):
            raise HTTPException(
                status_code=400,
                detail="Please select at least one format (markdown, html, screenshot, seo, images)."
            )

        # Execute crawl using AuthPageCrawler in a separate worker thread to prevent blocking
        crawler = AuthPageCrawler(config, cookies_to_inject, target_domain)
        
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            None,
            lambda: crawler.crawl_page(
                url=start_url,
                count=1,
                enable_md=enable_md,
                enable_html=enable_html,
                enable_ss=enable_ss,
                enable_seo=enable_seo,
                enable_images=enable_images,
                enable_json=False,
                client_id="auth_sites_" + uuid.uuid4().hex,
                websocket_manager=None
            )
        )

        if not result:
            raise HTTPException(status_code=500, detail="Scrape failed without producing results.")

        if "error" in result:
            raise HTTPException(status_code=500, detail=f"Scrape error: {result['error']}")

        return {
            "success": True,
            "status_code": 200,
            "data": result
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in /auth-sites endpoint: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
