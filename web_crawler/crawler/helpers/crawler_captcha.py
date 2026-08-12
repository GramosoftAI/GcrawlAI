import logging
from playwright.sync_api import Page

logger = logging.getLogger(__name__)


def is_captcha_page(page: Page) -> bool:
    """
    Deep check for CAPTCHA pages including iframes and specific bot-challenge elements.
    Only flags Turnstile/Recaptcha/Hcaptcha if the page is a WAF challenge wall,
    allowing legitimate forms with embedded widgets to be scraped normally.
    """
    try:
        title = page.title().lower().strip()
        
        # 1. Determine if this looks like a WAF challenge/block page by title
        challenge_title_keywords = [
            "just a moment", "attention required", "not a robot", "pardon our interruption",
            "verify you", "one more step", "access denied", "checking your browser", "cloudflare",
            "forbidden", "blocked"
        ]
        is_waf_challenge = any(kw in title for kw in challenge_title_keywords) or title == ""

        # 2. Check Unconditional block selectors first (always indicate a block)
        unconditional_selectors = [
            "#sec-if-cpt-container", ".scf-akamai-logo-sec-abc", "#sec-bc-tile-parent",
            "#px-captcha", "#distilCaptcha", "#challenge-container"
        ]
        for selector in unconditional_selectors:
            try:
                locator = page.locator(selector)
                if locator.count() > 0:
                    logger.warning(f"CAPTCHA/Challenge detected via unconditional selector: {selector}")
                    return True
            except:
                continue

        # If it is NOT a WAF challenge by title, we do not treat Turnstile/Recaptcha/Hcaptcha as blocks
        if not is_waf_challenge:
            return False

        # Get text content to check overall text footprint
        text_content = ""
        try:
            text_content = page.evaluate("document.body ? document.body.innerText : ''")
        except:
            pass
        
        text_len = len(text_content.strip())
        text_lower = text_content.lower()

        # Highly specific CAPTCHA text markers
        specific_markers = [
            "our systems have detected unusual traffic",
            "please show you're not a robot",
            "i'm not a robot",
            "i am not a robot",
            "verify you are human",
            "click the button below to continue shopping",
            "type the characters you see in this image",
            "enter the characters you see below",
            "verify your browser", "verify that you are human",
            "please complete the security check", "security check to access",
            "you don't have permission to access", "access denied"
        ]
        
        generic_markers = [
            "checking if the site connection is secure",
            "enable cookies and javascript",
            "one more step"
        ]

        matching_specific = [m for m in specific_markers if m in text_lower]
        matching_generic = [m for m in generic_markers if m in text_lower]

        # 3. Text marker check
        if (text_len < 4000 and matching_specific) or (text_len < 1000 and matching_generic):
            logger.warning(f"CAPTCHA detected via text content. Specific: {matching_specific}, Generic: {matching_generic}. Text preview: {text_content.strip()[:200]}")
            return True

        # 4. Turnstile/Cloudflare challenge selectors
        challenge_selectors = [
            "#cf-challenge", "#challenge-form",
            "iframe[src*='challenges.cloudflare.com']", "iframe[src*='challenge-platform']",
            "div[id*='turnstile']", "div[class*='turnstile']", ".cf-turnstile",
            "#challenge-running", "#challenge-stage", "#challenge-error-title",
            "#turnstile-wrapper"
        ]
        for selector in challenge_selectors:
            try:
                locator = page.locator(selector)
                if locator.count() > 0:
                    logger.warning(f"CAPTCHA/Challenge detected via challenge selector: {selector}")
                    return True
            except:
                continue

        # 5. Gated Selector check
        if text_len < 1000 or (text_len < 3000 and matching_specific):
            # 5a. Existence selectors
            existence_selectors = [
                ".behavioral-content"
            ]
            for selector in existence_selectors:
                try:
                    locator = page.locator(selector)
                    if locator.count() > 0:
                        logger.warning(f"CAPTCHA/Challenge detected via generic existence selector: {selector} (text_len={text_len})")
                        return True
                except:
                    continue

            # 5b. Visibility selectors
            visibility_selectors = [
                "iframe[src*='captcha']", "iframe[src*='recaptcha']", 
                "iframe[src*='hcaptcha']", "iframe[src*='turnstile']",
                ".g-recaptcha", ".h-captcha"
            ]
            for selector in visibility_selectors:
                try:
                    count = page.locator(selector).count()
                    if count > 0:
                        if selector.startswith("iframe"):
                            is_real_captcha = False
                            for i in range(count):
                                elem = page.locator(selector).nth(i)
                                src = elem.get_attribute("src") or ""
                                if "size=invisible" in src:
                                    continue
                                
                                try:
                                    box = elem.bounding_box()
                                    if box and box["width"] > 0 and box["height"] > 0:
                                        is_real_captcha = True
                                        break
                                except:
                                    if elem.is_visible():
                                        is_real_captcha = True
                                        break
                            if is_real_captcha:
                                logger.warning(f"CAPTCHA detected via visible iframe selector: {selector} (text_len={text_len})")
                                return True
                        else:
                            is_visible = False
                            for i in range(count):
                                elem = page.locator(selector).nth(i)
                                try:
                                    box = elem.bounding_box()
                                    if box and box["width"] > 0 and box["height"] > 0:
                                        is_visible = True
                                        break
                                except:
                                    if elem.is_visible():
                                        is_visible = True
                                        break
                            if is_visible:
                                logger.warning(f"CAPTCHA detected via visible class selector: {selector} (text_len={text_len})")
                                return True
                except:
                    continue

        return False
    except Exception as e:
        err_msg = str(e).lower()
        if any(kw in err_msg for kw in ("context", "navigat", "target", "closed", "frame")):
            logger.warning(f"Captcha check encountered transient error: {e}. Treating as active challenge/loading state.")
            return True
        logger.debug(f"Captcha detection check failed: {e}")
        return False
