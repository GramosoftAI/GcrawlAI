import logging
from playwright.sync_api import Page

logger = logging.getLogger(__name__)


def is_captcha_page(page: Page) -> bool:
    """
    Deep check for CAPTCHA pages including iframes and specific bot-challenge elements.
    Uses text length validation to avoid false positives on legitimate pages containing embedded widgets.
    """
    try:
        # 1. Check Page Title
        title = page.title().lower()
        captcha_title_markers = [
            "just a moment...", "just a moment |", "attention required! |",
            "not a robot", "pardon our interruption",
            "verify you are human", "verify you're human", "verify that you are human",
            "one more step to access"
        ]
        if any(m in title for m in captcha_title_markers):
            logger.warning(f"CAPTCHA detected via title: {title}")
            return True

        # Get text content first to check overall text footprint
        text_content = ""
        try:
            text_content = page.evaluate("document.body ? document.body.innerText : ''")
        except:
            pass
        
        text_len = len(text_content.strip())
        text_lower = text_content.lower()

        # Highly specific CAPTCHA text markers (indicate a block page even with moderate text)
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
            "please complete the security check", "security check to access"
        ]
        
        # Generic CAPTCHA text markers (might appear in support docs/forms, only check if page is sparse)
        generic_markers = [
            "checking if the site connection is secure",
            "enable cookies and javascript",
            "one more step"
        ]

        matching_specific = [m for m in specific_markers if m in text_lower]
        matching_generic = [m for m in generic_markers if m in text_lower]

        # 2. Text marker check
        if (text_len < 4000 and matching_specific) or (text_len < 1000 and matching_generic):
            logger.warning(f"CAPTCHA detected via text content. Specific: {matching_specific}, Generic: {matching_generic}. Text preview: {text_content.strip()[:200]}")
            return True

        # 3. Highly specific block selectors
        specific_block_selectors = [
            "#sec-if-cpt-container", ".scf-akamai-logo-sec-abc", "#sec-bc-tile-parent",
            "#px-captcha", "#distilCaptcha", "#cf-challenge", "#challenge-form",
            "iframe[src*='challenges.cloudflare.com']", "iframe[src*='challenge-platform']",
            "div[id*='turnstile']", "div[class*='turnstile']", ".cf-turnstile",
            "#challenge-running", "#challenge-stage", "#challenge-error-title",
            "#turnstile-wrapper"
        ]
        for selector in specific_block_selectors:
            try:
                locator = page.locator(selector)
                if locator.count() > 0:
                    logger.warning(f"CAPTCHA/Challenge detected via highly specific selector: {selector}")
                    return True
            except:
                continue

        # 4. Gated Selector check
        if text_len < 1000 or (text_len < 3000 and matching_specific):
            # 4a. Existence selectors
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

            # 4b. Visibility selectors
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
        logger.debug(f"Captcha detection check failed: {e}")
        return False
