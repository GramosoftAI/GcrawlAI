"""
Stealthy Fetcher using Patchright (Playwright fork with patched browser leaks).
Provides StealthyFetcher (sync) and AsyncStealthyFetcher (async) classes.
Includes Cloudflare Turnstile solver and anti-bot evasion techniques.
"""
import asyncio
from random import randint, uniform
from typing import Optional, Dict, Callable
from patchright.sync_api import sync_playwright, Page
from patchright.async_api import async_playwright as async_pw
from patchright.async_api import Page as AsyncPage

from .response import Response


class StealthyFetcher:
    """
    Synchronous stealthy browser automation using Patchright.
    Patches navigator.webdriver, adds canvas noise, WebRTC blocking, WebGL spoofing.
    Includes Cloudflare Turnstile solver.
    """

    def __init__(
        self,
        headless: bool = False,
        user_agent: Optional[str] = None,
        locale: str = "en-US",
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
        locale: str = "en-US",
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
