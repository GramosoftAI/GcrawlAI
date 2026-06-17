import logging
from typing import Optional
from urllib.parse import urlparse
import primp

logger = logging.getLogger(__name__)


def resolve_canonical_url(url: str, timeout: int = 8, proxies: Optional[dict] = None) -> str:
    """
    Follow redirects to find the canonical URL of a page.
    Uses a lightweight HEAD request.
    Returns the original URL unchanged if resolution fails.
    """
    try:
        # Skip canonical resolution for known high security sites to save 3-5 seconds of hanging requests
        high_sec = ["gartner.com", "expedia", "skyscanner", "oracle.com"]
        if any(h in url.lower() for h in high_sec):
            return url
            
        proxy_url = None
        if proxies:
            if "https" in proxies:
                proxy_url = proxies["https"]
            elif "http" in proxies:
                proxy_url = proxies["http"]

        client = primp.Client(
            impersonate="chrome",
            proxy=proxy_url,
            timeout=float(timeout),
            verify=False
        )
        resp = client.head(url)
        final_url = resp.url
        if final_url and final_url != url:
            # If redirection leads to a known 'Sorry' or 'Block' page, 
            # ignore it and return the original URL so the browser can try to bypass it.
            block_patterns = ["sorry-server", "delta_sorry", "access-denied", "captcha", "checkpoint"]
            if any(p in final_url.lower() for p in block_patterns):
                logger.warning(f"⚠️ Canonical resolver redirected to a Block page ({final_url}). Ignoring and using original URL.")
                return url

            parsed_orig = urlparse(url)
            parsed_final = urlparse(final_url)
            if parsed_orig.netloc != parsed_final.netloc:
                logger.info(f"🔀 URL canonicalized: {url} → {final_url}")
                return final_url
    except Exception:
        pass
    return url
