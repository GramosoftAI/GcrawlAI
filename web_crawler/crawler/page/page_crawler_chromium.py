import logging
import random
import time
from typing import Optional, Dict
from playwright.sync_api import Page
from web_crawler.common.config import CrawlConfig
from web_crawler.crawler.page.page_crawler1 import browser_manager

logger = logging.getLogger(__name__)


class ChromiumCrawlerMixin:
    """Mixin for Chromium crawling engine with stealth evasion."""
    
    def _build_chrome_headers(self, chrome_version: str, is_high_sec: bool, url: str) -> dict:
        """Construct a set of Client Hints that are safe to set context-wide.
        Accept, Sec-Fetch, and Referer headers are generated naturally by Chromium
        or overridden specifically during page.goto navigations to prevent subresource pollution.
        """
        return {
            "sec-ch-ua": f'"Not(A:Brand";v="99", "Google Chrome";v="{chrome_version}", "Chromium";v="{chrome_version}"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": "\"Windows\"",
        }

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
            browser = browser_manager.get_chromium(self.config, direct=(proxy_settings is None))
            
            is_japan = "jal.co.jp" in url.lower() or ".jp" in url.lower()
            is_india = "meesho" in url.lower() or "dinamalar" in url.lower() or ".in" in url.lower()
            
            if proxy_settings is None:
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
                java_script_enabled=True,
                ignore_https_errors=True,
                bypass_csp=True
            )
            if proxy_settings:
                context_kwargs["proxy"] = proxy_settings

            if self.config.render_timeout is not None:
                nav_timeout = self.config.render_timeout
            else:
                nav_timeout = 30000 if enable_ss else 15000

            if "google.com/search" in url and proxy_tier > 1:
                mobile_ua = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Mobile/15E148 Safari/604.1"
                context_kwargs["user_agent"] = mobile_ua
                context_kwargs["viewport"] = {"width": 390, "height": 844}
                context_kwargs["is_mobile"] = True
                context_kwargs["has_touch"] = True
            else:
                try:
                    clean_ua = f"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{browser.version} Safari/537.36"
                except:
                    clean_ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                context_kwargs["user_agent"] = clean_ua

            self._load_session_state(client_id, url, context_kwargs, browser_type="chromium")

            context = browser.new_context(**context_kwargs)

            # Apply playwright-stealth directly to the Chromium context
            from playwright_stealth import Stealth
            Stealth().apply_stealth_sync(context)
            
            logger.info(f"Chromium browser (windows) initialized successfully with evasion flags")
            logger.info(f"[Stealth Layer] Engine initialization: Hardened TLS fingerprinting and browser fingerprint evasion active.")
            logger.info(f"[Stealth Layer] Browser Fingerprinting: Platform=Desktop, Viewport={context_kwargs['viewport']['width']}x{context_kwargs['viewport']['height']}, Locale={context_kwargs['locale']}")
            logger.info(f"[Stealth Layer] Network Identity: Applying organic Chrome headers, Stealth Plugin, and Referer spoofing.")

            extreme_high_sec = ["expedia.com", "zillow.com", "wayfair.com", "oracle.com", "gartner.com"]
            is_high_sec = any(s in url.lower() for s in self.high_sec_sites)
            is_extreme = any(s in url.lower() for s in extreme_high_sec)
            
            is_skyscanner = "skyscanner" in url.lower()

            try:
                chrome_version = browser.version.split('.')[0]
            except Exception:
                chrome_version = "133"
            # Build comprehensive Chrome headers using helper
            custom_headers = self._build_chrome_headers(chrome_version, is_high_sec, url)

            context.set_extra_http_headers(custom_headers)
            
            page = context.new_page()
            
            # OPTIMIZATION: Block heavy network resources
            is_protected = self.browser_utils.is_protected_domain(url)
            block_images = not enable_ss and not is_protected
            block_css = False
            self.browser_utils.setup_resource_routing(page, block_images=block_images, block_css=block_css)
            
            # Manual Deep Stealth Scripts (webdriver wipe, chrome object mock)
            page.add_init_script(f"""
                // Brutally scrub Playwright variables before any site script can load
                delete window.__playwright;
                delete window.__pw;
            """)

            try:
                from playwright_stealth import stealth_sync
                stealth_sync(page)
                logger.debug("[Stealth Layer] Applied official playwright-stealth patches to Chromium page.")
            except Exception as e:
                pass

            ua = context_kwargs.get("user_agent", "")
            profile = self.browser_utils.generate_stealth_profile(ua, locale=target_locale)
            self.browser_utils.inject_stealth_scripts(page, locale=target_locale, profile=profile)
            
            extra_high_sec = ["expedia", "axs", "southwest", "skyscanner", "neimanmarcus"]
            if any(s in url.lower() for s in extra_high_sec):
                is_high_sec = True
            
            referer = "https://www.google.com/"
            if is_high_sec:
                domain_name = next((s for s in self.high_sec_sites if s in url.lower()), "site")
                referer = f"https://www.google.com/search?q={domain_name}+official+store&oq={domain_name}"
                if "skyscanner" in url.lower():
                    referer = "https://www.google.com/"
            
            try:
                logger.info(f"Navigating to target URL: {url} (Chromium)")
                wait_mode = "load" if enable_ss else "domcontentloaded"
                
                try:
                    response = page.goto(url, wait_until=wait_mode, timeout=nav_timeout, referer=referer)
                except Exception as e:
                    err_msg = str(e).lower()
                    if "timeout" in err_msg:
                        logger.warning(f"Chromium page.goto timed out for {url}. Checking if any DOM content was loaded...")
                        try:
                            html = page.content()
                            from bs4 import BeautifulSoup
                            soup = BeautifulSoup(html, "lxml")
                            text_len = len(soup.get_text().strip())
                            el_count = len(soup.find_all())
                            if text_len > 200 or el_count > 15:
                                logger.info(f"Substantial DOM content found (text: {text_len} chars, elements: {el_count}) despite timeout. Proceeding.")
                                response = None
                            else:
                                raise e
                        except Exception as check_err:
                            logger.error(f"Failed to check page content after timeout: {check_err}")
                            raise e
                    elif "err_empty_response" in err_msg or "reset" in err_msg or "interrupted" in err_msg or "aborted" in err_msg:
                        logger.warning(f"Chromium network error for {url}. Waiting 1s and retrying with {wait_mode}...")
                        page.wait_for_timeout(1000)
                        try:
                            response = page.goto(url, wait_until=wait_mode, timeout=nav_timeout + 10000, referer=referer)
                        except Exception as retry_e:
                            if "aborted" in str(retry_e).lower():
                                logger.warning(f"Chromium request aborted by target (possible bot block).")
                                return {"url": url, "error": "Connection Aborted (Bot Block)", "status_code": 403}
                            raise retry_e
                    else:
                        raise e
                
                logger.info(f"Navigation completed. Status: {response.status if response else 'No Response (Proceeded on timeout)'}")
                
                status_code = response.status if response else (page.evaluate("() => { try { return window.performance.getEntries()[0].responseStatus; } catch { return 200; } }") or 200)

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
                    # Adaptive Page Loading & Stabilization for standard crawls
                    if enable_ss:
                        try:
                            page.wait_for_load_state("networkidle", timeout=3000)
                        except Exception:
                            pass
                            
                        try:
                            self.browser_utils.wait_for_ready(page, quick=True)
                        except Exception as load_err:
                            logger.debug(f"Error during standard page load stabilization: {load_err}")
                        
                    result = self.process_page(page, url, count, enable_md, enable_html, enable_ss, enable_seo, enable_images, enable_json, client_id, status_code=status_code)
                    self._save_session_state(client_id, url, context, result, browser_type="chromium")
                    return result

                try:
                    page.wait_for_selector("body", state="visible", timeout=5000)
                    if is_high_sec:
                        page.wait_for_timeout(3000)
                except Exception as wait_err:
                    logger.warning(f"Error during initial wait: {wait_err}")
                
                # Post-load state CAPTCHA / WAF check
                if self.is_captcha_page(page):
                    logger.debug("CAPTCHA/Challenge detected after initial load wait (Chromium). Waiting for stealth bypass...")
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

                status_code = response.status if response else 0
                title = page.title()
                
                if status_code in [401, 407, 502, 503, 504]:
                    logger.warning(f"Bailing out due to status {status_code} before behavioral simulation.")
                    return {"url": url, "error": f"Block/Auth error: {status_code}", "status_code": status_code}

                if (not title and status_code == 200) or is_skyscanner or is_high_sec:
                    title = page.title()

                has_visuals = enable_ss or enable_images or enable_html or enable_md
                if (is_high_sec or is_skyscanner) and has_visuals:
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
                    if self.config.auto_scroll and enable_ss:
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
                                    let lastHeight = scrollTarget.scrollHeight || document.documentElement.scrollHeight;
                                    let currentY = 0;
                                    let reachedBottom = false;
                                    let consecutiveNoChange = 0;
                                    let stepCount = 0;

                                    while (!reachedBottom && consecutiveNoChange < 5 && stepCount < maxScrolls) {
                                        const clientHeight = scrollTarget.clientHeight || window.innerHeight;
                                        const scrollHeight = scrollTarget.scrollHeight || document.documentElement.scrollHeight;
                                        const maxScrollPos = scrollHeight - clientHeight;

                                        // Scroll down by 80% of clientHeight
                                        const step = Math.max(300, Math.floor(clientHeight * 0.8));
                                        currentY = Math.min(currentY + step, maxScrollPos);

                                        if (scrollTarget === window || scrollTarget === document.documentElement || scrollTarget === document.body) {
                                            window.scrollTo({ top: currentY, behavior: 'smooth' });
                                        } else {
                                            scrollTarget.scrollTo({ top: currentY, behavior: 'smooth' });
                                        }

                                        stepCount++;

                                        // Wait for delay
                                        await new Promise(r => setTimeout(r, delay));

                                        // Check if height has changed or we reached the bottom
                                        const newHeight = scrollTarget.scrollHeight || document.documentElement.scrollHeight;
                                        if (newHeight === lastHeight) {
                                            consecutiveNoChange++;
                                        } else {
                                            consecutiveNoChange = 0;
                                            lastHeight = newHeight;
                                        }

                                        // If we are close to the bottom (within 10 pixels), we've reached the bottom
                                        const currentScrollTop = (scrollTarget === window) ? window.scrollY : (scrollTarget.scrollTop || window.scrollY);
                                        if (currentY >= maxScrollPos || currentScrollTop >= maxScrollPos - 10) {
                                            reachedBottom = true;
                                        }
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
                         logger.info("Auto-scroll skipped (disabled or not needed for this crawl type).")
                    
                    if enable_ss:
                        if not self.browser_utils.wait_for_ready(page, quick=False): 
                            logger.warning(f"Page stabilization timed out for {url}, proceeding anyway.")
                
                if self.is_captcha_page(page): 
                    return {"url": url, "error": "CAPTCHA detected", "status_code": 403}
                    
                result = self.process_page(page, url, count, enable_md, enable_html, enable_ss, enable_seo, enable_images, enable_json, client_id, status_code=status_code)
                self._save_session_state(client_id, url, context, result, browser_type="chromium")
                return result
            finally:
                try:
                    if page: page.close()
                    if context: context.close()
                except:
                    pass
        except Exception as e:
            err_msg = str(e).lower()
            logger.warning(f"Chromium failed for {url}: {e}")
            
            # Recycle browser on critical network or protocol errors to prevent reusing bad socket state
            if "err_http2_protocol_error" in err_msg or "protocol" in err_msg or "http2" in err_msg or "aborted" in err_msg or "connection closed" in err_msg:
                logger.info(f"[Stealth Layer] Critical HTTP/2 Protocol or Connection Error. Recycling warm Chromium instance...")
                try:
                    browser_manager.close_chromium(direct=(proxy_settings is None))
                except Exception as close_err:
                    logger.error(f"Failed to close browser during recycling: {close_err}")
                    
            return None

