"""
Regular Fetcher using Playwright.
Provides DynamicFetcher (sync) and AsyncDynamicFetcher (async) classes.
"""
from typing import Optional, Dict, Callable
from playwright.sync_api import sync_playwright, Page
from playwright.async_api import async_playwright as async_pw
from playwright.async_api import Page as AsyncPage

from .response import Response


class DynamicFetcher:
    """
    Synchronous browser automation wrapper using Playwright.
    Spins up a real Chromium browser, visits the URL, and waits for a specific state.
    """

    def __init__(
        self,
        headless: bool = True,
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

    def fetch(
        self,
        url: str,
        page_action: Optional[Callable[[Page], None]] = None,
        referer: str = "https://www.google.com/",
        retries: int = 3,
    ) -> Response:
        """
        Fetch a URL with optional page action.

        Args:
            url: The URL to visit
            page_action: Optional callable that receives the page for custom actions
            referer: Referer header to set (default: Google)
            retries: Number of retry attempts on failure

        Returns:
            Response object with content, headers, and status
        """
        for attempt in range(retries):
            try:
                with sync_playwright() as p:
                    # Launch browser
                    browser = p.chromium.launch(
                        headless=self.headless,
                        args=["--disable-blink-features=AutomationControlled"]
                    )

                    # Create context with all settings
                    context = browser.new_context(
                        user_agent=self.user_agent,
                        locale=self.locale,
                        timezone_id=self.timezone_id,
                        proxy=self.proxy,
                        viewport=self.viewport,
                        bypass_csp=self.bypass_csp,
                        extra_http_headers=self.extra_headers,
                    )

                    page = context.new_page()
                    page.set_default_timeout(self.timeout)

                    # Block unnecessary resources if enabled
                    if self.block_resources:
                        page.route("**/*", lambda route: route.abort()
                            if route.request.resource_type in ["font", "image", "media", "websocket"]
                            else route.continue_())

                    # Navigate to URL
                    response = page.goto(url, referer=referer, wait_until=self.wait_until)

                    # Wait for network idle
                    try:
                        page.wait_for_load_state("networkidle", timeout=5000)
                    except:
                        pass  # Timeout is ok, we have the content

                    # Execute custom page action if provided
                    if page_action:
                        page_action(page)

                    # Extract content
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


class AsyncDynamicFetcher:
    """
    Asynchronous browser automation wrapper using Playwright.
    """

    def __init__(
        self,
        headless: bool = True,
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

    async def fetch(
        self,
        url: str,
        page_action: Optional[Callable[[AsyncPage], None]] = None,
        referer: str = "https://www.google.com/",
        retries: int = 3,
    ) -> Response:
        """
        Async fetch a URL with optional page action.
        """
        for attempt in range(retries):
            try:
                async with await async_pw() as p:
                    # Launch browser
                    browser = await p.chromium.launch(
                        headless=self.headless,
                        args=["--disable-blink-features=AutomationControlled"]
                    )

                    # Create context
                    context = await browser.new_context(
                        user_agent=self.user_agent,
                        locale=self.locale,
                        timezone_id=self.timezone_id,
                        proxy=self.proxy,
                        viewport=self.viewport,
                        bypass_csp=self.bypass_csp,
                        extra_http_headers=self.extra_headers,
                    )

                    page = await context.new_page()
                    page.set_default_timeout(self.timeout)

                    # Block resources
                    if self.block_resources:
                        async def handle_route(route):
                            if route.request.resource_type in ["font", "image", "media", "websocket"]:
                                await route.abort()
                            else:
                                await route.continue_()
                        await page.route("**/*", handle_route)

                    # Navigate
                    response = await page.goto(url, referer=referer, wait_until=self.wait_until)

                    # Wait for network idle
                    try:
                        await page.wait_for_load_state("networkidle", timeout=5000)
                    except:
                        pass

                    # Execute custom action
                    if page_action:
                        await page_action(page)

                    # Extract
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
