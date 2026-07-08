import logging
import random
import time
from typing import Optional, Dict
from playwright.sync_api import Page
from web_crawler.common.config import CrawlConfig
from web_crawler.crawler.page.page_crawler1 import browser_manager

logger = logging.getLogger(__name__)

class CloakCrawlerMixin:
    """Mixin for CloakBrowser crawling engine."""
    
    def crawl_with_cloakbrowser(
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
        provider: str = "nodemaven",
        use_high_speed: bool = True
    ) -> Optional[Dict]:
        """Crawl page using CloakBrowser (Pooled)"""
        context = None
        page = None
        try:
            proxy_settings = self._resolve_playwright_proxy(target_url=url, provider=provider, use_high_speed=use_high_speed)
            browser = browser_manager.get_clock_browser(self.config, direct=(proxy_settings is None))
            
            # Align viewport size to the launched browser screen size to avoid empty spaces
            local_data = browser_manager._get_local_data()
            v_width = getattr(local_data, "width", 1920)
            v_height = getattr(local_data, "height", 1080)
            
            context_kwargs = dict(
                viewport={"width": v_width, "height": v_height},
                java_script_enabled=True,
                ignore_https_errors=True
            )
            if proxy_settings:
                context_kwargs["proxy"] = proxy_settings

            # Let CloakBrowser handle User-Agent dynamically based on its stealth initialization

            # Note: We do not load old session states for high-security targets to prevent carrying over block flags
            is_high_sec = any(domain in url.lower() for domain in ["meesho", "ajio", "evomi"])
            if not is_high_sec:
                self._load_session_state(client_id, url, context_kwargs, browser_type="cloak")

            # Setup context using CloakBrowser
            context = browser.new_context(**context_kwargs)
            logger.info(f"CloakBrowser context initialized successfully")

            page = context.new_page()
            
            # Block heavy tracking/analytics scripts and heavy media to speed up loads and prevent timeouts
            def block_useless_resources(route):
                req_type = route.request.resource_type
                req_url = route.request.url.lower()
                trackers = {
                    "google-analytics.com", "googletagmanager.com", "doubleclick.net",
                    "facebook.net", "facebook.com/tr", "hotjar.com", "tiktok.com",
                    "analytics", "pixel", "pagead", "adnxs", "optimizely", "clarity.ms",
                    "mixpanel.com", "amplitude.com"
                }
                
                # Check for tracker keywords in request URL
                if any(t in req_url for t in trackers):
                    return route.abort()
                
                # Always block heavy media files
                if req_type == "media":
                    return route.abort()
                
                # If screenshot is disabled, block images (unless enable_images is True)
                if not enable_ss:
                    if req_type == "image" and not enable_images:
                        logger.debug(f"[Asset Blocker] Aborting load of image: {req_url[:120]}")
                        return route.abort()
                
                route.continue_()

            page.route("**/*", block_useless_resources)
            
            # Timeout logic: Evomi Premium/Core (15s), Nodemaven/Direct (12s)
            attempt_timeout = 15 if "evomi" in provider else 12
            if self.config.render_timeout is not None:
                nav_timeout = self.config.render_timeout
            else:
                nav_timeout = attempt_timeout * 1000

            try:
                logger.info(f"Navigating to target URL: {url} (CloakBrowser, timeout={nav_timeout/1000}s)")
                wait_mode = "load"
                
                response = None
                try:
                    response = page.goto(url, wait_until=wait_mode, timeout=nav_timeout)
                except Exception as e:
                    try:
                        content = page.content()
                    except Exception:
                        content = ""
                    
                    if "timeout" in str(e).lower() and len(content) > 10000:
                        logger.info(f"CloakBrowser page.goto timed out, but content is partially present ({len(content)} bytes). Proceeding with data extraction.")
                        response = None
                    else:
                        raise e
                
                logger.info(f"Navigation completed. Status: {response.status if response else 'No Response (Proceeded on timeout)'}")
                
                status_code = response.status if response else (page.evaluate("() => { try { return window.performance.getEntries()[0].responseStatus; } catch { return 200; } }") or 200)
                
                if self.is_captcha_page(page):
                    logger.debug("CAPTCHA/Challenge detected early. Waiting for stealth bypass...")
                    for _ in range(10):
                        page.wait_for_timeout(1000)
                        if not self.is_captcha_page(page):
                            logger.debug("CAPTCHA/Challenge bypassed successfully!")
                            try:
                                page.wait_for_load_state("load", timeout=5000)
                                page.wait_for_timeout(2000)
                            except:
                                pass
                            break
                    else:
                        logger.debug("CAPTCHA/Challenge could not be bypassed on this attempt (CloakBrowser).")
                        return {"url": url, "error": "CAPTCHA detected", "status_code": 403}

                if not self.config.js_render:
                    if enable_ss:
                        try:
                            page.wait_for_load_state("networkidle", timeout=3000)
                        except Exception:
                            pass
                        
                    result = self.process_page(page, url, count, enable_md, enable_html, enable_ss, enable_seo, enable_images, enable_json, client_id, status_code=status_code)
                    self._save_session_state(client_id, url, context, result, browser_type="cloak")
                    return result

                try:
                    page.wait_for_selector("body", state="visible", timeout=5000)
                except Exception as wait_err:
                    logger.warning(f"Error during initial wait: {wait_err}")
                
                if self.is_captcha_page(page):
                    logger.debug("CAPTCHA/Challenge detected after initial load wait. Waiting for stealth bypass...")
                    for _ in range(10):
                        page.wait_for_timeout(1000)
                        if not self.is_captcha_page(page):
                            logger.debug("CAPTCHA/Challenge bypassed successfully!")
                            try:
                                page.wait_for_load_state("load", timeout=5000)
                                page.wait_for_timeout(2000)
                            except:
                                pass
                            break
                    else:
                        logger.debug("CAPTCHA/Challenge could not be bypassed on this attempt (CloakBrowser).")
                        return {"url": url, "error": "CAPTCHA detected", "status_code": 403}

                status_code = response.status if response else 0
                title = page.title()
                
                if status_code in [401, 407, 502, 503, 504]:
                    logger.warning(f"Bailing out due to status {status_code}.")
                    return {"url": url, "error": f"Block/Auth error: {status_code}", "status_code": status_code}

                if not title and status_code == 200:
                    title = page.title()

                if self.config.js_render:
                    logger.info("[Stealth Layer] JS Rendering: Stabilizing dynamic DOM elements and triggering lazy-loaded assets before extraction.")
                    if self.config.auto_scroll:
                        logger.info(f"Performing custom auto-scroll: delay={self.config.scroll_delay}ms, max_scrolls={self.config.max_scrolls}")
                        try:
                            page.evaluate(
                                """
                                async (args) => {
                                    const { delay, maxScrolls } = args;
                                    let currentY = 0;
                                    let stepCount = 0;

                                    // Slow constant scroll speed: 600 pixels per second (extremely readable/slow)
                                    const scrollSpeed = 600; 
                                    const subStepDelay = 40; // 40ms interval (25 FPS smooth rendering)

                                    while (stepCount < maxScrolls) {
                                        const clientHeight = window.innerHeight;
                                        const scrollHeight = document.documentElement.scrollHeight || document.body.scrollHeight;
                                        const maxScrollPos = scrollHeight - clientHeight;

                                        if (maxScrollPos <= 0) {
                                            break;
                                        }

                                        const remainingSteps = maxScrolls - stepCount;
                                        const targetY = Math.min(currentY + (maxScrollPos - currentY) / remainingSteps, maxScrollPos);
                                        const startY = currentY;
                                        const distance = targetY - startY;

                                        // Slowly slide down from startY to targetY at 600px/second
                                        if (distance > 0) {
                                            const animDuration = (distance / scrollSpeed) * 1000; // in milliseconds
                                            const subSteps = Math.max(1, Math.floor(animDuration / subStepDelay));
                                            for (let i = 1; i <= subSteps; i++) {
                                                const intermediateY = startY + (distance * (i / subSteps));
                                                window.scrollTo({ top: Math.floor(intermediateY), behavior: 'auto' });
                                                await new Promise(r => setTimeout(r, subStepDelay));
                                            }
                                        } else {
                                            window.scrollTo({ top: targetY, behavior: 'auto' });
                                        }

                                        currentY = targetY;
                                        stepCount++;
                                        
                                        // Wait the full scroll_delay (e.g. 1500ms) at the target position to let content stabilize
                                        await new Promise(r => setTimeout(r, delay));
                                    }
                                    
                                    // A final clean scroll to absolute bottom (using native smooth scroll to finish slowly)
                                    const finalScrollHeight = document.documentElement.scrollHeight || document.body.scrollHeight;
                                    const finalMax = finalScrollHeight - window.innerHeight;
                                    if (finalMax > 0 && window.scrollY < finalMax) {
                                        window.scrollTo({ top: finalMax, behavior: 'smooth' });
                                        await new Promise(r => setTimeout(r, 800));
                                    }
                                }
                                """,
                                {"delay": self.config.scroll_delay, "maxScrolls": self.config.max_scrolls}
                            )
                        except Exception as scroll_err:
                            logger.warning(f"Custom scroll failed: {scroll_err}")
                            if "Execution context was destroyed" in str(scroll_err) or "Target closed" in str(scroll_err):
                                logger.info("[Stealth Layer] Challenge successfully bypassed! Redirecting to the real webpage...")
                                try:
                                    page.wait_for_load_state("domcontentloaded", timeout=15000)
                                    page.wait_for_timeout(2000)
                                except Exception as load_err:
                                    logger.warning(f"Timeout waiting for post-challenge page to load: {load_err}")
                    else:
                         logger.info("Auto-scroll skipped.")
                
                if self.is_captcha_page(page): 
                    return {"url": url, "error": "CAPTCHA detected", "status_code": 403}
                    
                result = self.process_page(page, url, count, enable_md, enable_html, enable_ss, enable_seo, enable_images, enable_json, client_id, status_code=status_code)
                self._save_session_state(client_id, url, context, result, browser_type="cloak")
                return result
            finally:
                try:
                    if page: page.close()
                    if context: context.close()
                except:
                    pass
        except Exception as e:
            err_msg = str(e).lower()
            logger.warning(f"CloakBrowser failed for {url}: {e}")
            if "err_http2_protocol_error" in err_msg or "protocol" in err_msg or "http2" in err_msg or "aborted" in err_msg or "connection closed" in err_msg:
                logger.info(f"[Stealth Layer] Critical HTTP/2 Protocol Error. Recycling browser instance...")
                try:
                    browser_manager.close_clock_browser(direct=(proxy_settings is None))
                except Exception as close_err:
                    logger.error(f"Failed to close browser during recycling: {close_err}")
                    
            return None
