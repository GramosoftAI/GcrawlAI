"""
stealth_chrome.py — Patchright-based stealthy browser fetcher.

Rewritten to match Scrapling's (D4Vinci/Scrapling) exact stealth approach:
  • 50+ Chrome flags that make the browser indistinguishable from real Chrome
  • launch_persistent_context instead of new_context (real user profile feel)
  • browserforge-generated useragent matched to the launched Chrome version
  • NO injected JS — patchright patches navigator.webdriver at C++ level
  • color_scheme=dark / device_scale_factor=2 to pass creepjs checks
  • Bare "https://www.google.com/" referer (not a search URL)
  • Scrapling-style Cloudflare solver (detect type → click iframe precisely)

With these in place, Google should NOT show /sorry CAPTCHA at all.
The CapMonster solver is kept as a last-resort safety net only.
"""

import re
import time
import tempfile
import threading
import logging
import os
import requests
from typing import Optional, Dict, Callable

from patchright.sync_api import sync_playwright, Page
from patchright.async_api import async_playwright as async_pw
from patchright.async_api import Page as AsyncPage

from .response import Response

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Browser launch args — copied from Scrapling's constants.py
# ─────────────────────────────────────────────────────────────────────────────

# Args Playwright adds by default that HURT stealth — remove all of them
HARMFUL_ARGS = [
    "--enable-automation",         # #1 bot signal
    "--disable-popup-blocking",
    "--disable-component-update",
    "--disable-default-apps",
    "--disable-extensions",
]

# Base speed/stability flags (Scrapling DEFAULT_ARGS)
DEFAULT_ARGS = [
    "--no-pings",
    "--no-first-run",
    "--disable-infobars",
    "--disable-breakpad",
    "--no-service-autorun",
    "--homepage=about:blank",
    "--password-store=basic",
    "--disable-hang-monitor",
    "--no-default-browser-check",
    "--disable-session-crashed-bubble",
    "--disable-search-engine-choice-screen",
]

# Stealth-specific flags (Scrapling STEALTH_ARGS)
STEALTH_ARGS = [
    "--test-type",                  # suppresses automation UI without the --enable-automation signal
    "--lang=en-US",
    "--mute-audio",
    "--disable-sync",
    "--hide-scrollbars",
    "--disable-logging",
    "--start-maximized",            # headless window-size detection bypass
    "--enable-async-dns",
    "--accept-lang=en-US",
    "--use-mock-keychain",
    "--disable-translate",
    "--disable-voice-input",
    "--window-position=0,0",
    "--disable-wake-on-wifi",
    "--ignore-gpu-blocklist",
    "--enable-tcp-fast-open",
    "--enable-web-bluetooth",
    "--disable-cloud-import",
    "--disable-print-preview",
    "--disable-dev-shm-usage",
    "--metrics-recording-only",
    "--disable-crash-reporter",
    "--disable-partial-raster",
    "--disable-gesture-typing",
    "--disable-checker-imaging",
    "--disable-prompt-on-repost",
    "--force-color-profile=srgb",
    "--font-render-hinting=none",
    "--aggressive-cache-discard",
    "--disable-cookie-encryption",
    "--disable-domain-reliability",
    "--disable-threaded-animation",
    "--disable-threaded-scrolling",
    "--enable-simple-cache-backend",
    "--disable-background-networking",
    "--enable-surface-synchronization",
    "--disable-image-animation-resync",
    "--disable-renderer-backgrounding",
    "--disable-ipc-flooding-protection",
    "--prerender-from-omnibox=disabled",
    "--safebrowsing-disable-auto-update",
    "--disable-offer-upload-credit-cards",
    "--disable-background-timer-throttling",
    "--disable-new-content-rendering-timeout",
    "--run-all-compositor-stages-before-draw",
    "--disable-client-side-phishing-detection",
    "--disable-backgrounding-occluded-windows",
    "--disable-layer-tree-host-memory-pressure",
    "--autoplay-policy=user-gesture-required",
    "--disable-offer-store-unmasked-wallet-cards",
    "--disable-blink-features=AutomationControlled",
    "--disable-component-extensions-with-background-pages",
    # TrustTokens enables privacy-preserving tokens — real Chrome behaviour
    "--enable-features=NetworkService,NetworkServiceInProcess,TrustTokens,TrustTokensAlwaysAllowIssuance",
    # Makes pointer/hover type look like a real desktop mouse (not automation)
    "--blink-settings=primaryHoverType=2,availableHoverTypes=2,primaryPointerType=4,availablePointerTypes=4",
    "--disable-features=AudioServiceOutOfProcess,TranslateUI,BlinkGenPropertyTrees",
]

