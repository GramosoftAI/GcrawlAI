import asyncio
from random import randint, uniform
from typing import Optional, Dict, Callable
from patchright.sync_api import sync_playwright, Page
from patchright.async_api import async_playwright as async_pw
from patchright.async_api import Page as AsyncPage
from .response import Response
import time
import requests
import logging

logger = logging.getLogger(__name__)

class StealthyFetcher:

    def __init__(
        self,
        headless: bool = False,
        user_agent: Optional[str] = None,
        locale: str = "en-IN",
        timezone_id: Optional[str] = None,
        proxy: Optional[Dict[str, str]] = None,
        viewport_width: int = 1920,
        viewport_height: int = 1080,
        bypass_csp: bool = True,
        extra_headers: Optional[Dict[str, str]] = None,
        block_resources: bool = True,
        wait_until: str = "domcontentloaded",
        timeout: int = 30000,
        solve_cloudflare: bool = True,
    ):
        self.headless = headless
        self.user_agent = user_agent or "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        self.locale = locale
        self.timezone_id = timezone_id
        self.proxy = proxy
        self.viewport = {"width": viewport_width, "height": viewport_height}
        self.bypass_csp = bypass_csp
        self.extra_headers = extra_headers or {}
        self.block_resources = block_resources
        self.wait_until = wait_until
        self.timeout = timeout
        self.solve_cloudflare = solve_cloudflare
        
        import os
        from dotenv import load_dotenv
        load_dotenv()
        self.capmonster_key = os.getenv("CAPMONSTER_API_KEY")
        logger.info(f"[*] CapMonster API Key: {self.capmonster_key}")

    def _is_google_captcha(self, page: Page) -> bool:
        """Check if page is a Google reCAPTCHA challenge (/sorry/index)."""
        if "/sorry/index" in page.url:
            return True
        return False

    def _solve_google_captcha(self, page: Page) -> bool:
        """Solve Google reCAPTCHA v2 using CapMonster API."""
        print("Google CAPTCHA detected! Attempting to solve with CapMonster...")
        
        if not self.capmonster_key:
            print("Error: CAPMONSTER_API_KEY environment variable not set. Cannot solve.")
            return False

        try:
            # Wait for reCAPTCHA element
            page.wait_for_selector(".g-recaptcha", state="attached", timeout=5000)
            site_key = page.locator(".g-recaptcha").get_attribute("data-sitekey")
            
            if not site_key:
                print("Could not find data-sitekey for CAPTCHA")
                return False
                
            website_url = page.url
            print(f"Found site_key: {site_key}. Sending to CapMonster...")

            # Create Task
            create_task_payload = {
                "clientKey": self.capmonster_key,
                "task": {
                    "type": "NoCaptchaTaskProxyless",
                    "websiteURL": website_url,
                    "websiteKey": site_key
                }
            }
            
            resp = requests.post("https://api.capmonster.cloud/createTask", json=create_task_payload).json()
            if resp.get("errorId") != 0:
                print(f"CapMonster createTask failed: {resp}")
                return False
                
            task_id = resp["taskId"]
            print(f"CapMonster Task created (ID: {task_id}). Waiting for solution...")
            
            # Poll for result
            solution = None
            for _ in range(30):
                time.sleep(1)
                res = requests.post("https://api.capmonster.cloud/getTaskResult", json={
                    "clientKey": self.capmonster_key,
                    "taskId": task_id
                }).json()
                
                if res.get("status") == "ready":
                    solution = res.get("solution", {}).get("gRecaptchaResponse")
                    break
                elif res.get("status") == "processing":
                    continue
                else:
                    print(f"CapMonster getTaskResult error: {res}")
                    return False
                    
            if not solution:
                print("CapMonster solving timed out.")
                return False
                
            print("CapMonster returned solution token! Injecting into page...")
            
            # Inject token and submit
            js_code = f"""
                var form = document.forms[0];
                if (form) {{
                    var el = document.getElementById("g-recaptcha-response") || document.querySelector('[name="g-recaptcha-response"]');
                    if (el) {{
                        el.innerHTML = "{solution}";
                        el.value = "{solution}";
                    }} else {{
                        var input = document.createElement("textarea");
                        input.id = "g-recaptcha-response";
                        input.name = "g-recaptcha-response";
                        input.value = "{solution}";
                        form.appendChild(input);
                    }}
                    form.submit();
                }}
            """
            page.evaluate(js_code)
            page.wait_for_load_state("networkidle", timeout=15000)
            
            # Verify if captcha was passed
            if not self._is_google_captcha(page):
                print("Successfully bypassed Google CAPTCHA!")
                return True
            else:
                print("Failed: Still on CAPTCHA page after form submission.")
                return False
                
        except Exception as e:
            print(f"Error solving Google CAPTCHA: {e}")
            return False

    def _is_cloudflare_challenge(self, page: Page) -> bool:
        """Check if page is a Cloudflare challenge."""
        try:
            title = page.title()
            if "Just a moment" in title:
                return True
            content = page.content()
            if "challenges.cloudflare.com" in content:
                return True
            # Check for challenge iframe
            iframes = page.frames
            for frame in iframes:
                if "challenges.cloudflare.com" in frame.url:
                    return True
        except:
            pass
        return False

    def _solve_cloudflare(self, page: Page) -> bool:
        """
        Solve Cloudflare Turnstile challenge using behavioral simulation.
        Returns True if solved successfully.
        """
        print("Cloudflare challenge detected! Attempting to solve...")

        # Wait for Turnstile widget to render
        page.wait_for_timeout(3000)

        # Look for the Turnstile checkbox/button
        selectors = [
            "#cf_turnstile div",
            "#cf-turnstile div",
            ".turnstile > div > div",
            "div[data-widget-id]",
            ".cf-turnstile-checkbox",
        ]

        for selector in selectors:
            try:
                elements = page.locator(selector)
                if elements.count() > 0:
                    box = elements.bounding_box()
                    if box:
                        # Calculate random offset within the element (anti-bot evasion)
                        click_x = box["x"] + randint(20, 35)
                        click_y = box["y"] + randint(20, 35)

                        # Move mouse naturally with random steps
                        page.mouse.move(click_x - 50, click_y - 50)
                        page.wait_for_timeout(uniform(100, 300))

                        # Click with random delay
                        page.mouse.click(
                            click_x, click_y,
                            delay=randint(100, 250),
                            button="left"
                        )

                        print(f"Clicked Turnstile element at ({click_x}, {click_y})")
                        break
            except:
                continue

        # Wait for challenge to disappear
        max_wait = 30  # seconds
        waited = 0
        while waited < max_wait:
            if not self._is_cloudflare_challenge(page):
                print("Cloudflare challenge passed!")
                return True
            page.wait_for_timeout(1000)
            waited += 1

        print("Cloudflare challenge timeout or still present")
        return not self._is_cloudflare_challenge(page)

    def fetch(
        self,
        url: str,
        page_action: Optional[Callable[[Page], None]] = None,
        referer: str = "https://www.google.com/",
        retries: int = 3,
    ) -> Response:
        """
        Fetch a URL with stealth and optional Cloudflare solving.
        """
        for attempt in range(retries):
            try:
                with sync_playwright() as p:
                    # Launch Patchright browser with stealth args
                    browser = p.chromium.launch(
                        headless=self.headless,
                        ignore_default_args=["--enable-automation"],
                        args=[
                            "--disable-blink-features=AutomationControlled",
                            "--disable-dev-shm-usage",
                            "--disable-accelerated-2d-canvas",
                            "--disable-gpu",
                            "--no-sandbox",
                        ]
                    )

                    # Create context with stealth settings
                    context = browser.new_context(
                        user_agent=self.user_agent,
                        locale=self.locale,
                        timezone_id=self.timezone_id,
                        proxy=self.proxy,
                        viewport=self.viewport,
                        bypass_csp=self.bypass_csp,
                        extra_http_headers=self.extra_headers,
                        java_script_enabled=True,
                    )

                    page = context.new_page()
                    page.set_default_timeout(self.timeout)

                    # Inject stealth scripts to patch navigator.webdriver
                    page.add_init_script("""
                        Object.defineProperty(navigator, 'webdriver', {
                            get: () => undefined
                        });
                        Object.defineProperty(navigator, 'plugins', {
                            get: () => [1, 2, 3, 4, 5]
                        });
                        Object.defineProperty(navigator, 'languages', {
                            get: () => ['en-US', 'en']
                        });
                    """)

                    # Block resources
                    if self.block_resources:
                        page.route("**/*", lambda route: route.abort()
                            if route.request.resource_type in ["font", "image", "media", "websocket"]
                            else route.continue_())

                    # Navigate
                    response = page.goto(url, referer=referer, wait_until=self.wait_until)

                    # Check and solve Cloudflare
                    if self.solve_cloudflare and self._is_cloudflare_challenge(page):
                        if not self._solve_cloudflare(page):
                            raise Exception("Cloudflare challenge could not be solved")
                            
                    # Check and solve Google Captcha
                    if self._is_google_captcha(page):
                        if not self._solve_google_captcha(page):
                            raise Exception("Google CAPTCHA could not be solved")

                    # Wait for network idle
                    try:
                        page.wait_for_load_state("networkidle", timeout=5000)
                    except:
                        pass

                    # Execute custom action
                    if page_action:
                        page_action(page)

                    # Extract
                    content = page.content()
                    status = response.status if response else 200
                    headers = response.headers if response else {}
                    final_url = page.url

                    browser.close()

                    return Response(
                        content=content,
                        headers=headers,
                        status=status,
                        url=final_url,
                        ok=status < 400,
                    )

            except Exception as e:
                print(f"Attempt {attempt + 1} failed: {e}")
                if attempt == retries - 1:
                    return Response(
                        content="",
                        headers={},
                        status=0,
                        url=url,
                        ok=False,
                        error=str(e),
                    )

        return Response(
            content="",
            headers={},
            status=0,
            url=url,
            ok=False,
            error="Max retries exceeded",
        )


