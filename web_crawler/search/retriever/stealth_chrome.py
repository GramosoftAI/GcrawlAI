"""
stealth_chrome.py — Patchright-based stealthy browser fetcher.
Dual-mode (Sync/Async) support.
"""

import re
import time
import random
import tempfile
import threading
import logging
import os
import requests
import asyncio
from typing import Optional, Dict, Callable, Any, List

from patchright.sync_api import sync_playwright, Page
from patchright.async_api import async_playwright as async_pw
from patchright.async_api import Page as AsyncPage

from .response import Response

logger = logging.getLogger(__name__)

# Constants
HARMFUL_ARGS = ["--enable-automation", "--disable-popup-blocking", "--disable-component-update", "--disable-default-apps", "--disable-extensions"]
DEFAULT_ARGS = ["--no-pings", "--no-first-run", "--disable-infobars", "--disable-breakpad", "--no-service-autorun", "--homepage=about:blank", "--password-store=basic", "--disable-hang-monitor", "--no-default-browser-check", "--disable-session-crashed-bubble", "--disable-search-engine-choice-screen"]
STEALTH_ARGS = ["--test-type", "--lang=en-US", "--mute-audio", "--disable-sync", "--hide-scrollbars", "--disable-logging", "--start-maximized", "--enable-async-dns", "--accept-lang=en-US", "--use-mock-keychain", "--disable-translate", "--disable-voice-input", "--window-position=0,0", "--disable-wake-on-wifi", "--ignore-gpu-blocklist", "--enable-tcp-fast-open", "--enable-web-bluetooth", "--disable-cloud-import", "--disable-print-preview", "--disable-dev-shm-usage", "--disable-crash-reporter", "--disable-partial-raster", "--disable-gesture-typing", "--disable-checker-imaging", "--disable-prompt-on-repost", "--force-color-profile=srgb", "--font-render-hinting=none", "--aggressive-cache-discard", "--disable-domain-reliability", "--disable-threaded-animation", "--disable-threaded-scrolling", "--enable-simple-cache-backend", "--disable-background-networking", "--enable-surface-synchronization", "--disable-image-animation-resync", "--disable-renderer-backgrounding", "--disable-ipc-flooding-protection", "--prerender-from-omnibox=disabled", "--safebrowsing-disable-auto-update", "--disable-offer-upload-credit-cards", "--disable-background-timer-throttling", "--disable-new-content-rendering-timeout", "--run-all-compositor-stages-before-draw", "--disable-client-side-phishing-detection", "--disable-backgrounding-occluded-windows", "--disable-layer-tree-host-memory-pressure", "--autoplay-policy=user-gesture-required", "--disable-offer-store-unmasked-wallet-cards", "--disable-blink-features=AutomationControlled", "--disable-component-extensions-with-background-pages", "--enable-features=NetworkService,NetworkServiceInProcess,TrustTokens,TrustTokensAlwaysAllowIssuance", "--blink-settings=primaryHoverType=2,availableHoverTypes=2,primaryPointerType=4,availablePointerTypes=4", "--disable-features=AudioServiceOutOfProcess,TranslateUI,BlinkGenPropertyTrees"]
ALL_LAUNCH_ARGS = DEFAULT_ARGS + STEALTH_ARGS
BLOCK_RESOURCE_TYPES = {"font", "image", "media", "beacon", "object", "imageset", "texttrack", "websocket", "csp_report", "stylesheet"}

# User Agent Pool
_CHROME_UA_POOL = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36 Edg/131.0.0.0",
]

def _get_random_stealth_ua() -> str:
    return random.choice(_CHROME_UA_POOL)

_STEALTH_UA: str = _get_random_stealth_ua()

def _build_stealth_headers(user_agent: str) -> Dict[str, str]:
    m = re.search(r"Chrome/(\d+)", user_agent)
    major = m.group(1) if m else "131"
    return {
        "Sec-CH-UA": f'"Chromium";v="{major}", "Google Chrome";v="{major}", "Not-A.Brand";v="99"',
        "Sec-CH-UA-Mobile": "?0",
        "Sec-CH-UA-Platform": '"Windows"' if "Windows" in user_agent else '"macOS"',
        "Accept-Language": "en-US,en;q=0.9",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-User": "?1",
        "Sec-Fetch-Dest": "document",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
    }

