import random
import json
import logging
from typing import Optional
from playwright.sync_api import Page

from web_crawler.crawler.browser.stealth_js_core import STEALTH_JS_CORE
from web_crawler.crawler.browser.stealth_js_fingerprint import STEALTH_JS_FINGERPRINT

logger = logging.getLogger(__name__)


def generate_stealth_profile(user_agent: str, locale: str = "en-US") -> dict:
    """
    Dynamically generate a high-entropy browser profile matching the user agent OS context.
    """
    ua_lower = user_agent.lower() if user_agent else ""
    
    # Determine OS context
    if "macintosh" in ua_lower or "mac os" in ua_lower:
        os_target = "mac"
    elif "linux" in ua_lower:
        os_target = "linux"
    else:
        os_target = "windows"
        
    profile = {
        "canvas_seed": random.randint(1, 4294967295),
        "audio_seed": random.randint(1, 4294967295),
        "font_spacing_seed": random.randint(1, 4294967295),
        "concurrency": random.choice([4, 8, 12, 16]),
        "device_memory": random.choice([4, 8, 16]),
        "locale": locale
    }
    
    if os_target == "mac":
        profile["platform"] = "MacIntel"
        profile["oscpu"] = "Intel Mac OS X 10.15"
        profile["webgl_vendor"] = "Apple Inc."
        profile["webgl_renderer"] = random.choice([
            "Apple M1", "Apple M1 Pro", "Apple M1 Max",
            "Apple M2", "Apple M3", "Apple GPU"
        ])
        profile["voices"] = [
            {"name": "Alex", "lang": "en-US", "default": True, "localService": True, "voiceURI": "Alex"},
            {"name": "Samantha", "lang": "en-US", "default": False, "localService": True, "voiceURI": "Samantha"},
            {"name": "Fred", "lang": "en-US", "default": False, "localService": True, "voiceURI": "Fred"},
            {"name": "Victoria", "lang": "en-US", "default": False, "localService": True, "voiceURI": "Victoria"}
        ]
    elif os_target == "linux":
        profile["platform"] = "Linux x86_64"
        profile["oscpu"] = "Linux x86_64"
        profile["webgl_vendor"] = "Intel Open Source Technology Center"
        profile["webgl_renderer"] = "Mesa DRI Intel(R) HD Graphics 520 (Skylake GT2)"
        profile["voices"] = [
            {"name": "Google US English", "lang": "en-US", "default": True, "localService": False, "voiceURI": "Google US English"},
            {"name": "Google UK English Male", "lang": "en-GB", "default": False, "localService": False, "voiceURI": "Google UK English Male"}
        ]
    else: # Windows
        profile["platform"] = "Win32"
        profile["oscpu"] = "Windows NT 10.0; Win64; x64"
        profile["webgl_vendor"] = "Google Inc. (NVIDIA)"
        profile["webgl_renderer"] = random.choice([
            "ANGLE (NVIDIA, NVIDIA GeForce RTX 3060 Direct3D11 vs_5_0 ps_5_0, D3D11)",
            "ANGLE (NVIDIA, NVIDIA GeForce RTX 4070 Laptop GPU Direct3D11 vs_5_0 ps_5_0, D3D11)",
            "ANGLE (Intel, Intel(R) Iris(R) Xe Graphics Direct3D11 vs_5_0 ps_5_0, D3D11)"
        ])
        profile["voices"] = [
            {"name": "Microsoft David - English (United States)", "lang": "en-US", "default": True, "localService": True, "voiceURI": "Microsoft David"},
            {"name": "Microsoft Zira - English (United States)", "lang": "en-US", "default": False, "localService": True, "voiceURI": "Microsoft Zira"}
        ]
        
    return profile


def inject_stealth_scripts(page: Page, locale: str = "en-US", profile: Optional[dict] = None) -> None:
    """
    Inject additional JS-level anti-detection patches matching the dynamic profile.
    """
    try:
        preferred_locale = locale if locale else 'en-US'
        languages_js = f"['{preferred_locale}', '{preferred_locale.split('-')[0]}']" if '-' in preferred_locale else f"['{preferred_locale}']"
        
        if profile is None:
            # Fallback to standard Windows profile if none is supplied
            ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            profile = generate_stealth_profile(ua, locale)
            
        profile_js = json.dumps(profile)
        
        # Combine the core and fingerprint JS strings and format with variables
        combined_js = (STEALTH_JS_CORE + "\\n" + STEALTH_JS_FINGERPRINT).format(
            profile_js=profile_js,
            languages_js=languages_js
        )
        
        page.add_init_script(combined_js)
    except Exception as e:
        logger.warning(f"Failed to inject stealth scripts: {e}")