class AsyncStealthyFetcher:
    """
    Asynchronous stealthy browser automation using Patchright.
    """

    def __init__(
        self,
        headless: bool = False,
        user_agent: Optional[str] = None,
        locale: str = "en-IN",
        timezone_id: Optional[str] = None,
        proxy: Optional[Dict[str, str]] = None,
        viewport_width: int = 1920,
        viewport_height: int = 1080,
        bypass_csp: bool = True,
        extra_headers: Optional[Dict[str, str]] = None,
        block_resources: bool = True,
        wait_until: str = "domcontentloaded",
        timeout: int = 30000,
        solve_cloudflare: bool = True,
    ):
        self.headless = headless
        self.user_agent = user_agent or "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        self.locale = locale
        self.timezone_id = timezone_id
        self.proxy = proxy
        self.viewport = {"width": viewport_width, "height": viewport_height}
        self.bypass_csp = bypass_csp
        self.extra_headers = extra_headers or {}
        self.block_resources = block_resources
        self.wait_until = wait_until
        self.timeout = timeout
        self.solve_cloudflare = solve_cloudflare

        import os
        from dotenv import load_dotenv
        load_dotenv()
        self.capmonster_key = os.getenv("CAPMONSTER_API_KEY")

    def _is_cloudflare_challenge(self, page: AsyncPage) -> bool:
        """Check if page is a Cloudflare challenge."""
        try:
            title = asyncio.get_event_loop().run_until_complete(page.title())
            if "Just a moment" in title:
                return True
            content = asyncio.get_event_loop().run_until_complete(page.content())
            if "challenges.cloudflare.com" in content:
                return True
            iframes = page.frames
            for frame in iframes:
                if "challenges.cloudflare.com" in frame.url:
                    return True
        except:
            pass
        return False

    async def _solve_cloudflare(self, page: AsyncPage) -> bool:
        """Solve Cloudflare Turnstile challenge."""
        print("Cloudflare challenge detected! Attempting to solve...")

        await page.wait_for_timeout(3000)

        selectors = [
            "#cf_turnstile div",
            "#cf-turnstile div",
            ".turnstile > div > div",
            "div[data-widget-id]",
        ]

        for selector in selectors:
            try:
                elements = page.locator(selector)
                if await elements.count() > 0:
                    box = await elements.bounding_box()
                    if box:
                        click_x = box["x"] + randint(20, 35)
                        click_y = box["y"] + randint(20, 35)

                        await page.mouse.move(click_x - 50, click_y - 50)
                        await page.wait_for_timeout(uniform(100, 300))

                        await page.mouse.click(
                            click_x, click_y,
                            delay=randint(100, 250),
                            button="left"
                        )

                        print(f"Clicked Turnstile element at ({click_x}, {click_y})")
                        break
            except:
                continue

        max_wait = 30
        waited = 0
        while waited < max_wait:
            if not self._is_cloudflare_challenge(page):
                print("Cloudflare challenge passed!")
                return True
            await page.wait_for_timeout(1000)
            waited += 1

        return not self._is_cloudflare_challenge(page)

    async def fetch(
        self,
        url: str,
        page_action: Optional[Callable[[AsyncPage], None]] = None,
        referer: str = "https://www.google.com/",
        retries: int = 3,
    ) -> Response:
        """Async fetch with stealth."""
        for attempt in range(retries):
            try:
                async with await async_pw() as p:
                    browser = await p.chromium.launch(
                        headless=self.headless,
                        ignore_default_args=["--enable-automation"],
                        args=[
                            "--disable-blink-features=AutomationControlled",
                            "--disable-dev-shm-usage",
                            "--disable-accelerated-2d-canvas",
                            "--disable-gpu",
                            "--no-sandbox",
                        ]
                    )

                    context = await browser.new_context(
                        user_agent=self.user_agent,
                        locale=self.locale,
                        timezone_id=self.timezone_id,
                        proxy=self.proxy,
                        viewport=self.viewport,
                        bypass_csp=self.bypass_csp,
                        extra_http_headers=self.extra_headers,
                        java_script_enabled=True,
                    )

                    page = await context.new_page()
                    page.set_default_timeout(self.timeout)

                    # Inject stealth
                    await page.add_init_script("""
                        Object.defineProperty(navigator, 'webdriver', {
                            get: () => undefined
                        });
                        Object.defineProperty(navigator, 'plugins', {
                            get: () => [1, 2, 3, 4, 5]
                        });
                        Object.defineProperty(navigator, 'languages', {
                            get: () => ['en-US', 'en']
                        });
                    """)

                    if self.block_resources:
                        async def handle_route(route):
                            if route.request.resource_type in ["font", "image", "media", "websocket"]:
                                await route.abort()
                            else:
                                await route.continue_()
                        await page.route("**/*", handle_route)

                    response = await page.goto(url, referer=referer, wait_until=self.wait_until)

                    if self.solve_cloudflare and self._is_cloudflare_challenge(page):
                        if not await self._solve_cloudflare(page):
                            raise Exception("Cloudflare challenge could not be solved")

                    try:
                        await page.wait_for_load_state("networkidle", timeout=5000)
                    except:
                        pass

                    if page_action:
                        await page_action(page)

                    content = await page.content()
                    status = response.status if response else 200
                    headers = response.headers if response else {}
                    final_url = page.url

                    await browser.close()

                    return Response(
                        content=content,
                        headers=headers,
                        status=status,
                        url=final_url,
                        ok=status < 400,
                    )

            except Exception as e:
                print(f"Attempt {attempt + 1} failed: {e}")
                if attempt == retries - 1:
                    return Response(
                        content="",
                        headers={},
                        status=0,
                        url=url,
                        ok=False,
                        error=str(e),
                    )

        return Response(
            content="",
            headers={},
            status=0,
            url=url,
            ok=False,
            error="Max retries exceeded",
        )
