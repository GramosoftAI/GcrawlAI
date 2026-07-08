import logging
from playwright.sync_api import Page
from web_crawler.common.config import CrawlConfig

logger = logging.getLogger(__name__)


def capture_robust_screenshot(page: Page, config: CrawlConfig) -> bytes:
    """
    Capture page screenshot using a robust technique.
    Supports custom full page option, quality, and format.
    """
    try:
        viewport = page.viewport_size
        current_width = viewport["width"] if viewport else 1920
        current_height = viewport["height"] if viewport else 1080
        
        full_page = config.screenshot_full_page
        screenshot_format = config.screenshot_format.lower()
        pw_type = "jpeg" if screenshot_format in ("jpeg", "jpg") else "png"
        quality = config.screenshot_quality
        
        # We use full_page=False even for full page screenshots when we manually resize the viewport,
        # which prevents Playwright from expanding the width/height due to absolute/overflowing elements.
        screenshot_args = {"full_page": False, "animations": "disabled", "type": pw_type, "timeout": 15000}
        if pw_type == "jpeg" and quality is not None:
            screenshot_args["quality"] = quality

        # Eagerly load lazy images and disable animations
        try:
            page.evaluate("""
                () => {
                    document.querySelectorAll('img').forEach(img => {
                        img.setAttribute('loading', 'eager');
                        const lazyAttr = img.getAttribute('data-src') || img.getAttribute('lazy-src') || img.getAttribute('data-lazy') || img.getAttribute('srcset');
                        if (lazyAttr && !img.src.includes(lazyAttr)) {
                            img.src = lazyAttr;
                        }
                    });
                }
            """)
        except:
            pass

        if not full_page:
            page.evaluate("window.scrollTo(0, 0)")
            page.wait_for_timeout(50)
            return page.screenshot(**screenshot_args)

        # Full page screenshot:
        # Detect if the page has horizontal scroll overflow (elements lying off-screen).
        has_horizontal_overflow = page.evaluate("""
            (() => {
                const scrollWidth = document.scrollingElement ? document.scrollingElement.scrollWidth : 0;
                const bodyScrollWidth = document.body ? document.body.scrollWidth : 0;
                const maxScrollWidth = Math.max(scrollWidth, bodyScrollWidth);
                return maxScrollWidth > window.innerWidth;
            })()
        """)
        
        if has_horizontal_overflow:
            # For pages with horizontal overflow, we temporarily resize the viewport height to total scroll height
            # but capture with full_page=False to strictly restrict width to viewport width (current_width).
            total_height = page.evaluate("""
                (() => {
                    let h1 = document.scrollingElement ? document.scrollingElement.scrollHeight : 0;
                    let h2 = document.body ? document.body.scrollHeight : 0;
                    return Math.max(h1, h2, 1000);
                })()
            """)
            capture_height = min(total_height, 15000)
            page.set_viewport_size({"width": current_width, "height": capture_height})
            
            try:
                page.mouse.move(0, 0)
            except:
                pass
            
            page.wait_for_timeout(200)
            page.evaluate("window.scrollTo(0, 0)")
            
            logger.info(f"Horizontal overflow detected. Sizing viewport to {current_width}x{capture_height} and capturing...")
            screenshot_args["full_page"] = False
            chunk_bytes = page.screenshot(**screenshot_args)
            
            # Restore original viewport size
            page.set_viewport_size({"width": current_width, "height": current_height})
            return chunk_bytes
        else:
            # For pages without horizontal overflow, we take a standard native full page screenshot
            # to preserve standard layout constraints and prevent vertical gaps.
            page.evaluate("window.scrollTo(0, 0)")
            page.wait_for_timeout(50)
            logger.info("No horizontal overflow. Taking native Playwright full-page screenshot...")
            screenshot_args["full_page"] = True
            chunk_bytes = page.screenshot(**screenshot_args)
            return chunk_bytes
        
    except Exception as e:
        logger.warning(f"Screenshot failed, falling back to basic: {e}")
        try:
            page.set_viewport_size({"width": current_width, "height": current_height})
        except:
            pass
        page.evaluate("window.scrollTo(0, 0)")
        screenshot_args["full_page"] = full_page
        return page.screenshot(**screenshot_args)
