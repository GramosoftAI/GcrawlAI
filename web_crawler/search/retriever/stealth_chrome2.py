"""
stealth_chrome2.py — AsyncPersistentStealthyFetcher with Context Rotation.

This version uses the ASYNC Playwright API to fully support high-concurrency
environments like FastAPI. It implements Layer 6: Context Rotation.
"""

import asyncio
import random
import logging
import os
from typing import Optional, Dict, Callable

from patchright.async_api import async_playwright, Page, Browser, BrowserContext

from .response import Response
from .stealth_chrome import (
    _StealthMixin,
    _human_pre_navigation_async,
    _human_post_navigation_async,
    _build_context_options,
    HARMFUL_ARGS,
    ALL_LAUNCH_ARGS,
    BLOCK_RESOURCE_TYPES,
    _get_random_stealth_ua,
)

logger = logging.getLogger(__name__)


class PersistentStealthyFetcher(_StealthMixin):
    """
    Pooled async stealthy browser fetcher using Context Rotation.
    """

    def __init__(
        self,
        headless: bool = True,
        user_agent: Optional[str] = None,
        locale: str = "en-US",
        timezone_id: Optional[str] = None,
        proxy: Optional[Dict] = None,
        extra_headers: Optional[Dict] = None,
        block_resources: bool = False,
        wait_until: str = "commit", # Changed to 'commit' for faster response under slow proxies
        timeout: int = 30_000, 
        solve_cloudflare: bool = True,
        use_random_fingerprint: bool = True,
    ):
        self.headless = headless
        self.user_agent = user_agent or _get_random_stealth_ua()
        self.locale = locale
        self.timezone_id = timezone_id
        self.proxy = proxy
        self.extra_headers = extra_headers or {}
        self.block_resources = block_resources
        self.wait_until = wait_until
        self.timeout = timeout
        self.solve_cloudflare = solve_cloudflare
        self.use_random_fingerprint = use_random_fingerprint

        from dotenv import load_dotenv
        load_dotenv()
        self.capmonster_key = os.getenv("CAPMONSTER_API_KEY")

        self._lock = asyncio.Lock()
        self._playwright = None
        self._browser = None

    async def _is_alive(self) -> bool:
        try:
            return (
                self._browser is not None
                and self._browser.is_connected()
            )
        except Exception:
            return False

    async def _start(self) -> None:
        if await self._is_alive():
            return

        async with self._lock:
            if await self._is_alive():
                return

            logger.info("[PersistentFetcher] Launching async browser binary.")
            if not self._playwright:
                self._playwright = await async_playwright().start()

            self._browser = await self._playwright.chromium.launch(
                headless=self.headless,
                ignore_default_args=HARMFUL_ARGS,
                args=ALL_LAUNCH_ARGS,
            )
            logger.info("[PersistentFetcher] Async browser binary ready.")

    async def _reset(self) -> None:
        """Full reset - closes the browser binary."""
        logger.warning("[PersistentFetcher] Resetting async browser binary.")
        if self._browser:
            try:
                await self._browser.close()
            except Exception:
                pass
        if self._playwright:
            try:
                await self._playwright.stop()
            except Exception:
                pass
        self._browser = None
        self._playwright = None

    async def close(self) -> None:
        async with self._lock:
            await self._reset()

    async def fetch(
        self,
        url: str,
        page_action: Optional[Callable[[Page], None]] = None,
        referer: str = "https://www.google.com/",
        retries: int = 3,
    ) -> Response:
        await self._start()

        for attempt in range(retries):
            context: Optional[BrowserContext] = None
            try:
                # ── Layer 6: Context Rotation ──
                # Fresh UA per context for maximum isolation
                current_ua = _get_random_stealth_ua()
                
                ctx_opts = _build_context_options(
                    current_ua, self.locale, self.timezone_id,
                    self.proxy, self.extra_headers or None,
                )

                if self.use_random_fingerprint:
                    width = random.randint(1366, 1920)
                    height = random.randint(768, 1080)
                    ctx_opts["viewport"] = {"width": width, "height": height}
                    ctx_opts["screen"] = {"width": width, "height": height}

                context = await self._browser.new_context(**ctx_opts)
                page = await context.new_page()
                page.set_default_timeout(self.timeout)

                # Layer 11: Advanced Deep Stealth Script Injection (Bypass CAPTCHA)
                stealth_script = """
                    // 1. Overwrite webdriver
                    Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
                    
                    // 2. Mock chrome object completely
                    window.chrome = {
                        runtime: {},
                        app: { isInstalled: false, InstallState: { DISABLED: 'disabled', INSTALLED: 'installed', NOT_INSTALLED: 'not_installed' } },
                        csi: function() {},
                        loadTimes: function() {}
                    };
                    
                    // 3. Spoof Plugins and MimeTypes
                    const mockPlugins = [
                        { name: 'Chrome PDF Plugin', filename: 'internal-pdf-viewer', description: 'Portable Document Format' },
                        { name: 'Chrome PDF Viewer', filename: 'mhjimiokj', description: '' },
                        { name: 'Native Client', filename: 'internal-nacl-plugin', description: '' }
                    ];
                    Object.defineProperty(navigator, 'plugins', { get: () => mockPlugins });
                    Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
                    
                    // 4. Spoof Permissions API to allow notifications
                    const originalQuery = window.navigator.permissions.query;
                    window.navigator.permissions.query = (parameters) => (
                        parameters.name === 'notifications' ? 
                            Promise.resolve({ state: Notification.permission }) : 
                            originalQuery(parameters)
                    );
                    
                    // 5. WebGL Spoofing (Vendor/Renderer)
                    const getParameterProxyHandler = {
                        apply: function (target, ctx, args) {
                            const param = (args || [])[0];
                            if (param === 37445) return 'Intel Inc.'; // UNMASKED_VENDOR_WEBGL
                            if (param === 37446) return 'Intel Iris OpenGL Engine'; // UNMASKED_RENDERER_WEBGL
                            return Reflect.apply(target, ctx, args);
                        }
                    };
                    const proxyWebGL = (contextName) => {
                        try {
                            const getParam = HTMLCanvasElement.prototype.getContext.call(document.createElement('canvas'), contextName).getParameter;
                            HTMLCanvasElement.prototype.getContext.call(document.createElement('canvas'), contextName).getParameter = new Proxy(getParam, getParameterProxyHandler);
                        } catch(e) {}
                    };
                    proxyWebGL('webgl');
                    proxyWebGL('webgl2');
                    
                    // 6. Canvas Fingerprint Noise
                    const originalToDataURL = HTMLCanvasElement.prototype.toDataURL;
                    HTMLCanvasElement.prototype.toDataURL = function(...args) {
                        const context = this.getContext('2d');
                        if (context) {
                            context.fillStyle = 'rgba(' + Math.floor(Math.random() * 255) + ',' + Math.floor(Math.random() * 255) + ',' + Math.floor(Math.random() * 255) + ', 0.01)';
                            context.fillRect(0, 0, 1, 1);
                        }
                        return originalToDataURL.apply(this, args);
                    };
                """
                await page.add_init_script(stealth_script)

                if self.block_resources:
                    async def _block(route):
                        if route.request.resource_type in BLOCK_RESOURCE_TYPES:
                            await route.abort()
                        else:
                            await route.continue_()
                    await page.route("**/*", _block)

                # Layer 5: navigation with commit-only check
                # This ensures we don't timeout just because a slow proxy 
                # takes long to load the whole DOM.
                response = await page.goto(url, referer=referer, wait_until="commit", timeout=20000)

                try:
                    # We just need the initial DOM for search results
                    await page.wait_for_load_state("domcontentloaded", timeout=5000)
                except Exception:
                    pass

                if self.solve_cloudflare and await self._is_cloudflare_async(page):
                    await self._solve_cloudflare_async(page)
                    try:
                        await page.wait_for_load_state("domcontentloaded", timeout=5000)
                    except Exception:
                        pass

                # ── Layer 10: Detection Handling ──
                if self._is_google_captcha(page):
                    logger.warning("[PersistentFetcher] 🛡️ CAPTCHA detected! Rotating context and IP.")
                    await context.close()
                    context = None
                    
                    # Force a new IP on retry by randomizing the proxy session string if present
                    if self.proxy and self.proxy.get("password") and "_session-" in self.proxy["password"]:
                        import re
                        new_session = "".join(random.choices("0123456789abcdef", k=8))
                        self.proxy["password"] = re.sub(r"_session-[a-zA-Z0-9]+", f"_session-{new_session}", self.proxy["password"])
                        
                    await asyncio.sleep(random.uniform(0.5, 1.5)) # Reduced jitter to speed up retry
                    continue

                if response and (response.status == 429 or "429" in str(response.status)):
                    logger.warning(f"[PersistentFetcher] 🛑 429 Detected (attempt {attempt+1}) — rotating context.")
                    await context.close()
                    context = None
                    await asyncio.sleep(random.uniform(4.0, 8.0))
                    continue

                if "google.com/search" in url:
                    try:
                        await page.wait_for_selector("#search, div.g, h3", timeout=3000)
                    except Exception:
                        pass

                content = await page.content()
                status = response.status if response else 200
                headers = dict(response.headers) if response else {}
                final_url = page.url

                await context.close()
                context = None

                logger.info(f"[PersistentFetcher] ✅ {url} (status={status})")
                return Response(content=content, headers=headers, status=status,
                                url=final_url, ok=status < 400)

            except Exception as e:
                if "ERR_TIMED_OUT" in str(e) or "Timeout" in str(e):
                    logger.warning(f"[PersistentFetcher] ⏳ Timeout on attempt {attempt+1} (IP possibly dead). Rotating...")
                else:
                    logger.error(f"[PersistentFetcher] Attempt {attempt+1} failed: {e}")
                
                if context:
                    try:
                        await context.close()
                    except Exception:
                        pass
                context = None
                
                if attempt == retries - 1:
                    logger.warning("[PersistentFetcher] All retries exhausted — resetting binary.")
                    await self._reset()
                    return Response(content="", headers={}, status=0,
                                    url=url, ok=False, error=str(e))
                
                await asyncio.sleep(random.uniform(1.0, 2.0))

        return Response(content="", headers={}, status=0, url=url,
                         ok=False, error="Max retries exhausted")


class AsyncStealthyFetcher(PersistentStealthyFetcher):
    """Alias for consistency."""
    pass
