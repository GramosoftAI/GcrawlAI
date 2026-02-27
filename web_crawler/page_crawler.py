"""
Individual page crawling logic
"""

import logging
import asyncio
import sys
import json
import time
import random
from typing import Optional, Dict
from pathlib import Path
from playwright.sync_api import sync_playwright, Page
from bs4 import BeautifulSoup
from web_crawler.seo_report import CrawlReportWriter
import platform

if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

from web_crawler.config import CrawlConfig
from web_crawler.file_manager import FileManager
from web_crawler.browser_utils import BrowserUtils
from web_crawler.content_processor import ContentProcessor
from web_crawler.websocket_manager import WebSocketManager
from web_crawler.utils import normalize_url
from web_crawler.redis_events import publish_event


logger = logging.getLogger(__name__)


class PageCrawler:
    """Handle individual page crawling"""
    
    def __init__(self, config: CrawlConfig, file_manager: FileManager):
        self.config = config
        self.file_manager = file_manager
        self.browser_utils = BrowserUtils()
        self.content_processor = ContentProcessor()
    
    def process_page(
        self,
        page: Page,
        url: str,
        count: int,
        enable_md: bool,
        enable_html: bool,
        enable_ss: bool,
        enable_seo: bool,
        client_id: Optional[str]
    ) -> Optional[Dict]:
        """Process loaded page and extract data"""
        md_path = None
        html_path = None
        screenshot_path = None
        seo_json_path = None
        seo_md_path = None
        seo_xlsx_path = None
        
        try:
            # Scroll to load dynamic content
            self.scroll_to_bottom(page)
            
            html = page.content()
            soup = BeautifulSoup(html, "lxml")
            seo = self.content_processor.extract_seo(soup, url)
            
            canonical_url = seo.get("canonical")
            canonical = normalize_url(canonical_url if canonical_url else url)
            
            title = seo.get("title")
            title_safe = self.file_manager.safe_filename(title if title else "page")
            prefix = f"{count}_{title_safe}"

            if enable_seo:
                try:
                    writer = CrawlReportWriter(self.config.output_dir)
                    seo_json_path = writer.save_single_json(prefix, seo)
                    seo_md_path = writer.save_single_markdown(prefix, seo)
                    seo_xlsx_path = writer.save_single_excel(prefix, seo)
                except Exception as e:
                    logger.error(f"Failed to save per-page SEO report for {url}: {e}")
            
            # Save HTML
            if enable_html:
                html_path = str(self.config.html_dir / f"{prefix}.html")
                try:
                    with open(html_path, "w", encoding="utf-8") as f:
                        f.write(html)
                except Exception as e:
                    logger.error(f"Failed to save HTML for {url}: {e}")
            
            # Save screenshot
            if enable_ss:
                screenshot_path = str(self.config.screenshot_dir / f"{prefix}.png")
                try:
                    page.screenshot(path=screenshot_path, full_page=True)
                except Exception as e:
                    logger.error(f"Failed to save screenshot for {url}: {e}")
            
            # Save markdown (per page file)
            if enable_md:
                try:
                    markdown = self.content_processor.convert_to_markdown(html, url)
                    # md_filename = f"{count}_{title_safe}.md"
                    # md_path = Path(self.config.output_dir) / md_filename
                    md_path = str(self.config.md_dir / f"{prefix}.md")
                    
                    with open(md_path, "w", encoding="utf-8") as f:
                        f.write(markdown)
                except Exception as e:
                    logger.error(f"Failed to save markdown for {url}: {e}")

            if client_id:
                publish_event(
                    crawl_id=client_id,
                    payload={
                        "type": "page_processed",
                        "page": count,
                        "url": url,
                        "title": seo.get("title", "No Title"),
                        "markdown_file": str(md_path) if md_path else None,
                        "html_file": html_path,
                        "screenshot": screenshot_path,
                        "seo_json": seo_json_path,
                        "seo_md": seo_md_path,
                        "seo_xlsx": seo_xlsx_path,
                    }
                )

            
            links = self.content_processor.extract_links(soup, url)
            
            logger.info(f"Successfully processed: {url}")
            
            return {
                "url": url,
                "canonical": canonical,
                "seo": seo,
                "html_file": html_path,
                "screenshot": screenshot_path,
                "markdown_file": str(md_path) if md_path else None,
                "links": links,
            }
            
        except Exception as e:
            logger.error(f"Error processing page {url}: {e}")
            return None

    def is_captcha_page(self, text_content: str) -> bool:
        """Check if the page is a Google/Cloudflare CAPTCHA page"""
        if not text_content:
            return False
            
        text_lower = text_content.lower()
        captcha_markers = [
            "our systems have detected unusual traffic from your computer network",
            "please show you're not a robot",
            "to continue, please type the characters below",
            "about this page",
            "i'm not a robot",
            "pardon our interruption",
            "enable javascript on your web browser",
            "before you continue to google",
            "not a robot",
            "recaptcha"
        ]
        
        if len(text_content.strip()) < 1500 and any(marker in text_lower for marker in captcha_markers):
            return True
        return False
    
    def setup_google_context(self, page: Page, url: str) -> None:
        """Setup Google-specific context with additional stealth measures"""
        try:
            # Set cookies to mimic real user
            page.context.add_cookies([
                {"name": "CONSENT", "value": "YES+cb.20210328-17-p0.en+FX+" , "domain": ".google.com", "path": "/"},
                {"name": "1P_JAR", "value": f"{time.time()*1000}", "domain": ".google.com", "path": "/"}
            ])
            
            # Set geolocation to appear as a real user
            page.context.set_geolocation({"latitude": 37.7749, "longitude": -122.4194})  # San Francisco
            
            # Set timezone
            page.emulate_media(timezone_id="America/Los_Angeles")
            
            # Add more realistic viewport
            page.set_viewport_size({"width": random.randint(1200, 1920), "height": random.randint(800, 1080)})
            
            # Add some randomness to user agent
            user_agents = [
                'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36',
                'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36',
                'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36'
            ]
            page.set_extra_http_headers({
                "User-Agent": random.choice(user_agents)
            })
            
        except Exception as e:
            logger.warning(f"Failed to setup Google context: {e}")
    
    def perform_human_actions(self, page: Page, url: str) -> None:
        """Perform human-like actions to appear more legitimate"""
        try:
            # Random mouse movements
            for _ in range(random.randint(3, 7)):
                x = random.randint(50, 500)
                y = random.randint(50, 500)
                page.mouse.move(x, y)
                time.sleep(random.uniform(0.1, 0.5))
            
            # Random scrolls
            for _ in range(random.randint(2, 4)):
                scroll_amount = random.randint(100, 500)
                page.mouse.wheel(0, scroll_amount)
                time.sleep(random.uniform(0.3, 1.0))
            
            # Random wait times
            time.sleep(random.uniform(1.0, 3.0))
            
            # Focus on search input if it exists
            try:
                search_input = page.query_selector("input[name='q']")
                if search_input:
                    search_input.focus()
                    time.sleep(random.uniform(0.5, 1.5))
            except:
                pass
                
        except Exception as e:
            logger.warning(f"Failed to perform human actions: {e}")
    
    def crawl_with_chromium(
        self,
        url: str,
        count: int,
        enable_md: bool,
        enable_html: bool,
        enable_ss: bool,
        enable_seo: bool,
        client_id: Optional[str]
    ) -> Optional[Dict]:
        """Crawl page using Chromium with stealth"""
        try:
            with sync_playwright() as p:
                browser_args = [
                    '--no-sandbox',
                    '--disable-setuid-sandbox',
                    '--disable-infobars',
                    '--ignore-certificate-errors',
                    '--window-position=0,0',
                    '--window-size=1920,1080',
                    '--disable-blink-features=AutomationControlled',
                    '--disable-web-security',
                    '--disable-features=IsolateOrigins,site-per-process',
                    '--disable-dev-shm-usage',
                    '--disable-gpu',
                    '--lang=en-US,en;q=0.9',
                    '--disable-background-timer-throttling',
                    '--disable-backgrounding-occluded-windows',
                    '--disable-renderer-backgrounding',
                    '--disable-ipc-flooding-protection'
                ]
                
                # Add proxy arguments if configured
                if self.config.proxy:
                    proxy_url = self.config.proxy
                    if "@" in proxy_url:
                        # Extract credentials from proxy URL
                        # Format: http://user:pass@host:port
                        protocol_host_port = proxy_url.split("@")[-1]
                        browser_args.extend([
                            f'--proxy-server={protocol_host_port}'
                        ])
                    else:
                        # Format: http://host:port
                        browser_args.extend([
                            f'--proxy-server={proxy_url}'
                        ])
                
                browser = p.chromium.launch(
                    headless=self.config.headless,
                    args=browser_args
                )
                
                # Prepare context options with proxy if configured
                context_options = {
                    "viewport": {"width": random.randint(1200, 1920), "height": random.randint(800, 1080)},
                    "locale": 'en-US',
                    # Updated to current Chrome version (133, Feb 2026)
                    "user_agent": 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36',
                    "java_script_enabled": True,
                    "ignore_https_errors": True,
                    "bypass_csp": True,
                    "extra_http_headers": {
                        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
                        "Accept-Language": "en-US,en;q=0.9",
                        "Accept-Encoding": "gzip, deflate, br",
                        "Upgrade-Insecure-Requests": "1",
                        "Sec-Fetch-Dest": "document",
                        "Sec-Fetch-Mode": "navigate",
                        "Sec-Fetch-Site": "none",
                        "Sec-Fetch-User": "?1",
                        "Cache-Control": "max-age=0"
                    }
                }
                
                # Add proxy configuration if provided
                if self.config.proxy:
                    # Parse proxy URL to extract components
                    from urllib.parse import urlparse
                    parsed_proxy = urlparse(self.config.proxy)
                    
                    proxy_config = {
                        "server": f"{parsed_proxy.scheme}://{parsed_proxy.hostname}:{parsed_proxy.port or 8080}"
                    }
                    
                    if parsed_proxy.username and parsed_proxy.password:
                        proxy_config["username"] = parsed_proxy.username
                        proxy_config["password"] = parsed_proxy.password
                    
                    context_options["proxy"] = proxy_config
                
                context = browser.new_context(**context_options)
                
                # Apply stealth at context level only
                from playwright_stealth import Stealth
                Stealth().apply_stealth_sync(context)
                
                page = context.new_page()

                if self.config.use_custom_headers:
                    self.browser_utils.set_custom_headers(page)
                
                # Skip resource-blocking on protected domains (Google uses resources to fingerprint)
                if not self.browser_utils.is_protected_domain(url):
                    page.route("**/*", self.browser_utils.block_resources)
                
                try:
                    # Special handling for Google searches
                    is_google_search = "google.com" in url.lower() and "search" in url.lower()
                    
                    if is_google_search:
                        # Setup Google-specific context
                        self.setup_google_context(page, url)
                        
                        # Navigate to page
                        response = page.goto(url, wait_until="domcontentloaded", timeout=60000)
                        
                        # Perform human-like actions
                        self.perform_human_actions(page, url)
                        
                        # Wait for network idle
                        try:
                            page.wait_for_load_state("networkidle", timeout=15000)
                        except:
                            pass
                    else:
                        response = page.goto(url, wait_until="domcontentloaded", timeout=60000)
                    
                    if not response or not (200 <= response.status < 300):
                        raise Exception(f"HTTP {response.status if response else 'None'}")   
                    
                    # Check for Cloudflare
                    self.browser_utils.check_cloudflare(page, self.config)
                    if not self.browser_utils.wait_for_ready(page):
                        raise Exception("Page not ready")
                        
                    # Validate content
                    text_content = page.evaluate("document.body.innerText")
                    if self.is_captcha_page(text_content):
                        # Try to handle Google CAPTCHA by waiting and simulating human behavior
                        if is_google_search:
                            logger.info("Detected Google CAPTCHA, attempting to bypass with advanced techniques...")
                            
                            # Try multiple approaches
                            for attempt in range(3):
                                logger.info(f"CAPTCHA bypass attempt {attempt + 1}/3")
                                
                                # Reload with different parameters
                                time.sleep(random.uniform(2.0, 4.0))
                                page.reload(wait_until="domcontentloaded", timeout=30000)
                                
                                # Perform human actions
                                self.perform_human_actions(page, url)
                                
                                # Wait and check again
                                time.sleep(random.uniform(3.0, 6.0))
                                text_content = page.evaluate("document.body.innerText")
                                
                                if not self.is_captcha_page(text_content):
                                    logger.info("Successfully bypassed CAPTCHA!")
                                    break
                                else:
                                    logger.warning(f"CAPTCHA still present after attempt {attempt + 1}")
                            
                            if self.is_captcha_page(text_content):
                                # If we still have CAPTCHA, try to solve it if possible
                                captcha_elements = page.query_selector_all("iframe[src*='recaptcha']")
                                if captcha_elements:
                                    logger.warning("Recaptcha detected, cannot solve automatically. Consider using a proxy.")
                                
                                raise Exception("Google CAPTCHA detected - unable to bypass. Consider using a proxy or reducing request frequency.")
                        else:
                            raise Exception("CAPTCHA detected")
                        
                    if len(text_content.strip()) < 200:
                        raise Exception(f"Content too short ({len(text_content.strip())} chars)")
                    
                    result = self.process_page(page, url, count, enable_md, enable_html, enable_ss, enable_seo, client_id)
                    return result
                
                finally:
                    # Clean up routes before closing browser to prevent async TargetClosedError/CancelledError tracebacks
                    try:
                        if not self.browser_utils.is_protected_domain(url):
                            page.unroute("**/*")
                    except Exception:
                        pass
                    # Small wait to let pending routes settle before closing context
                    try:
                        page.wait_for_timeout(100)
                    except Exception:
                        pass
                        
                    try:
                        page.close()
                    except Exception:
                        pass
                    
                    try:
                        context.close()
                    except Exception:
                        pass
                    
                    try:
                        browser.close()
                    except Exception:
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
        client_id: Optional[str]
    ) -> Optional[Dict]:
        """Fallback crawl using Camoufox"""
        if not self.config.camoufox_path:
            logger.warning("Camoufox path not configured")
            return None
        
        try:
            with sync_playwright() as p:
                # Add proxy arguments for Firefox/Camoufox
                firefox_user_prefs = {}
                if self.config.proxy:
                    from urllib.parse import urlparse
                    parsed_proxy = urlparse(self.config.proxy)
                    firefox_user_prefs = {
                        "network.proxy.type": 1,  # Manual proxy config
                        "network.proxy.http": parsed_proxy.hostname,
                        "network.proxy.http_port": parsed_proxy.port or 8080,
                        "network.proxy.ssl": parsed_proxy.hostname,
                        "network.proxy.ssl_port": parsed_proxy.port or 8080,
                        "network.proxy.ftp": parsed_proxy.hostname,
                        "network.proxy.ftp_port": parsed_proxy.port or 8080,
                        "network.proxy.socks": parsed_proxy.hostname,
                        "network.proxy.socks_port": parsed_proxy.port or 8080,
                        "network.proxy.share_proxy_settings": True,
                        "network.proxy.no_proxies_on": "",
                        "intl.accept_languages": "en-US,en;q=0.9",
                        "general.useragent.override": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:133.0) Gecko/20100101 Firefox/133.0"
                    }
                    
                    # Handle proxy authentication
                    if parsed_proxy.username and parsed_proxy.password:
                        firefox_user_prefs.update({
                            "network.proxy.username": parsed_proxy.username,
                            "network.proxy.password": parsed_proxy.password
                        })
                
                if platform.system() == "Windows":
                    browser = p.firefox.launch(
                        executable_path=self.config.camoufox_path,
                        headless=self.config.headless,
                        firefox_user_prefs=firefox_user_prefs
                    )
                else:
                    browser = p.firefox.launch(
                        headless=self.config.headless,
                        firefox_user_prefs=firefox_user_prefs
                    )
                
                try:
                    # Prepare context options with proxy if configured
                    context_options = {
                        "viewport": {"width": random.randint(1200, 1920), "height": random.randint(800, 1080)},
                        "locale": 'en-US',
                        # No user_agent override — let Camoufox (Firefox) present its native UA.
                        # Overriding with Chrome UA on a Firefox binary creates a contradictory fingerprint.
                        "java_script_enabled": True,
                        "ignore_https_errors": True,
                        "bypass_csp": True
                    }
                    
                    # Add proxy configuration if provided
                    if self.config.proxy:
                        # Parse proxy URL to extract components
                        from urllib.parse import urlparse
                        parsed_proxy = urlparse(self.config.proxy)
                        
                        proxy_config = {
                            "server": f"{parsed_proxy.scheme}://{parsed_proxy.hostname}:{parsed_proxy.port or 8080}"
                        }
                        
                        if parsed_proxy.username and parsed_proxy.password:
                            proxy_config["username"] = parsed_proxy.username
                            proxy_config["password"] = parsed_proxy.password
                        
                        context_options["proxy"] = proxy_config
                    
                    context = browser.new_context(**context_options)
                    
                    # Apply stealth at context level only
                    from playwright_stealth import Stealth
                    Stealth().apply_stealth_sync(context)
                    
                    page = context.new_page()

                    if self.config.use_custom_headers:
                        self.browser_utils.set_custom_headers(page)
                    
                    # Skip resource-blocking on protected domains (Google uses resources to fingerprint)
                    if not self.browser_utils.is_protected_domain(url):
                        page.route("**/*", self.browser_utils.block_resources)
                    
                    # Special handling for Google searches
                    is_google_search = "google.com" in url.lower() and "search" in url.lower()
                    
                    if is_google_search:
                        # Setup Google-specific context
                        self.setup_google_context(page, url)
                        
                        response = page.goto(url, wait_until="domcontentloaded", timeout=60000)
                        
                        # Perform human-like actions
                        self.perform_human_actions(page, url)
                        
                        try:
                            page.wait_for_load_state("networkidle", timeout=15000)
                        except:
                            pass
                    else:
                        response = page.goto(url, wait_until="domcontentloaded", timeout=60000)
                    
                    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                    page.wait_for_timeout(4000)
                    
                    if not response or not (200 <= response.status < 300):
                        return None
                    
                    if not self.browser_utils.wait_for_ready(page):
                        return None
                        
                    text_content = page.evaluate("document.body.innerText")
                    if self.is_captcha_page(text_content):
                        logger.warning(f"Camoufox also hit CAPTCHA for {url}")
                        # For Google searches, try additional human-like behavior
                        if is_google_search:
                            logger.info("Attempting to bypass Google CAPTCHA with Camoufox...")
                            
                            # Try multiple approaches
                            for attempt in range(3):
                                logger.info(f"Camoufox CAPTCHA bypass attempt {attempt + 1}/3")
                                
                                time.sleep(random.uniform(3.0, 5.0))
                                page.reload(wait_until="domcontentloaded", timeout=30000)
                                
                                # Perform human actions
                                self.perform_human_actions(page, url)
                                
                                time.sleep(random.uniform(3.0, 6.0))
                                text_content = page.evaluate("document.body.innerText")
                                
                                if not self.is_captcha_page(text_content):
                                    logger.info("Successfully bypassed CAPTCHA with Camoufox!")
                                    return self.process_page(page, url, count, enable_md, enable_html, enable_ss, enable_seo, client_id)
                                else:
                                    logger.warning(f"CAPTCHA still present after Camoufox attempt {attempt + 1}")
                            
                            logger.warning(f"Still getting CAPTCHA with Camoufox for {url}")
                            return None
                        else:
                            return None
                    
                    result = self.process_page(page, url, count, enable_md, enable_html, enable_ss, enable_seo, client_id)
                    return result
                finally:
                    try:
                        if not self.browser_utils.is_protected_domain(url):
                            page.unroute("**/*")
                    except Exception:
                        pass
                    try:
                        page.wait_for_timeout(100)
                    except Exception:
                        pass
                        
                    try:
                        page.close()
                    except Exception:
                        pass
                        
                    try:
                        context.close()
                    except Exception:
                        pass
                        
                    try:
                        browser.close()
                    except Exception:
                        pass
                
        except Exception as e:
            logger.error(f"Camoufox failed for {url}: {e}")
            return None
    
    def crawl_page(
        self,
        url: str,
        count: int,
        enable_md: bool,
        enable_html: bool,
        enable_ss: bool,
        enable_seo: bool,
        client_id: Optional[str],
        websocket_manager
    ) -> Optional[Dict]:
        """Crawl a single page with fallback browsers"""
        logger.info(f"Crawling [{count}]: {url}")
        
        WebSocketManager.send_update(client_id, websocket_manager, {
            "type": "progress",
            "status": "starting",
            "url": url,
            "count": count
        })
        
        # Try Chromium first
        result = self.crawl_with_chromium(url, count, enable_md, enable_html, enable_ss, enable_seo, client_id)
        
        if result:
            logger.info(f"Chromium success: {url}")
            return result
    
        # Fallback to Camoufox
        logger.info(f"Trying Camoufox fallback for: {url}")
        result = self.crawl_with_camoufox(url, count, enable_md, enable_html, enable_ss, enable_seo, client_id)
        
        if result:
            logger.info(f"Camoufox success: {url}")
        else:
            logger.error(f"All browsers failed for: {url}")
        
        return result

    def scroll_to_bottom(self, page, max_scrolls=10, wait_time=500):
        """
        Incrementally scroll page to trigger lazy loading
        """
        try:
            prev_height = -1
            for _ in range(max_scrolls):
                # Scroll in chunks
                page.mouse.wheel(0, 1000)
                page.wait_for_timeout(200)
                
                # Check if height changed
                curr_height = page.evaluate("document.body.scrollHeight")
                if curr_height == prev_height:
                    break
                prev_height = curr_height
                
                # Small wait between major chunks
                page.wait_for_timeout(wait_time)
                
            # Final ensure bottom
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            page.wait_for_timeout(wait_time)
            
        except Exception as e:
            logger.warning(f"Scroll failed: {e}")
