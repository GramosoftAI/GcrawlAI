"""
stealth_chrome.py — Patchright-based stealthy browser fetcher.
Dual-mode (Sync/Async) support.
"""

import re
import random
import logging
from typing import Optional, Dict, Any

from playwright.async_api import Page as AsyncPage

logger = logging.getLogger(__name__)

# Constants
DEFAULT_ARGS = ["--no-pings", "--no-first-run", "--disable-infobars", "--disable-breakpad", "--no-service-autorun", "--homepage=about:blank", "--password-store=basic", "--disable-hang-monitor", "--no-default-browser-check", "--disable-session-crashed-bubble", "--disable-search-engine-choice-screen"]
STEALTH_ARGS = ["--test-type", "--lang=en-US", "--mute-audio", "--disable-sync", "--hide-scrollbars", "--disable-logging", "--start-maximized", "--enable-async-dns", "--accept-lang=en-US", "--use-mock-keychain", "--disable-translate", "--disable-voice-input", "--window-position=0,0", "--disable-wake-on-wifi", "--ignore-gpu-blocklist", "--enable-tcp-fast-open", "--enable-web-bluetooth", "--disable-cloud-import", "--disable-print-preview", "--disable-dev-shm-usage", "--disable-crash-reporter", "--disable-partial-raster", "--disable-gesture-typing", "--disable-checker-imaging", "--disable-prompt-on-repost", "--force-color-profile=srgb", "--font-render-hinting=none", "--aggressive-cache-discard", "--disable-domain-reliability", "--disable-threaded-animation", "--disable-threaded-scrolling", "--enable-simple-cache-backend", "--disable-background-networking", "--enable-surface-synchronization", "--disable-image-animation-resync", "--disable-renderer-backgrounding", "--disable-ipc-flooding-protection", "--prerender-from-omnibox=disabled", "--safebrowsing-disable-auto-update", "--disable-offer-upload-credit-cards", "--disable-background-timer-throttling", "--disable-new-content-rendering-timeout", "--run-all-compositor-stages-before-draw", "--disable-client-side-phishing-detection", "--disable-backgrounding-occluded-windows", "--disable-layer-tree-host-memory-pressure", "--autoplay-policy=user-gesture-required", "--disable-offer-store-unmasked-wallet-cards", "--disable-blink-features=AutomationControlled", "--disable-component-extensions-with-background-pages", "--enable-features=NetworkService,NetworkServiceInProcess,TrustTokens,TrustTokensAlwaysAllowIssuance", "--blink-settings=primaryHoverType=2,availableHoverTypes=2,primaryPointerType=4,availablePointerTypes=4", "--disable-features=AudioServiceOutOfProcess,TranslateUI,BlinkGenPropertyTrees"]
ALL_LAUNCH_ARGS = DEFAULT_ARGS + STEALTH_ARGS
BLOCK_RESOURCE_TYPES = {"image", "media", "beacon", "object", "imageset", "texttrack", "websocket", "csp_report"}

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
    """Return random stealth ua."""
    return random.choice(_CHROME_UA_POOL)

def _get_stealth_ua_for_platform(platform: str) -> str:
    """Return stealth ua for platform."""
    p = platform.lower()
    if p == "windows":
        pool = [ua for ua in _CHROME_UA_POOL if "windows" in ua.lower()]
    elif p == "macos":
        pool = [ua for ua in _CHROME_UA_POOL if "macintosh" in ua.lower() or "mac os" in ua.lower()]
    elif p == "linux":
        pool = [ua for ua in _CHROME_UA_POOL if "linux" in ua.lower() or "x11" in ua.lower()]
    else:
        pool = _CHROME_UA_POOL
        
    if not pool:
        pool = _CHROME_UA_POOL
    return random.choice(pool)

_STEALTH_UA: str = _get_random_stealth_ua()

def _build_stealth_headers(user_agent: str) -> Dict[str, str]:
    """Build stealth headers."""
    m = re.search(r"Chrome/(\d+)", user_agent)
    major = m.group(1) if m else "131"
    
    # Resolve platform for Sec-CH-UA-Platform
    if "windows" in user_agent.lower():
        platform = '"Windows"'
    elif "macintosh" in user_agent.lower() or "mac os" in user_agent.lower():
        platform = '"macOS"'
    elif "linux" in user_agent.lower():
        platform = '"Linux"'
    else:
        platform = '"Windows"'
        
    return {
        "Sec-CH-UA": f'"ClockBrowser";v="{major}", "Google Chrome";v="{major}", "Not-A.Brand";v="99"',
        "Sec-CH-UA-Mobile": "?0",
        "Sec-CH-UA-Platform": platform,
        "Accept-Language": "en-US,en;q=0.9",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-User": "?1",
        "Sec-Fetch-Dest": "document",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
    }

def _build_context_options(user_agent: str, locale: str, timezone_id: Optional[str], proxy: Optional[Dict], extra_headers: Optional[Dict]) -> Dict:
    """Build context options."""
    stealth_hdrs = _build_stealth_headers(user_agent)
    if extra_headers: stealth_hdrs.update(extra_headers)
    
    platform_choice = random.choices(["windows", "macos", "linux"], weights=[85, 10, 5])[0]
    seed = random.randint(100000, 9999999)
    concurrency = random.choice([4, 8, 12, 16])
    memory = random.choice([4, 8, 16])
    
    if platform_choice == "windows":
        res = random.choice([(1920, 1080, 48), (1366, 768, 40), (1536, 864, 40)])
    elif platform_choice == "macos":
        res = random.choice([(1440, 900, 95), (1680, 1050, 95), (2560, 1600, 95)])
    else:
        res = random.choice([(1920, 1080, 0), (1366, 768, 0)])
        
    width, height, taskbar = res
    
    fingerprint_args = [
        f"--fingerprint={seed}",
        f"--fingerprint-platform={platform_choice}",
        f"--fingerprint-screen-width={width}",
        f"--fingerprint-screen-height={height}",
        f"--fingerprint-taskbar-height={taskbar}",
        f"--fingerprint-hardware-concurrency={concurrency}",
        f"--fingerprint-device-memory={memory}",
    ]
    
    opts = {
        "color_scheme": "dark", "device_scale_factor": 2, "is_mobile": False, "has_touch": False,
        "service_workers": "allow", "ignore_https_errors": True,
        "screen": {"width": width, "height": height}, "viewport": {"width": width, "height": height - taskbar},
        "user_agent": user_agent, "locale": locale, "java_script_enabled": True, "extra_http_headers": stealth_hdrs,
        "headless": False,
        "args": fingerprint_args + ALL_LAUNCH_ARGS
    }
    if timezone_id: opts["timezone_id"] = timezone_id
    if proxy: opts["proxy"] = proxy
    return opts



_CF_PATTERN = re.compile(r"^https?://challenges\.cloudflare\.com/cdn-cgi/challenge-platform/.*")

class _StealthMixin:
    """Return True if google captcha."""
    def _is_google_captcha(self, page: Any) -> bool: return "/sorry/" in page.url
    
    async def _is_cloudflare_async(self, page: AsyncPage) -> bool:
        """Return True if cloudflare async."""
        try:
            if "Just a moment" in await page.title(): return True
            content = await page.content()
            if "challenges.cloudflare.com" in content: return True
        except Exception: pass
        return False

    async def _solve_cloudflare_async(self, page: AsyncPage) -> bool:
        """Solve cloudflare async."""
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

__all__ = ["_get_random_stealth_ua", "_get_stealth_ua_for_platform"]