ALL_LAUNCH_ARGS = DEFAULT_ARGS + STEALTH_ARGS

# Resource types to block when block_resources=True
BLOCK_RESOURCE_TYPES = {
    "font", "image", "media", "beacon", "object",
    "imageset", "texttrack", "websocket", "csp_report", "stylesheet",
}


# ─────────────────────────────────────────────────────────────────────────────
# Useragent — matched to the actual Chrome version patchright ships
# ─────────────────────────────────────────────────────────────────────────────

def _get_stealth_useragent() -> str:
    """
    Generate a real Chrome useragent via browserforge.
    A mismatched version (e.g. Chrome/120 when patchright ships Chrome/124+)
    is a fingerprinting signal on its own.
    """
    try:
        import platform
        from browserforge.headers import Browser, HeaderGenerator
        os_name = {"Windows": "windows", "Darwin": "macos", "Linux": "linux"}.get(
            platform.system(), "windows"
        )
        headers = HeaderGenerator(
            browser=[Browser(name="chrome", min_version=124, max_version=124)],
            os=os_name,
            device="desktop",
        ).generate()
        ua = headers.get("User-Agent", "")
        if ua:
            return ua
    except Exception as e:
        logger.debug(f"[stealth] browserforge UA generation failed: {e}")

    # Hardcoded fallback — keep in sync with patchright's bundled Chrome
    return (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )


_STEALTH_UA: str = _get_stealth_useragent()


# ─────────────────────────────────────────────────────────────────────────────
# Context options builder — Scrapling-compatible
# ─────────────────────────────────────────────────────────────────────────────

def _build_context_options(
    user_agent: str,
    locale: str,
    timezone_id: Optional[str],
    proxy: Optional[Dict],
    extra_headers: Optional[Dict],
) -> Dict:
    """
    Build Playwright persistent-context options the Scrapling way.

    Critical additions vs naïve approach:
      color_scheme=dark      → bypasses creepjs prefersLightColor check
      device_scale_factor=2  → realistic Retina-style display
      screen/viewport 1920   → consistent with --start-maximized
      ignore_https_errors    → avoids TLS-related navigation failures
    """
    opts: Dict = {
        "color_scheme": "dark",
        "device_scale_factor": 2,
        "is_mobile": False,
        "has_touch": False,
        "service_workers": "allow",
        "ignore_https_errors": True,
        "screen": {"width": 1920, "height": 1080},
        "viewport": {"width": 1920, "height": 1080},
        "user_agent": user_agent,
        "locale": locale,
        "java_script_enabled": True,
    }
    if timezone_id:
        opts["timezone_id"] = timezone_id
    if proxy:
        opts["proxy"] = proxy
    if extra_headers:
        opts["extra_http_headers"] = extra_headers
    return opts


# ─────────────────────────────────────────────────────────────────────────────
# CapMonster solver (last-resort only — with correct stealth you rarely need it)
# ─────────────────────────────────────────────────────────────────────────────

def _capmonster_solve(
    api_key: str,
    website_url: str,
    site_key: str,
    poll_interval: float = 3.0,
    max_polls: int = 40,
) -> Optional[str]:
    """Submit reCAPTCHA v2 job to CapMonster and return the token."""
    try:
        resp = requests.post(
            "https://api.capmonster.cloud/createTask",
            json={
                "clientKey": api_key,
                "task": {
                    "type": "RecaptchaV2TaskProxyless",
                    "websiteURL": website_url,
                    "websiteKey": site_key,
                },
            },
            timeout=15,
        ).json()
    except Exception as e:
        logger.error(f"[CapMonster] createTask request failed: {e}")
        return None

    if resp.get("errorId") != 0:
        logger.error(f"[CapMonster] createTask error: {resp}")
        return None

    task_id = resp["taskId"]
    logger.info(f"[CapMonster] Task {task_id} created — polling…")

    for i in range(max_polls):
        time.sleep(poll_interval)
        try:
            res = requests.post(
                "https://api.capmonster.cloud/getTaskResult",
                json={"clientKey": api_key, "taskId": task_id},
                timeout=10,
            ).json()
        except Exception as e:
            logger.warning(f"[CapMonster] Poll {i+1} request failed: {e}")
            continue

        status = res.get("status")
        if status == "ready":
            token = res.get("solution", {}).get("gRecaptchaResponse")
            if token:
                logger.info("[CapMonster] ✅ Token received.")
                return token
            logger.error(f"[CapMonster] Ready but no token: {res}")
            return None
        elif status == "processing":
            continue
        else:
            logger.error(f"[CapMonster] Unexpected: {res}")
            return None

    logger.error("[CapMonster] Polling timed out.")
    return None