def _build_context_options(user_agent: str, locale: str, timezone_id: Optional[str], proxy: Optional[Dict], extra_headers: Optional[Dict]) -> Dict:
    stealth_hdrs = _build_stealth_headers(user_agent)
    if extra_headers: stealth_hdrs.update(extra_headers)
    opts = {
        "color_scheme": "dark", "device_scale_factor": 2, "is_mobile": False, "has_touch": False,
        "service_workers": "allow", "ignore_https_errors": True,
        "screen": {"width": 1920, "height": 1080}, "viewport": {"width": 1920, "height": 1080},
        "user_agent": user_agent, "locale": locale, "java_script_enabled": True, "extra_http_headers": stealth_hdrs,
    }
    if timezone_id: opts["timezone_id"] = timezone_id
    if proxy: opts["proxy"] = proxy
    return opts

# Human Signals - Sync
def _human_pre_navigation(page: Page) -> None:
    try:
        x, y = random.randint(400, 900), random.randint(200, 500)
        for _ in range(random.randint(3, 6)):
            x = max(100, min(1820, x + random.randint(-120, 120)))
            y = max(50, min(1000, y + random.randint(-80, 80)))
            page.mouse.move(x, y, steps=random.randint(4, 10))
        page.wait_for_timeout(random.randint(600, 1200))
    except Exception: pass

def _human_post_navigation(page: Page) -> None:
    try:
        page.wait_for_timeout(random.randint(200, 600))
        page.mouse.wheel(0, random.randint(80, 350))
        page.wait_for_timeout(random.randint(150, 400))
        if random.random() < 0.6:
            page.mouse.move(random.randint(300, 1200), random.randint(200, 700), steps=random.randint(3, 8))
    except Exception: pass

# Human Signals - Async
async def _human_pre_navigation_async(page: AsyncPage) -> None:
    try:
        x, y = random.randint(400, 900), random.randint(200, 500)
        for _ in range(random.randint(3, 6)):
            x = max(100, min(1820, x + random.randint(-120, 120)))
            y = max(50, min(1000, y + random.randint(-80, 80)))
            await page.mouse.move(x, y, steps=random.randint(4, 10))
        await page.wait_for_timeout(random.randint(600, 1200))
    except Exception: pass

async def _human_post_navigation_async(page: AsyncPage) -> None:
    try:
        await page.wait_for_timeout(random.randint(200, 600))
        await page.mouse.wheel(0, random.randint(80, 350))
        await page.wait_for_timeout(random.randint(150, 400))
        if random.random() < 0.6:
            await page.mouse.move(random.randint(300, 1200), random.randint(200, 700), steps=random.randint(3, 8))
    except Exception: pass

def _capmonster_solve(api_key: str, website_url: str, site_key: str) -> Optional[str]:
    try:
        resp = requests.post("https://api.capmonster.cloud/createTask", json={"clientKey": api_key, "task": {"type": "RecaptchaV2TaskProxyless", "websiteURL": website_url, "websiteKey": site_key}}, timeout=15).json()
        if resp.get("errorId") != 0: return None
        task_id = resp["taskId"]
        for _ in range(40):
            time.sleep(3)
            res = requests.post("https://api.capmonster.cloud/getTaskResult", json={"clientKey": api_key, "taskId": task_id}, timeout=10).json()
            if res.get("status") == "ready": return res.get("solution", {}).get("gRecaptchaResponse")
    except Exception: pass
    return None

def _extract_sitekey(page: Page) -> Optional[str]:
    try:
        for selector in [".g-recaptcha", "[data-sitekey]"]:
            el = page.locator(selector).first
            if el.count() > 0:
                k = el.get_attribute("data-sitekey", timeout=2000)
                if k: return k
    except Exception: pass
    return None

async def _extract_sitekey_async(page: AsyncPage) -> Optional[str]:
    try:
        for selector in [".g-recaptcha", "[data-sitekey]"]:
            el = page.locator(selector).first
            if await el.count() > 0:
                k = await el.get_attribute("data-sitekey", timeout=2000)
                if k: return k
    except Exception: pass
    return None

def _inject_and_submit(page: Page, token: str) -> None:
    page.evaluate("(token) => { var ta = document.getElementById('g-recaptcha-response') || document.querySelector('[name=\"g-recaptcha-response\"]'); if (!ta) { ta = document.createElement('textarea'); ta.id = 'g-recaptcha-response'; ta.name = 'g-recaptcha-response'; ta.style.cssText = 'display:none;'; document.forms[0].appendChild(ta); } ta.value = token; var form = document.forms[0]; if (form) form.submit(); }", token)

