"""
Browser crawling engines, screenshot capturing, and multi-tier orchestration.
"""

import logging
import random
import time
from typing import Optional, Dict
from playwright.sync_api import Page

from web_crawler.common.config import CrawlConfig
from web_crawler.crawler.file_manager import FileManager
from web_crawler.common.redis_events import publish_event
from web_crawler.crawler.page_crawler2 import BasePageCrawler

from web_crawler.crawler.page_crawler1 import (
    _record_crawl_error,
    browser_manager
)

logger = logging.getLogger(__name__)


class PageCrawler(BasePageCrawler):
    """Handle page crawling using standard Chromium and fallback Camoufox engines"""

    def crawl_with_chromium(
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
        proxy_tier: int = 2
    ) -> Optional[Dict]:
        """Crawl page using Chromium with stealth (Pooled)"""
        context = None
        page = None
        try:
            session_id = "".join(random.choices("0123456789abcdef", k=8))
            proxy_settings = self._resolve_playwright_proxy(proxy_tier, session_id=session_id, target_url=url)
            browser = browser_manager.get_chromium(self.config, direct=(proxy_tier == 1))
            
            is_japan = "jal.co.jp" in url.lower() or ".jp" in url.lower()
            is_india = "meesho" in url.lower() or "dinamalar" in url.lower() or ".in" in url.lower()
            
            if proxy_tier == 1:
                target_tz = "Asia/Kolkata"
                target_locale = "en-US"
                target_geo = {"latitude": 19.0760, "longitude": 72.8777}
            else:
                if is_japan:
                    target_tz = "Asia/Tokyo"
                    target_locale = "ja-JP"
                    target_geo = {"latitude": 35.6762, "longitude": 139.6503}
                elif is_india:
                    target_tz = "Asia/Kolkata"
                    target_locale = "en-IN"
                    target_geo = {"latitude": 19.0760, "longitude": 72.8777}
                else:
                    target_tz = "America/New_York"
                    target_locale = "en-US"
                    target_geo = {"latitude": 40.7128, "longitude": -74.0060}

            context_kwargs = dict(
                viewport={"width": 1920, "height": 1080},
                locale=target_locale,
                timezone_id=target_tz,
                geolocation=target_geo,
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36',
                java_script_enabled=True,
                ignore_https_errors=True,
                bypass_csp=True,
                extra_http_headers={
                    "sec-ch-ua": '"Not(A:Brand";v="99", "Google Chrome";v="133", "Chromium";v="133"',
                    "sec-ch-ua-mobile": "?0",
                    "sec-ch-ua-platform": '"Windows"'
                }
            )
            if proxy_settings:
                context_kwargs["proxy"] = proxy_settings

            nav_timeout = self.config.render_timeout if self.config.render_timeout is not None else (90_000 if proxy_tier > 1 else 60_000)
            if "google.com/search" in url and proxy_tier > 1:
                mobile_ua = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Mobile/15E148 Safari/604.1"
                context_kwargs["user_agent"] = mobile_ua
                context_kwargs["viewport"] = {"width": 390, "height": 844}
                context_kwargs["is_mobile"] = True
                context_kwargs["has_touch"] = True

            context = browser.new_context(**context_kwargs)
            
            logger.info(f"Chromium browser (windows) initialized successfully with evasion flags")
            logger.info(f"[Stealth Layer] Engine initialization: Hardened TLS fingerprinting and browser fingerprint evasion active.")
            logger.info(f"[Stealth Layer] Browser Fingerprinting: Platform=Desktop, Viewport={context_kwargs['viewport']['width']}x{context_kwargs['viewport']['height']}, Locale={context_kwargs['locale']}")
            logger.info(f"[Stealth Layer] Network Identity: Applying organic Chrome headers and Referer spoofing.")

            high_sec_sites = [
                "meesho", "delta.com", "jal.co.jp", "united.com", "wayfair.com", 
                "zillow.com", "amazon", "google.com", "myaccount.google.com", 
                "gcrawlai.com", "luisaviaroma.com", "oracle.com", "usps.com", 
                "nike.com", "adidas.com", "homedepot.com", "southwest.com",
                "expedia.com", "neimanmarcus.com", "nordstrom.com", "skyscanner",
                "lowes.com", "rakuten.com", "footlocker.com", "att.com", "booking.com",
                "chewy.com", "autozone.com", "comcast.com", "indeed.com", "gartner.com"
            ]
            extreme_high_sec = ["expedia.com", "zillow.com", "wayfair.com", "oracle.com", "gartner.com"]
            mobile_target_sites = [
                "expedia.com", "luisaviaroma.com", "oracle.com", "chewy.com",
                "autozone.com", "indeed.com", "zillow.com", "wayfair.com", "nordstrom.com", "jal.co.jp"
            ]
            is_high_sec = any(s in url.lower() for s in high_sec_sites)
            is_extreme = any(s in url.lower() for s in extreme_high_sec)
            
            use_mobile = any(site in url.lower() for site in mobile_target_sites) and proxy_tier >= 3
            if is_extreme: use_mobile = False
            is_skyscanner = "skyscanner" in url.lower()

            custom_headers = {
                "Sec-Fetch-Site": "cross-site",
                "Sec-Fetch-Mode": "navigate",
                "Sec-Fetch-Dest": "document"
            }
            
            if is_high_sec:
                domain_name = next((s for s in high_sec_sites if s in url.lower()), "site")
                query_name = domain_name.split('.')[0]
                custom_headers["Referer"] = f"https://www.google.com/search?q={query_name}+official+store&oq={query_name}"
                if is_skyscanner:
                    custom_headers["Referer"] = "https://www.google.com/"
            else:
                custom_headers["Referer"] = "https://www.google.com/"

            context.set_extra_http_headers(custom_headers)
            
            page = context.new_page()
            
            # OPTIMIZATION: Block heavy network resources (ads, analytics, fonts, CSS/images if visuals off)
            has_visuals = enable_ss or enable_images
            page.route("**/*", self.browser_utils.make_resource_blocker(block_images=not has_visuals, block_css=not has_visuals))
            
            self._move_human(page, random.randint(300, 800), random.randint(300, 600))
            
            self.browser_utils.inject_stealth_scripts(page)
            
            extra_high_sec = ["expedia", "axs", "southwest", "skyscanner", "neimanmarcus"]
            if any(s in url.lower() for s in extra_high_sec):
                is_high_sec = True
            
            if is_high_sec:
                domain_name = next((s for s in high_sec_sites if s in url.lower()), "site")
                referer = f"https://www.google.com/search?q={domain_name}+official+store&oq={domain_name}"
                if "skyscanner" in url.lower():
                    referer = "https://www.google.com/"
            
            if is_high_sec and not is_japan and "gartner.com" not in url.lower():
                from urllib.parse import urlparse
                parsed = urlparse(url)
                warmup_url = f"{parsed.scheme}://{parsed.netloc}/"
                
                if warmup_url.rstrip("/") != url.rstrip("/"):
                    logger.info(f"Domain Warmup (Cookie Seeding) for: {warmup_url}")
                    try:
                        page.goto(warmup_url, wait_until="load", timeout=40000)
                        
                        for _ in range(2):
                            page.wait_for_timeout(random.randint(500, 1500))
                            self._move_human(page, random.randint(100, 1000), random.randint(100, 800))
                        
                        cookies = context.cookies()
                        abck = [c for c in cookies if c['name'] == '_abck']
                        logger.info(f"[Stealth Layer] Identity Token Seeding: _abck={'FOUND' if abck else 'MISSING'}")
                        
                        if not abck:
                            logger.warning("Cookie still missing, extra 3s settlement...")
                            page.wait_for_timeout(3000)
                    except Exception as e:
                        logger.debug(f"Domain warmup failed (proceeding): {e}")
                else:
                    logger.info(f"Skipping domain warmup because target URL is the root domain: {url}")
            
            try:
                logger.info(f"Navigating to target URL: {url} (Chromium)")
                is_skyscanner = "skyscanner" in url.lower()
                
                # OPTIMIZATION: Always use 'commit' wait state to return status 200 instantly without waiting for heavy media/ads
                has_visuals = enable_ss or enable_images
                wait_mode = "commit"
                
                try:
                    response = page.goto(url, wait_until=wait_mode, timeout=nav_timeout)
                except Exception as e:
                    err_msg = str(e).lower()
                    if "err_empty_response" in err_msg or "reset" in err_msg or "interrupted" in err_msg or "aborted" in err_msg:
                        logger.warning(f"Chromium network error for {url}. Waiting 5s and retrying with 'commit'...")
                        page.wait_for_timeout(5000)
                        try:
                            response = page.goto(url, wait_until="commit", timeout=nav_timeout + 10000)
                        except Exception as retry_e:
                            if "aborted" in str(retry_e).lower():
                                logger.warning(f"Chromium request aborted by target (possible bot block).")
                                return {"url": url, "error": "Connection Aborted (Bot Block)", "status_code": 403}
                            raise retry_e
                    else:
                        raise e
                
                logger.info(f"Navigation completed. Status: {response.status if response else 'No Response'}")
                
                if not response: return {"url": url, "error": "No response", "status_code": 0}
                
                status_code = response.status if response else 0

                # Wait up to 10 seconds for CAPTCHA/Challenge to be resolved by stealth engine
                if self.is_captcha_page(page):
                    logger.debug("CAPTCHA/Challenge detected immediately (Chromium). Waiting for stealth bypass...")
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
                        logger.debug("CAPTCHA/Challenge could not be bypassed on this tier (Chromium).")
                        return {"url": url, "error": "CAPTCHA detected", "status_code": 403}

                if not self.config.js_render:
                    if has_visuals:
                        try:
                            # User explicitly disabled JS rendering but requested a screenshot/image.
                            # Give the framework (e.g. React) a few seconds to hydrate the UI so it isn't completely white.
                            page.wait_for_load_state("load", timeout=10000)
                            page.wait_for_timeout(3000)
                        except:
                            pass
                    return self.process_page(page, url, count, enable_md, enable_html, enable_ss, enable_seo, enable_images, enable_json, client_id, status_code=status_code)

                try:
                    # OPTIMIZATION: Short stabilization if no visuals are needed
                    if has_visuals:
                        stab_timeout = 15000 if is_high_sec else 5000
                        page.wait_for_load_state("load", timeout=stab_timeout)
                        page.wait_for_selector("body", state="visible", timeout=5000)
                        if is_high_sec:
                            page.wait_for_timeout(5000)
                    else:
                        # Wait for dynamic React hydration to execute and populate body content
                        if is_high_sec:
                            page.wait_for_load_state("load", timeout=15000)
                            page.wait_for_timeout(5000)
                        else:
                            page.wait_for_timeout(2000)
                except:
                    pass
                
                status_code = response.status if response else 0
                title = page.title()
                
                if status_code in [401, 407, 502, 503, 504]:
                    logger.warning(f"Bailing out due to status {status_code} before behavioral simulation.")
                    return {"url": url, "error": f"Block/Auth error: {status_code}", "status_code": status_code}

                if (not title and status_code == 200) or is_skyscanner or is_high_sec:
                    title = page.title()

                if is_high_sec or is_skyscanner:
                    logger.info(f"[Stealth Layer] JavaScript Challenges: Executing fast behavioral signals.")
                    try:
                        sim_start = time.time()
                        for _ in range(2): 
                            if time.time() - sim_start > 2: break
                            self._move_human(page, random.randint(200, 1000), random.randint(200, 800))
                        logger.info("Human activity simulation completed")
                    except Exception as sim_err:
                        logger.debug(f"Behavioral simulation interrupted: {sim_err}")

                if enable_ss or enable_images:
                    logger.info("[Stealth Layer] JS Rendering: Stabilizing dynamic DOM elements and triggering lazy-loaded assets before extraction.")
                    if self.config.auto_scroll:
                        logger.info(f"Performing custom auto-scroll: delay={self.config.scroll_delay}ms, max_scrolls={self.config.max_scrolls}")
                        try:
                            page.evaluate(
                                """
                                async (args) => {
                                    const { delay, maxScrolls } = args;
                                    const getTallestScrollable = () => {
                                        const elements = document.querySelectorAll('*');
                                        let tallest = document.scrollingElement || document.documentElement;
                                        let maxH = tallest.scrollHeight;
                                        
                                        for (const el of elements) {
                                            const h = el.scrollHeight;
                                            if (h > maxH && getComputedStyle(el).overflowY !== 'hidden') {
                                                maxH = h;
                                                tallest = el;
                                            }
                                        }
                                        return tallest;
                                    };

                                    const scrollTarget = getTallestScrollable();
                                    const step = 500;
                                    for (let i = 0; i < maxScrolls; i++) {
                                        if (scrollTarget === window || scrollTarget === document.documentElement || scrollTarget === document.body) {
                                            window.scrollBy({ top: step, behavior: 'auto' });
                                        } else {
                                            scrollTarget.scrollBy({ top: step, behavior: 'auto' });
                                        }
                                        await new Promise(r => setTimeout(r, delay));
                                    }
                                }
                                """,
                                {"delay": self.config.scroll_delay, "maxScrolls": self.config.max_scrolls}
                            )
                        except Exception as scroll_err:
                            logger.warning(f"Custom scroll failed: {scroll_err}")
                    else:
                         logger.info("Auto-scroll is disabled, skipping scrolling.")
                    
                    if not self.browser_utils.wait_for_ready(page): 
                        logger.warning(f"Page stabilization timed out for {url}, proceeding anyway.")
                
                if self.is_captcha_page(page): 
                    return {"url": url, "error": "CAPTCHA detected", "status_code": 403}
                    
                return self.process_page(page, url, count, enable_md, enable_html, enable_ss, enable_seo, enable_images, enable_json, client_id, status_code=status_code)
            finally:
                try:
                    if page: page.close()
                    if context: context.close()
                except:
                    pass
        except Exception as e:
            logger.warning(f"Chromium failed for {url}: {e}")
            return None

    def crawl_with_camoufox(
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
        proxy_tier: int = 2
    ) -> Optional[Dict]:
        """Fallback crawl using Camoufox (Pooled)"""
        context = None
        page = None
        try:
            session_id = "".join(random.choices("0123456789abcdef", k=8))
            proxy_settings = self._resolve_playwright_proxy(proxy_tier, session_id=session_id, target_url=url)
            browser = browser_manager.get_camoufox(self.config)
            
            high_sec_sites = [
                "meesho", "delta.com", "jal.co.jp", "united.com", "wayfair.com", 
                "zillow.com", "amazon", "google.com", "myaccount.google.com", 
                "gcrawlai.com", "luisaviaroma.com", "oracle.com", "usps.com", 
                "nike.com", "adidas.com", "homedepot.com", "southwest.com",
                "expedia.com", "neimanmarcus.com", "nordstrom.com", "skyscanner",
                "lowes.com", "rakuten.com", "footlocker.com", "att.com", "booking.com",
                "chewy.com", "autozone.com", "comcast.com", "indeed.com", "gartner.com"
            ]
            extreme_high_sec = ["expedia.com", "zillow.com", "wayfair.com", "oracle.com", "gartner.com"]
            mobile_target_sites = [
                "expedia.com", "luisaviaroma.com", "oracle.com", "chewy.com",
                "autozone.com", "indeed.com", "zillow.com", "wayfair.com", "nordstrom.com", "jal.co.jp"
            ]
            is_high_sec = any(site in url.lower() for site in high_sec_sites)
            is_extreme = any(site in url.lower() for site in extreme_high_sec)
            
            use_mobile = any(site in url.lower() for site in mobile_target_sites) and proxy_tier >= 3
            if is_extreme: use_mobile = False

            is_japan = "jal.co.jp" in url.lower() or ".jp" in url.lower()
            is_india = "meesho" in url.lower() or "dinamalar" in url.lower() or ".in" in url.lower()
            
            if proxy_tier == 1:
                target_tz = "Asia/Kolkata"
                target_locale = "en-US"
                target_geo = {"latitude": 19.0760, "longitude": 72.8777}
            else:
                if is_japan:
                    target_tz = "Asia/Tokyo"
                    target_locale = "ja-JP"
                    target_geo = {"latitude": 35.6762, "longitude": 139.6503}
                elif is_india:
                    target_tz = "Asia/Kolkata"
                    target_locale = "en-IN"
                    target_geo = {"latitude": 19.0760, "longitude": 72.8777}
                else:
                    target_tz = "America/New_York"
                    target_locale = "en-US"
                    target_geo = {"latitude": 40.7128, "longitude": -74.0060}

            context_kwargs = dict(
                viewport={"width": 1920, "height": 1080} if not use_mobile else {"width": 390, "height": 844},
                locale=target_locale,
                permissions=["geolocation", "notifications"], java_script_enabled=True,
                ignore_https_errors=True, bypass_csp=True, color_scheme="light"
            )
            if proxy_settings: context_kwargs["proxy"] = proxy_settings
            if use_mobile: context_kwargs["user_agent"] = "Mozilla/5.0 (iPhone; CPU iPhone OS 15_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/15.0 Mobile/15E148 Safari/604.1"

            logger.info(f"Camoufox browser (windows) initialized successfully with evasion flags")
            logger.info(f"[Stealth Layer] Engine initialization: Hardened TLS fingerprinting and browser fingerprint evasion active.")
            logger.info(f"[Stealth Layer] Browser Fingerprinting: Platform=Desktop, Viewport={context_kwargs['viewport']['width']}x{context_kwargs['viewport']['height']}, Locale={context_kwargs['locale']}")
            logger.info(f"[Stealth Layer] Network Identity: Applying deep referer spoofing and Sec-Fetch headers to mimic organic traffic.")
            
            context = browser.new_context(**context_kwargs)
            from urllib.parse import urlparse
            
            extra_high_sec = ["expedia", "axs", "southwest", "skyscanner", "neimanmarcus"]
            if any(s in url.lower() for s in extra_high_sec):
                is_high_sec = True
            is_skyscanner = "skyscanner" in url.lower()

            custom_headers = {}
            if is_high_sec:
                domain_name = next((s for s in high_sec_sites if s in url.lower()), "site")
                query_name = domain_name.split('.')[0] 
                custom_headers["Referer"] = f"https://www.google.com/search?q={query_name}+official+store&oq={query_name}"
                if is_skyscanner:
                    custom_headers["Referer"] = "https://www.google.com/"
            else:
                custom_headers["Referer"] = "https://www.google.com/"
            
            context.set_extra_http_headers(custom_headers)
            
            page = context.new_page()
            
            # OPTIMIZATION: Block heavy network resources (ads, analytics, fonts, CSS/images if visuals off)
            has_visuals = enable_ss or enable_images
            page.route("**/*", self.browser_utils.make_resource_blocker(block_images=not has_visuals, block_css=not has_visuals))
            
            self.browser_utils.inject_stealth_scripts(page)
            self._move_human(page, random.randint(300, 800), random.randint(300, 600))
            
            if is_high_sec and not is_japan:
                parsed = urlparse(url)
                warmup_url = f"{parsed.scheme}://{parsed.netloc}/"
                
                if warmup_url.rstrip("/") != url.rstrip("/"):
                    logger.info(f"Domain Warmup (Cookie Seeding) for: {warmup_url}")
                    try:
                        page.goto(warmup_url, wait_until="domcontentloaded", timeout=15000)
                    except Exception as e:
                        logger.debug(f"Domain warmup failed (proceeding): {e}")
                else:
                    logger.info(f"Skipping domain warmup because target URL is the root domain: {url}")

            # OPTIMIZATION: Always use 'domcontentloaded' wait state to return status 200 instantly without waiting for heavy media/ads
            wait_mode = "domcontentloaded"
            
            render_timeout = self.config.render_timeout if self.config.render_timeout is not None else 60000
            try:
                response = page.goto(url, wait_until=wait_mode, timeout=render_timeout)
            except Exception as e:
                if "NS_ERROR_NET_INTERRUPT" in str(e) or "interrupted" in str(e).lower():
                    if proxy_tier > 1:
                        logger.warning(f"Network interruption detected for {url}. Creating FRESH context and retrying with Mobile identity...")
                        try:
                            if page: page.close()
                            if context: context.close()
                            
                            retry_kwargs = context_kwargs.copy()
                            retry_kwargs["user_agent"] = "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1"
                            retry_kwargs["viewport"] = {"width": 390, "height": 844}
                            
                            context = browser.new_context(**retry_kwargs)
                            page = context.new_page()
                            self.browser_utils.inject_stealth_scripts(page)
                            
                            page.wait_for_timeout(3000)
                            response = page.goto(url, wait_until="domcontentloaded", timeout=render_timeout + 10000)
                        except Exception as retry_e:
                            logger.error(f"Fresh context retry failed: {retry_e}")
                            raise e
                    else:
                        raise e
                else:
                    raise e
                    
            status_code = response.status if response else 0
            logger.info(f"Navigation completed. Status: {status_code}")
 
            if self.is_cert_error_page(page):
                logger.warning("Browser certificate/network error page detected.")
                return {"url": url, "error": "SSL/HSTS Certificate Block", "status_code": 403}
 
            # Wait up to 10 seconds for CAPTCHA/Challenge to be resolved by stealth engine
            if self.is_captcha_page(page):
                logger.debug("CAPTCHA/Challenge detected immediately (Camoufox). Waiting for stealth bypass...")
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
                    logger.debug("CAPTCHA/Challenge could not be bypassed on this tier (Camoufox).")
                    return {"url": url, "error": "CAPTCHA detected", "status_code": 403}

            if not self.config.js_render:
                if has_visuals:
                    try:
                        page.wait_for_selector("body", state="visible", timeout=3000)
                        page.wait_for_timeout(500)
                    except:
                        pass
                return self.process_page(page, url, count, enable_md, enable_html, enable_ss, enable_seo, enable_images, enable_json, client_id, status_code=status_code)
            try:
                page.wait_for_selector("body", state="visible", timeout=5000)
                if has_visuals:
                    if is_high_sec:
                        page.wait_for_timeout(1000)
                    else:
                        page.wait_for_timeout(200)
                else:
                    if is_high_sec:
                        page.wait_for_timeout(500)
            except:
                pass

            status_code = response.status if response else 0
            title = page.title()

            if status_code in [401, 407, 502, 503, 504]:
                logger.warning(f"Bailing out due to status {status_code} before behavioral simulation.")
                return {"url": url, "error": f"Block/Auth error: {status_code}", "status_code": status_code}

            is_skyscanner = "skyscanner" in url.lower()
            if (not title and status_code == 200) or is_skyscanner or is_high_sec:
                title = page.title()
            
            if (response and response.status in [403, 429]):
                logger.info(f"[Stealth Layer] JavaScript Challenges: Executing fast behavioral signals.")
                try:
                    sim_start = time.time()
                    for _ in range(2):
                        if time.time() - sim_start > 2: break
                        self._move_human(page, random.randint(200, 1000), random.randint(200, 800))
                    logger.info("Human activity simulation completed")
                except Exception as sim_err:
                    logger.debug(f"Behavioral simulation interrupted: {sim_err}")

            if self.config.js_render:
                logger.info("[Stealth Layer] JS Rendering: Stabilizing dynamic DOM elements and triggering lazy-loaded assets before extraction.")
                if self.config.auto_scroll:
                    logger.info(f"Performing custom auto-scroll: delay={self.config.scroll_delay}ms, max_scrolls={self.config.max_scrolls}")
                    try:
                        page.evaluate(
                            """
                            async (args) => {
                                const { delay, maxScrolls } = args;
                                const getTallestScrollable = () => {
                                    const elements = document.querySelectorAll('*');
                                    let tallest = document.scrollingElement || document.documentElement;
                                    let maxH = tallest.scrollHeight;
                                    
                                    for (const el of elements) {
                                        const h = el.scrollHeight;
                                        if (h > maxH && getComputedStyle(el).overflowY !== 'hidden') {
                                            maxH = h;
                                            tallest = el;
                                        }
                                    }
                                    return tallest;
                                };

                                const scrollTarget = getTallestScrollable();
                                const totalHeight = scrollTarget.scrollHeight || document.body.scrollHeight || 3000;
                                const step = Math.ceil(totalHeight / maxScrolls);
                                for (let i = 0; i < maxScrolls; i++) {
                                    if (scrollTarget === window || scrollTarget === document.documentElement || scrollTarget === document.body) {
                                        window.scrollBy({ top: step, behavior: 'auto' });
                                    } else {
                                        scrollTarget.scrollBy({ top: step, behavior: 'auto' });
                                    }
                                    await new Promise(r => setTimeout(r, delay));
                                }
                            }
                            """,
                            {"delay": self.config.scroll_delay, "maxScrolls": self.config.max_scrolls}
                        )
                    except Exception as scroll_err:
                        logger.warning(f"Custom scroll failed: {scroll_err}")
                else:
                    logger.info("Auto-scroll is disabled, skipping scrolling.")
            
            if self.is_captcha_page(page):
                return {"url": url, "error": "CAPTCHA detected", "status_code": 403}
                
            if self.is_cert_error_page(page):
                logger.warning("Browser certificate/network error page detected after stabilization.")
                return {"url": url, "error": "SSL/HSTS Certificate Block", "status_code": 403}
                
            result = self.process_page(page, url, count, enable_md, enable_html, enable_ss, enable_seo, enable_images, enable_json, client_id, status_code=status_code)
            return result
        except Exception as e:
            err_msg = str(e)
            if "NS_ERROR_NET_INTERRUPT" in err_msg or "connection was closed" in err_msg.lower():
                logger.warning(f"Network interruption detected for {url} (Akamai block). Escalating...")
                return {"url": url, "error": "Network Interruption", "status_code": 403}
            
            logger.error(f"Camoufox failed: {e}")
            return None
        finally:
            try:
                if page: page.close()
                if context: context.close()
            except:
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
        """Crawl a single page with fallback browsers"""
        logger.info(f"Crawling [{count}]: {url}")
        
        if client_id:
            publish_event(
                crawl_id=client_id,
                payload={
                    "type": "progress",
                    "status": "starting",
                    "url": url,
                    "count": count
                }
            )

        custom_proxy_type = (self.config.proxy_type_custom or "").strip().lower()
        
        if custom_proxy_type == "residential":
            start_tier = 2
            end_tier = 3
        elif custom_proxy_type == "datacenter":
            start_tier = 4
            end_tier = 7
        elif custom_proxy_type == "both":
            start_tier = 1
            end_tier = 7
        else:
            requested_proxy_type = (proxy_type or "auto").strip().lower()
            if requested_proxy_type == "none":
                start_tier = 1
            elif requested_proxy_type == "auto":
                start_tier = self.config.default_tier
            else:
                if requested_proxy_type == "mobile":
                    start_tier = 2
                elif requested_proxy_type == "bright_data":
                    start_tier = 3
                elif requested_proxy_type == "basic":
                    start_tier = 4
                elif requested_proxy_type == "stealth":
                    start_tier = 6
                elif requested_proxy_type == "enhanced":
                    start_tier = 7
                else:
                    start_tier = 1
            end_tier = 7
            
        current_tier = start_tier
        result = None

        while current_tier <= end_tier:
            logger.info("\n" + "="*30 + f"\nTier {current_tier} - Processing\n" + "="*30)
            
            result = self.crawl_with_camoufox(
                url, count, enable_md, enable_html, enable_ss, enable_seo, enable_images, enable_json, client_id, current_tier
            )
            browser_name = "Camoufox"
            
            # FALLBACK: If Camoufox fails (e.g. HSTS block), try Chromium on the same tier before escalating
            if not result or "error" in result:
                logger.warning(f"Camoufox failed on Tier {current_tier} (Error: {result.get('error') if result else 'Unknown'}). Falling back to Chromium on Tier {current_tier}...")
                result = self.crawl_with_chromium(
                    url, count, enable_md, enable_html, enable_ss, enable_seo, enable_images, enable_json, client_id, current_tier
                )
                browser_name = "Chromium (Fallback)"
 
            if result and "error" not in result:
                logger.info("\n" + "="*30 + f"\nTier {current_tier} - Success\n" + "="*30)
                logger.info(f"{browser_name} success with Tier {current_tier}: {url}")
                return result
 
            logger.warning("\n" + "="*30 + f"\nTier {current_tier} - Failed\n" + "="*30)
            if current_tier < end_tier:
                logger.warning(f"{browser_name} failed with Tier {current_tier} (Error: {result.get('error') if result else 'Unknown'}). Escalating to Tier {current_tier + 1}...")
                current_tier += 1
            else:
                break
                
        logger.error(f"All browsers and tiers failed for: {url}")
        
        try:
            from api.core.config_setup import load_config
            import os
            from api.services.email_service import EmailService
            
            admin_email = os.getenv("ADMIN_EMAIL")
            if admin_email:
                config = load_config()
                smtp_config = config.get("email", {})
                email_service = EmailService(smtp_config)
                
                last_error = result.get('error') if result else 'Unknown'
                email_service.send_report_issue_email(
                    to_email=admin_email,
                    url_affected=url,
                    issue_related_to=["Crawler Proxy Exhaustion", "All Tiers Failed"],
                    explanation=f"The crawler failed to process this URL across all available proxy tiers and browsers.\n\nLast Error: {last_error}"
                )
        except Exception as e:
            logger.error(f"Failed to send alert email for proxy exhaustion: {e}")
        _record_crawl_error(
            crawl_id=client_id,
            url=url,
            error_source="Crawler Orchestrator",
            reason=f"Exhausted all proxy tiers without success.",
            blocked_message=result.get("error") if result else "All attempts failed with no specific error message."
        )
        
        return result

    def scroll_to_bottom(self, page):
        """
        Incrementally scroll page to trigger lazy loading.
        """
        try:
            logger.info("Starting slow auto-scroll to load dynamic content...")
            page.evaluate("""
                async () => {
                    await new Promise((resolve) => {
                        let totalHeight = 0;
                        let distance = 500; 
                        let timer = setInterval(() => {
                            let scrollHeight = document.body.scrollHeight;
                            let jitter = Math.floor(Math.random() * 20);
                            window.scrollBy(0, distance + jitter);
                            totalHeight += distance;

                            if(totalHeight >= scrollHeight || totalHeight > 15000){
                                clearInterval(timer);
                                resolve();
                            }
                        }, 200); 
                    });
                }
            """)
            page.wait_for_timeout(3000)
        except Exception as e:
            logger.warning(f"Scroll failed: {e}")

    def _handle_popups_and_overlays(self, page: Page):
        """
        Hide common popups and cookie banners using an aggressive non-destructive stealth approach.
        """
        try:
            try:
                page.wait_for_function("""
                    () => {
                        const skeletons = document.querySelectorAll('[class*="skeleton"], [class*="loading-shimmer"], .shimmer');
                        return skeletons.length === 0;
                    }
                """, timeout=3000)
            except: pass 

            page.evaluate("""
                () => {
                    const buttons = Array.from(document.querySelectorAll('button, a, span'));
                    const acceptKeywords = [
                        'accept all', 'allow all', 'accept cookies', 'agree', 'got it', 
                        'accept and close', 'confirm', 'allow cookies', 'agree & closed'
                    ];
                    
                    for (const btn of buttons) {
                        const text = btn.innerText.toLowerCase().trim();
                        if (acceptKeywords.some(kw => text === kw || text.includes(kw))) {
                            const style = window.getComputedStyle(btn);
                            if (style.position === 'fixed' || style.position === 'absolute' || parseInt(style.zIndex) > 10) {
                                try { btn.click(); } catch(e) {}
                            }
                        }
                    }
                }
            """)
            page.wait_for_timeout(1000)

            page.evaluate("""
                () => {
                    const selectorsToHide = [
                        '#onetrust-banner-sdk', '.ot-sdk-container', '#didomi-notice', 
                        '#cookie-banner', '.cookie-banner', '[id*="cookie"]', '[class*="cookie"]',
                        '[class*="consent"]', '[id*="consent"]', '[class*="privacy"]',
                        '.modal-backdrop', '.modal-open', '.fade.in',
                        '.bx-row-submit-button', '#newsletter-popup', '[id*="newsletter"]',
                        '[id^="sp_message_container"]', '.sp_veil', '.evidon-banner',
                        '#consent-banner', '.gdpr-consent', '.overlay', '.fixed-overlay',
                        '[class*="NewsletterPopup"]', '[class*="PromotionPopup"]',
                        '[id*="pop-up"]', '[class*="pop-up"]', '[id*="modal"]'
                    ];
                    
                    selectorsToHide.forEach(s => {
                        document.querySelectorAll(s).forEach(el => {
                            if (['BODY', 'HTML', 'HEADER', 'NAV'].includes(el.tagName)) return;
                            if (['app', 'root', 'main-content', 'header', 'nav'].includes(el.id)) return;
                            el.style.setProperty('display', 'none', 'important');
                        });
                    });
                    
                    document.body.style.setProperty('overflow', 'auto', 'important');
                    document.documentElement.style.setProperty('overflow', 'auto', 'important');
                    
                    document.querySelectorAll('*').forEach(el => {
                        const style = window.getComputedStyle(el);
                        if (parseInt(style.zIndex) > 100 && !['HEADER', 'NAV', 'BODY', 'HTML'].includes(el.tagName)) {
                            if (style.position === 'fixed' || style.position === 'absolute') {
                                el.style.setProperty('display', 'none', 'important');
                            }
                        }
                    });
                }
            """)
            page.wait_for_timeout(500)
            
        except Exception as e:
            logger.debug(f"Popup handling failed: {e}")

    def _capture_robust_screenshot(self, page: Page) -> bytes:
        """
        Capture page screenshot using a robust merging technique to avoid blank areas.
        Supports custom full page option, quality, and format.
        """
        try:
            viewport = page.viewport_size
            current_width = viewport["width"] if viewport else 1920
            current_height = viewport["height"] if viewport else 1080
            
            full_page = self.config.screenshot_full_page
            screenshot_format = self.config.screenshot_format.lower()
            pw_type = "jpeg" if screenshot_format in ("jpeg", "jpg") else "png"
            quality = self.config.screenshot_quality
            
            screenshot_args = {"full_page": full_page, "animations": "disabled", "type": pw_type}
            if pw_type == "jpeg" and quality is not None:
                screenshot_args["quality"] = quality

            if not full_page:
                page.evaluate("window.scrollTo(0, 0)")
                page.wait_for_timeout(500)
                return page.screenshot(**screenshot_args)
            
            page.evaluate("window.scrollTo(0, 0)")
            total_height = page.evaluate("""
                (() => {
                    let h1 = document.scrollingElement ? document.scrollingElement.scrollHeight : 0;
                    let h2 = document.body ? document.body.scrollHeight : 0;
                    return Math.max(h1, h2, 1000);
                })()
            """)
            
            if total_height < current_height * 2:
                page.evaluate("window.scrollTo(0, 0)")
                page.wait_for_timeout(1000)
                return page.screenshot(**screenshot_args)

            target_height = min(total_height, 12000) 
            page.set_viewport_size({"width": current_width, "height": target_height})
            
            page.evaluate("""
                async () => {
                    window.dispatchEvent(new Event('resize'));
                    window.scrollBy(0, 10);
                    await new Promise(r => setTimeout(r, 100));
                    window.scrollBy(0, -10);
                    
                    document.querySelectorAll('*').forEach(el => {
                        const style = window.getComputedStyle(el);
                        if (style.overflowY === 'auto' || style.overflowY === 'scroll' || style.overflow === 'auto' || style.overflow === 'scroll') {
                            el.style.setProperty('height', 'auto', 'important');
                            el.style.setProperty('overflow', 'visible', 'important');
                            el.style.setProperty('overflow-y', 'visible', 'important');
                        }
                    });

                    document.querySelectorAll('img').forEach(img => {
                        img.setAttribute('loading', 'eager');
                        const lazyAttr = img.getAttribute('data-src') || img.getAttribute('lazy-src') || img.getAttribute('data-lazy') || img.getAttribute('srcset');
                        if (lazyAttr && !img.src.includes(lazyAttr)) {
                            img.src = lazyAttr;
                        }
                    });
                }
            """)
            
            try:
                page.mouse.move(0, 0)
                page.wait_for_timeout(100)
            except:
                pass
            
            final_height = page.evaluate("Math.max(document.scrollingElement.scrollHeight, document.body.scrollHeight, 1000)")
            capture_height = min(final_height, 15000) 
            page.set_viewport_size({"width": current_width, "height": capture_height})
            
            try:
                page.evaluate("window.scrollTo(0, 0)")
                page.wait_for_timeout(100)
            except:
                pass
            logger.info(f"Taking screenshot...")
            logger.info(f"Setting final viewport height to {capture_height}px for screenshot")
            chunk_bytes = page.screenshot(**screenshot_args)
            
            page.set_viewport_size({"width": current_width, "height": current_height})
            return chunk_bytes
            
        except Exception as e:
            logger.warning(f"Screenshot failed, falling back to basic: {e}")
            try:
                page.set_viewport_size({"width": current_width, "height": current_height})
            except:
                pass
            page.evaluate("window.scrollTo(0, 0)")
            return page.screenshot(**screenshot_args)

    def is_cert_error_page(self, page: Page) -> bool:
        try:
            title = page.title()
            html = page.content()
            return "about:certerror" in page.url or "about:neterror" in page.url or "certerror" in html or "neterror" in html or "Potential Security Issue" in title
        except:
            return False
