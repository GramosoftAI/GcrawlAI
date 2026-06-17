import logging
from playwright.sync_api import Page
from web_crawler.common.config import CrawlConfig

logger = logging.getLogger(__name__)


def capture_robust_screenshot(page: Page, config: CrawlConfig) -> bytes:
    """
    Capture page screenshot using a robust merging technique to avoid blank areas.
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
        
        screenshot_args = {"full_page": full_page, "animations": "disabled", "type": pw_type, "timeout": 15000}
        if pw_type == "jpeg" and quality is not None:
            screenshot_args["quality"] = quality

        if not full_page:
            page.evaluate("window.scrollTo(0, 0)")
            page.wait_for_timeout(50)
            return page.screenshot(**screenshot_args)
        
        total_height = page.evaluate("""
            (() => {
                let h1 = document.scrollingElement ? document.scrollingElement.scrollHeight : 0;
                let h2 = document.body ? document.body.scrollHeight : 0;
                return Math.max(h1, h2, 1000);
            })()
        """)
        
        if total_height < current_height * 2:
            page.evaluate("window.scrollTo(0, 0)")
            page.wait_for_timeout(50)
            return page.screenshot(**screenshot_args)

        capture_height = min(total_height, 15000)
        page.set_viewport_size({"width": current_width, "height": capture_height})
        
        page.evaluate("""
            () => {
                window.dispatchEvent(new Event('resize'));
                
                const style = document.createElement('style');
                style.id = 'gcrawl-screenshot-style';
                style.innerHTML = `
                    html, body {
                        height: auto !important;
                        overflow: visible !important;
                        overflow-y: visible !important;
                    }
                `;
                document.head.appendChild(style);

                document.querySelectorAll('img').forEach(img => {
                    img.setAttribute('loading', 'eager');
                    const lazyAttr = img.getAttribute('data-src') || img.getAttribute('lazy-src') || img.getAttribute('data-lazy') || img.getAttribute('srcset');
                    if (lazyAttr && !img.src.includes(lazyAttr)) {
                        img.src = lazyAttr;
                    }
                });
            }
        """)
        
        try:
            page.mouse.move(0, 0)
        except:
            pass
        
        page.wait_for_timeout(100)
        page.evaluate("window.scrollTo(0, 0)")
        
        logger.info(f"Taking screenshot...")
        logger.info(f"Setting final viewport height to {capture_height}px for screenshot")
        
        screenshot_args["full_page"] = True
        chunk_bytes = page.screenshot(**screenshot_args)
        
        page.set_viewport_size({"width": current_width, "height": current_height})
        return chunk_bytes
        
    except Exception as e:
        logger.warning(f"Screenshot failed, falling back to basic: {e}")
        try:
            page.set_viewport_size({"width": current_width, "height": current_height})
        except:
            pass
        page.evaluate("window.scrollTo(0, 0)")
        return page.screenshot(**screenshot_args)