async def _inject_and_submit_async(page: AsyncPage, token: str) -> None:
    await page.evaluate("(token) => { var ta = document.getElementById('g-recaptcha-response') || document.querySelector('[name=\"g-recaptcha-response\"]'); if (!ta) { ta = document.createElement('textarea'); ta.id = 'g-recaptcha-response'; ta.name = 'g-recaptcha-response'; ta.style.cssText = 'display:none;'; document.forms[0].appendChild(ta); } ta.value = token; var form = document.forms[0]; if (form) form.submit(); }", token)

_CF_PATTERN = re.compile(r"^https?://challenges\.cloudflare\.com/cdn-cgi/challenge-platform/.*")

class _StealthMixin:
    def _is_google_captcha(self, page: Any) -> bool: return "/sorry/" in page.url
    
    async def _is_cloudflare_async(self, page: AsyncPage) -> bool:
        try:
            if "Just a moment" in await page.title(): return True
            content = await page.content()
            if "challenges.cloudflare.com" in content: return True
        except Exception: pass
        return False

    def _is_cloudflare(self, page: Page) -> bool:
        try:
            if "Just a moment" in page.title(): return True
            if "challenges.cloudflare.com" in page.content(): return True
        except Exception: pass
        return False

    def _solve_cloudflare(self, page: Page) -> bool:
        logger.warning("[CF] Sync solver starting.")
        try:
            page.wait_for_timeout(2000)
            iframe = page.frame(url=_CF_PATTERN)
            if iframe:
                box = iframe.frame_element().bounding_box()
                if box: page.mouse.click(box["x"] + 30, box["y"] + 30)
            return not self._is_cloudflare(page)
        except Exception: return False

    async def _solve_cloudflare_async(self, page: AsyncPage) -> bool:
        logger.warning("[CF] Async solver starting.")
        try:
            await page.wait_for_timeout(2000)
            iframe = None
            for f in page.frames:
                if _CF_PATTERN.match(f.url):
                    iframe = f; break
            if iframe:
                box = await (await iframe.frame_element()).bounding_box()
                if box: await page.mouse.click(box["x"] + 30, box["y"] + 30)
            return not await self._is_cloudflare_async(page)
        except Exception: return False

    def _solve_google_captcha(self, page: Page, original_url: str = None) -> bool:
        logger.warning("[CAPTCHA] Sync solver starting.")
        site_key = _extract_sitekey(page)
        if not site_key or not hasattr(self, 'capmonster_key'): return False
        token = _capmonster_solve(self.capmonster_key, page.url, site_key)
        if token: _inject_and_submit(page, token); return True
        return False

    async def _solve_google_captcha_async(self, page: AsyncPage, original_url: str = None) -> bool:
        logger.warning("[CAPTCHA] Async solver starting.")
        site_key = await _extract_sitekey_async(page)
        if not site_key or not hasattr(self, 'capmonster_key'): return False
        token = await asyncio.get_event_loop().run_in_executor(None, _capmonster_solve, self.capmonster_key, page.url, site_key)
        if token: await _inject_and_submit_async(page, token); return True
        return False

class StealthyFetcher(_StealthMixin):
    def __init__(self, **kwargs):
        for k, v in kwargs.items(): setattr(self, k, v)
        self.user_agent = getattr(self, 'user_agent', _get_random_stealth_ua())
        self.capmonster_key = os.getenv("CAPMONSTER_API_KEY")

    def fetch(self, url: str, **kwargs) -> Response:
        with sync_playwright() as p:
            opts = _build_context_options(self.user_agent, "en-US", None, getattr(self, 'proxy', None), None)
            ctx = p.chromium.launch_persistent_context(tempfile.mkdtemp(), **opts)
            page = ctx.new_page()
            _human_pre_navigation(page)
            resp = page.goto(url)
            _human_post_navigation(page)
            res = Response(content=page.content(), status=resp.status, url=page.url, ok=resp.ok)
            ctx.close()
            return res

try:
    from .stealth_chrome2 import AsyncStealthyFetcher, PersistentStealthyFetcher
except ImportError:
    AsyncStealthyFetcher = PersistentStealthyFetcher = None

__all__ = ["StealthyFetcher", "AsyncStealthyFetcher", "PersistentStealthyFetcher", "_get_random_stealth_ua"]