def _extract_sitekey(page: Page) -> Optional[str]:
    """Multi-strategy sitekey extraction from Google /sorry page."""
    try:
        el = page.locator(".g-recaptcha").first
        if el.count() > 0:
            k = el.get_attribute("data-sitekey", timeout=2000)
            if k:
                return k
    except Exception:
        pass
    try:
        el = page.locator("[data-sitekey]").first
        if el.count() > 0:
            k = el.get_attribute("data-sitekey", timeout=2000)
            if k:
                return k
    except Exception:
        pass
    try:
        html = page.content()
        m = re.search(r'"sitekey"\s*:\s*"([^"]+)"', html) or \
            re.search(r"data-sitekey=[\"']([^\"']+)[\"']", html)
        if m:
            return m.group(1)
    except Exception:
        pass
    return None


def _inject_and_submit(page: Page, token: str) -> None:
    """Inject token via grecaptcha callback, then fall back to form submit."""
    page.evaluate(
        """(token) => {
            var ta = document.getElementById('g-recaptcha-response')
                  || document.querySelector('[name="g-recaptcha-response"]');
            if (!ta) {
                ta = document.createElement('textarea');
                ta.id = 'g-recaptcha-response';
                ta.name = 'g-recaptcha-response';
                ta.style.cssText = 'display:none;width:250px;height:40px;';
                var f = document.forms[0];
                if (f) f.appendChild(ta);
            }
            ta.value = token;

            var triggered = false;

            // Method A: data-callback attribute
            var widget = document.querySelector('[data-callback]');
            if (widget) {
                var cbName = widget.getAttribute('data-callback');
                if (cbName && typeof window[cbName] === 'function') {
                    try { window[cbName](token); triggered = true; } catch(e) {}
                }
            }

            // Method B: ___grecaptcha_cfg internal API
            if (!triggered && window.___grecaptcha_cfg && window.___grecaptcha_cfg.clients) {
                Object.values(window.___grecaptcha_cfg.clients).forEach(function(client) {
                    Object.values(client).forEach(function(w) {
                        if (w && typeof w.callback === 'function' && !triggered) {
                            try { w.callback(token); triggered = true; } catch(e) {}
                        }
                    });
                });
            }

            // Method C: direct form submit
            if (!triggered) {
                var form = document.forms[0];
                if (form) { try { form.submit(); } catch(e) {} }
            }
        }""",
        token,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Shared mixin — detection + solving
# ─────────────────────────────────────────────────────────────────────────────

_CF_PATTERN = re.compile(r"^https?://challenges\.cloudflare\.com/cdn-cgi/challenge-platform/.*")


class _StealthMixin:

    # ── Detection ─────────────────────────────────────────────────────────────

    def _is_google_captcha(self, page: Page) -> bool:
        return "/sorry/" in page.url

    def _is_hard_blocked(self, page: Page) -> bool:
        """IP is hard-blocked when /sorry shows NO reCAPTCHA widget."""
        try:
            if "/sorry/" not in page.url:
                return False
            html = page.content()
            return not any(kw in html for kw in ("g-recaptcha", "data-sitekey", "grecaptcha"))
        except Exception:
            return False

    def _is_cloudflare(self, page: Page) -> bool:
        try:
            if "Just a moment" in page.title():
                return True
            html = page.content()
            if "challenges.cloudflare.com" in html:
                return True
            for frame in page.frames:
                if "challenges.cloudflare.com" in frame.url:
                    return True
        except Exception:
            pass
        return False

    # ── Solvers ───────────────────────────────────────────────────────────────

    def _solve_cloudflare(self, page: Page) -> bool:
        """
        Scrapling-style Cloudflare solver:
          1. Detect challenge type from cType JS variable
          2. For non-interactive: just wait
          3. For all others: click the Turnstile iframe at precise coordinates
        """
        logger.warning("[CF] Cloudflare detected — solving.")

        try:
            html = page.content()
        except Exception:
            html = ""

        # Detect challenge type
        challenge_type = None
        for ctype in ("non-interactive", "managed", "interactive"):
            if f"cType: '{ctype}'" in html:
                challenge_type = ctype
                break
        if challenge_type is None and "challenges.cloudflare.com/turnstile/v" in html:
            challenge_type = "embedded"

        logger.info(f"[CF] Type: {challenge_type}")

        if challenge_type == "non-interactive":
            for _ in range(30):
                try:
                    if "<title>Just a moment...</title>" not in page.content():
                        logger.info("[CF] ✅ Non-interactive solved.")
                        return True
                except Exception:
                    pass
                page.wait_for_timeout(1000)
            return False

        # Interactive/managed/embedded: click the iframe checkbox
        from random import randint
        page.wait_for_timeout(2000)

        outer_box = None
        iframe = page.frame(url=_CF_PATTERN)
        if iframe:
            try:
                outer_box = iframe.frame_element().bounding_box()
            except Exception:
                pass

        if not outer_box:
            box_selector = (
                ".main-content p+div>div>div"
                if challenge_type not in (None, "embedded")
                else "#cf_turnstile div, #cf-turnstile div, .turnstile>div>div"
            )
            try:
                outer_box = page.locator(box_selector).last.bounding_box()
            except Exception:
                pass

        if outer_box:
            # Scrapling uses randint(26,28) / randint(25,27) — precise, not random big range
            cx = outer_box["x"] + randint(26, 28)
            cy = outer_box["y"] + randint(25, 27)
            page.mouse.click(cx, cy, delay=randint(100, 200))
            logger.info(f"[CF] Clicked at ({cx:.0f}, {cy:.0f})")

            # Poll every 100ms for up to 10s (Scrapling's approach)
            for _ in range(100):
                page.wait_for_timeout(100)
                try:
                    if "<title>Just a moment...</title>" not in page.content():
                        logger.info("[CF] ✅ Cloudflare solved!")
                        return True
                except Exception:
                    pass

        result = not self._is_cloudflare(page)
        if not result:
            logger.warning("[CF] ❌ Could not solve Cloudflare.")
        return result

    def _solve_google_captcha(self, page: Page, original_url: str = None) -> bool:
        """
        Last-resort solver. With correct stealth fingerprinting this should
        rarely be called — Google should not show CAPTCHA at all.
        """
        logger.warning("[CAPTCHA] Google /sorry — attempting CapMonster solve.")

        if not getattr(self, "capmonster_key", None):
            logger.error("[CAPTCHA] CAPMONSTER_API_KEY not set.")
            return False

        if self._is_hard_blocked(page):
            # Raise explicitly so google_search.py _force_rotate_fetcher() is triggered.
            # Silent `return False` was hiding hard blocks from the caller.
            raise Exception("Google hard block — IP banned, no CAPTCHA widget shown")

        page.wait_for_timeout(2000)
        site_key = _extract_sitekey(page)
        if not site_key:
            logger.error("[CAPTCHA] No sitekey found — treating as hard block.")
            return False

        logger.info(f"[CAPTCHA] Sitekey: {site_key}")
        token = _capmonster_solve(
            api_key=self.capmonster_key,
            website_url=page.url,
            site_key=site_key,
        )
        if not token:
            logger.error("[CAPTCHA] No token from CapMonster.")
            return False

        _inject_and_submit(page, token)

        # Wait strategies in order
        try:
            page.wait_for_url(lambda u: "/sorry/" not in u, timeout=15_000)
        except Exception:
            pass
        if not self._is_google_captcha(page):
            logger.info("[CAPTCHA] ✅ Bypassed!")
            return True

        try:
            page.wait_for_load_state("domcontentloaded", timeout=10_000)
        except Exception:
            pass
        if not self._is_google_captcha(page):
            logger.info("[CAPTCHA] ✅ Bypassed (load state)!")
            return True

        try:
            page.evaluate("() => { var f=document.forms[0]; if(f) f.submit(); }")
            page.wait_for_load_state("domcontentloaded", timeout=10_000)
        except Exception:
            pass
        if not self._is_google_captcha(page):
            logger.info("[CAPTCHA] ✅ Bypassed (form submit)!")
            return True

        if original_url:
            try:
                page.goto(original_url, wait_until="domcontentloaded", timeout=30_000)
                time.sleep(1)
            except Exception:
                pass

        success = not self._is_google_captcha(page)
        if success:
            logger.info("[CAPTCHA] ✅ Bypassed via re-navigation!")
        else:
            logger.error("[CAPTCHA] ❌ All strategies failed. Use a residential proxy.")
        return success


# ─────────────────────────────────────────────────────────────────────────────
# StealthyFetcher  (stateless — new browser per call)
# ─────────────────────────────────────────────────────────────────────────────

class StealthyFetcher(_StealthMixin):
    """One-shot stealthy fetcher. For multiple calls use PersistentStealthyFetcher."""

    def __init__(
        self,
        headless: bool = True,
        user_agent: Optional[str] = None,
        locale: str = "en-US",
        timezone_id: Optional[str] = None,
        proxy: Optional[Dict] = None,
        extra_headers: Optional[Dict] = None,
        block_resources: bool = False,
        wait_until: str = "domcontentloaded",
        timeout: int = 60_000,
        solve_cloudflare: bool = True,
    ):
        self.headless = headless
        self.user_agent = user_agent or _STEALTH_UA
        self.locale = locale
        self.timezone_id = timezone_id
        self.proxy = proxy
        self.extra_headers = extra_headers or {}
        self.block_resources = block_resources
        self.wait_until = wait_until
        self.timeout = timeout
        self.solve_cloudflare = solve_cloudflare
        from dotenv import load_dotenv
        load_dotenv()
        self.capmonster_key = os.getenv("CAPMONSTER_API_KEY")

    def fetch(
        self,
        url: str,
        page_action: Optional[Callable[[Page], None]] = None,
        referer: str = "https://www.google.com/",
        retries: int = 3,
    ) -> Response:
        for attempt in range(retries):
            try:
                with sync_playwright() as p:
                    ctx_opts = _build_context_options(
                        self.user_agent, self.locale, self.timezone_id,
                        self.proxy, self.extra_headers or None,
                    )
                    context = p.chromium.launch_persistent_context(
                        user_data_dir=tempfile.mkdtemp(),
                        headless=self.headless,
                        ignore_default_args=HARMFUL_ARGS,
                        args=ALL_LAUNCH_ARGS,
                        **ctx_opts,
                    )
                    page = context.new_page()
                    page.set_default_timeout(self.timeout)

                    if self.block_resources:
                        page.route("**/*", lambda r: r.abort()
                            if r.request.resource_type in BLOCK_RESOURCE_TYPES else r.continue_())

                    response = page.goto(url, referer=referer, wait_until=self.wait_until)
                    try:
                        page.wait_for_load_state("load")
                        page.wait_for_load_state("domcontentloaded")
                    except Exception:
                        pass

                    if self.solve_cloudflare and self._is_cloudflare(page):
                        self._solve_cloudflare(page)
                        try:
                            page.wait_for_load_state("domcontentloaded")
                        except Exception:
                            pass

                    if self._is_google_captcha(page):
                        if not self._solve_google_captcha(page, original_url=url):
                            raise Exception("Google CAPTCHA could not be solved")

                    if page_action:
                        page_action(page)

                    content = page.content()
                    status = response.status if response else 200
                    headers = dict(response.headers) if response else {}
                    final_url = page.url
                    context.close()

                    return Response(content=content, headers=headers, status=status,
                                    url=final_url, ok=status < 400)

            except Exception as e:
                logger.error(f"[StealthyFetcher] Attempt {attempt+1} failed: {e}")
                if attempt == retries - 1:
                    return Response(content="", headers={}, status=0, url=url,
                                    ok=False, error=str(e))

        return Response(content="", headers={}, status=0, url=url,
                        ok=False, error="Max retries exceeded")


# ─────────────────────────────────────────────────────────────────────────────
# AsyncStealthyFetcher
# ─────────────────────────────────────────────────────────────────────────────

class AsyncStealthyFetcher(_StealthMixin):

    def __init__(
        self,
        headless: bool = True,
        user_agent: Optional[str] = None,
        locale: str = "en-US",
        timezone_id: Optional[str] = None,
        proxy: Optional[Dict] = None,
        extra_headers: Optional[Dict] = None,
        block_resources: bool = False,
        wait_until: str = "domcontentloaded",
        timeout: int = 60_000,
        solve_cloudflare: bool = True,
    ):
        self.headless = headless
        self.user_agent = user_agent or _STEALTH_UA
        self.locale = locale
        self.timezone_id = timezone_id
        self.proxy = proxy
        self.extra_headers = extra_headers or {}
        self.block_resources = block_resources
        self.wait_until = wait_until
        self.timeout = timeout
        self.solve_cloudflare = solve_cloudflare
        from dotenv import load_dotenv
        load_dotenv()
        self.capmonster_key = os.getenv("CAPMONSTER_API_KEY")

    async def fetch(
        self,
        url: str,
        page_action: Optional[Callable[[AsyncPage], None]] = None,
        referer: str = "https://www.google.com/",
        retries: int = 3,
    ) -> Response:
        import asyncio
        for attempt in range(retries):
            try:
                async with await async_pw() as p:
                    ctx_opts = _build_context_options(
                        self.user_agent, self.locale, self.timezone_id,
                        self.proxy, self.extra_headers or None,
                    )
                    context = await p.chromium.launch_persistent_context(
                        user_data_dir=tempfile.mkdtemp(),
                        headless=self.headless,
                        ignore_default_args=HARMFUL_ARGS,
                        args=ALL_LAUNCH_ARGS,
                        **ctx_opts,
                    )
                    page = await context.new_page()
                    page.set_default_timeout(self.timeout)

                    if self.block_resources:
                        async def _block(route):
                            if route.request.resource_type in BLOCK_RESOURCE_TYPES:
                                await route.abort()
                            else:
                                await route.continue_()
                        await page.route("**/*", _block)

                    response = await page.goto(url, referer=referer, wait_until=self.wait_until)
                    try:
                        await page.wait_for_load_state("load")
                        await page.wait_for_load_state("domcontentloaded")
                    except Exception:
                        pass

                    loop = asyncio.get_event_loop()
                    if self.solve_cloudflare and self._is_cloudflare(page):
                        await loop.run_in_executor(None, self._solve_cloudflare, page)
                        try:
                            await page.wait_for_load_state("domcontentloaded")
                        except Exception:
                            pass

                    if self._is_google_captcha(page):
                        solved = await loop.run_in_executor(
                            None, lambda: self._solve_google_captcha(page, original_url=url)
                        )
                        if not solved:
                            raise Exception("Google CAPTCHA could not be solved")

                    if page_action:
                        await page_action(page)

                    content = await page.content()
                    status = response.status if response else 200
                    headers = dict(response.headers) if response else {}
                    final_url = page.url
                    await context.close()

                    return Response(content=content, headers=headers, status=status,
                                    url=final_url, ok=status < 400)

            except Exception as e:
                logger.error(f"[AsyncStealthyFetcher] Attempt {attempt+1} failed: {e}")
                if attempt == retries - 1:
                    return Response(content="", headers={}, status=0, url=url,
                                    ok=False, error=str(e))

        return Response(content="", headers={}, status=0, url=url,
                        ok=False, error="Max retries exceeded")


# ─────────────────────────────────────────────────────────────────────────────
# PersistentStealthyFetcher — ONE browser session reused across all calls
# ─────────────────────────────────────────────────────────────────────────────

class PersistentStealthyFetcher(_StealthMixin):
    """
    Keeps a single persistent Chromium context alive across all fetch() calls.
    This is equivalent to Scrapling's StealthySession.

    The persistent context means cookies, localStorage, and browser history
    survive between pages — exactly how a real user's browser behaves.
    Google's bot detection is primarily fingerprint-based (browser flags,
    UA, JS APIs), so with the correct stealth args it should not CAPTCHA at all.
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
        wait_until: str = "domcontentloaded",
        timeout: int = 180_000,
        solve_cloudflare: bool = True,
    ):
        self.headless = headless
        self.user_agent = user_agent or _STEALTH_UA
        self.locale = locale
        self.timezone_id = timezone_id
        self.proxy = proxy
        self.extra_headers = extra_headers or {}
        self.block_resources = block_resources
        self.wait_until = wait_until
        self.timeout = timeout
        self.solve_cloudflare = solve_cloudflare

        from dotenv import load_dotenv
        load_dotenv()
        self.capmonster_key = os.getenv("CAPMONSTER_API_KEY")

        self._lock = threading.Lock()
        self._playwright = None
        self._context = None
        self._user_data_dir = tempfile.mkdtemp()

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def _is_alive(self) -> bool:
        try:
            return (
                self._context is not None
                and self._context.browser is not None
                and self._context.browser.is_connected()
            )
        except Exception:
            return False

    def _start(self) -> None:
        if self._is_alive():
            return

        logger.info("[PersistentFetcher] Launching browser session.")
        self._playwright = sync_playwright().start()

        ctx_opts = _build_context_options(
            self.user_agent, self.locale, self.timezone_id,
            self.proxy, self.extra_headers or None,
        )

        # launch_persistent_context = same as a real Chrome profile
        # Cookies and session state survive between tabs and navigations
        self._context = self._playwright.chromium.launch_persistent_context(
            user_data_dir=self._user_data_dir,
            headless=self.headless,
            ignore_default_args=HARMFUL_ARGS,
            args=ALL_LAUNCH_ARGS,
            **ctx_opts,
        )
        logger.info("[PersistentFetcher] Browser session ready.")

    def _reset(self) -> None:
        logger.warning("[PersistentFetcher] Resetting browser session.")
        for obj, method in [(self._context, "close"), (self._playwright, "stop")]:
            try:
                if obj:
                    getattr(obj, method)()
            except Exception:
                pass
        self._context = None
        self._playwright = None
        self._user_data_dir = tempfile.mkdtemp()   # fresh profile on reset

    def close(self) -> None:
        with self._lock:
            self._reset()

    # ── Main fetch ────────────────────────────────────────────────────────────

    def fetch(
        self,
        url: str,
        page_action: Optional[Callable[[Page], None]] = None,
        referer: str = "https://www.google.com/",   # bare — NOT a search URL
        retries: int = 3,
    ) -> Response:
        with self._lock:
            for attempt in range(retries):
                page = None
                try:
                    self._start()
                    page = self._context.new_page()
                    page.set_default_timeout(self.timeout)
                    # NO add_init_script — patchright patches at C++ level

                    if self.block_resources:
                        page.route("**/*", lambda r: r.abort()
                            if r.request.resource_type in BLOCK_RESOURCE_TYPES else r.continue_())

                    response = page.goto(url, referer=referer, wait_until=self.wait_until)

                    # Scrapling's _wait_for_page_stability equivalent
                    try:
                        page.wait_for_load_state("load")
                    except Exception:
                        pass
                    try:
                        page.wait_for_load_state("domcontentloaded")
                    except Exception:
                        pass

                    if self.solve_cloudflare and self._is_cloudflare(page):
                        self._solve_cloudflare(page)
                        try:
                            page.wait_for_load_state("domcontentloaded")
                        except Exception:
                            pass

                    if self._is_google_captcha(page):
                        logger.warning("[PersistentFetcher] Google CAPTCHA — solving.")
                        if not self._solve_google_captcha(page, original_url=url):
                            raise Exception("Google CAPTCHA could not be solved")

                    if page_action:
                        page_action(page)

                    content = page.content()
                    status = response.status if response else 200
                    headers = dict(response.headers) if response else {}
                    final_url = page.url
                    page.close()

                    logger.info(f"[PersistentFetcher] ✅ {url} (status={status})")
                    return Response(content=content, headers=headers, status=status,
                                    url=final_url, ok=status < 400)

                except Exception as e:
                    logger.error(f"[PersistentFetcher] Attempt {attempt+1} failed: {e}")
                    try:
                        if page:
                            page.close()
                    except Exception:
                        pass

                    if attempt == retries - 1:
                        logger.warning("[PersistentFetcher] All retries exhausted — resetting.")
                        self._reset()
                        return Response(content="", headers={}, status=0,
                                        url=url, ok=False, error=str(e))

            return Response(content="", headers={}, status=0, url=url,
                            ok=False, error="Max retries exceeded")