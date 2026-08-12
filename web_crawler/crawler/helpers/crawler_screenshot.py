import logging
from playwright.sync_api import Page
from web_crawler.common.config import CrawlConfig

logger = logging.getLogger(__name__)


def capture_robust_screenshot(page: Page, config: CrawlConfig) -> bytes:
    """
    Takes a full-page screenshot of a Playwright page.
    """
    try:
        # Move mouse to top-left corner to prevent hover states in screenshots
        try:
            page.mouse.move(0, 0)
        except Exception as e:
            logger.debug(f"Could not move mouse to (0,0): {e}")

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

        # Full page scroll simulation to trigger lazy loading of content & images
        # If auto_scroll was already executed in the crawler phase, skip it to prevent redundant scrolling
        if not config.auto_scroll:
            try:
                logger.info("Scrolling page to trigger lazy loaded resources...")
                page.evaluate("""
                    async () => {
                        await new Promise((resolve) => {
                            let totalHeight = 0;
                            const distance = 800; // Scroll distance in pixels
                            const maxSteps = 30; // Max scrolls to prevent infinite loops / long hangs
                            let steps = 0;
                            const timer = setInterval(() => {
                                const scrollElement = document.scrollingElement || document.documentElement || document.body;
                                const scrollHeight = scrollElement ? scrollElement.scrollHeight : document.body.scrollHeight;
                                window.scrollBy(0, distance);
                                totalHeight += distance;
                                steps++;
                                if (steps >= maxSteps || totalHeight >= scrollHeight || (scrollElement && (scrollElement.scrollTop + window.innerHeight >= scrollHeight))) {
                                    clearInterval(timer);
                                    window.scrollTo(0, 0);
                                    resolve();
                                }
                            }, 100);
                        });
                    }
                """)
                # Give layout and sticky bars 500ms to stabilize after scrolling back to top
                page.wait_for_timeout(500)
            except Exception as scroll_err:
                logger.warning(f"Lazy load scrolling failed/timed out: {scroll_err}")
        else:
            logger.info("Auto-scroll was already executed during page crawl phase, skipping redundant scroll.")

        # Try native full_page=True screenshot first, as it maintains original viewport constraints
        # and doesn't break slide-like or viewport-relative layouts (e.g. line.me).
        page.evaluate("window.scrollTo(0, 0)")
        page.wait_for_timeout(100)

        # Force visibility of animated elements (AOS, ScrollReveal, counters) right before screenshot
        try:
            # 1. Inject CSS overrides to disable transitions and force AOS/ScrollReveal elements to final visible state
            page.add_style_tag(content="""
                /* Disable all transitions and animations to prevent half-finished states */
                *, *::before, *::after {
                    transition-delay: 0s !important;
                    transition-duration: 0s !important;
                    animation-delay: 0s !important;
                    animation-duration: 0s !important;
                    transition-property: none !important;
                }
                /* Force html and body heights to be auto/visible to prevent native full-page screenshot truncation */
                html, body {
                    height: auto !important;
                    overflow: visible !important;
                }
                /* Force AOS (Animate on Scroll) elements to be visible and correctly positioned */
                [data-aos] {
                    opacity: 1 !important;
                    transform: none !important;
                    visibility: visible !important;
                }
                /* Force ScrollReveal elements to be visible */
                [data-sr-id] {
                    opacity: 1 !important;
                    transform: none !important;
                    visibility: visible !important;
                }
                /* Force WOW.js elements to be visible */
                .wow {
                    opacity: 1 !important;
                    visibility: visible !important;
                }
            """)
            
            # 2. Force AOS classes and counters to show their final values
            page.evaluate("""
                () => {
                    // Force AOS animated classes
                    document.querySelectorAll('[data-aos]').forEach(el => {
                        el.classList.add('aos-animate');
                    });
                    
                    // Force counter numbers to show their final values
                    document.querySelectorAll('h3[data-number]').forEach(counter => {
                        const endValue = counter.getAttribute('data-number');
                        const symbol = counter.getAttribute('data-symbol') || '';
                        if (endValue) {
                            counter.textContent = endValue + symbol;
                            counter.classList.add('animated');
                        }
                    });
                }
            """)
            page.wait_for_timeout(150)
        except Exception as inject_err:
            logger.debug(f"Could not inject screenshot preparation styles/scripts: {inject_err}")
        
        screenshot_args["full_page"] = True
        logger.info("Capturing native Playwright full-page screenshot...")
        chunk_bytes = page.screenshot(**screenshot_args)
        
        # Check if the native capture suffered from compositor truncation (rendering blank white space at bottom)
        try:
            import io
            from PIL import Image
            
            img = Image.open(io.BytesIO(chunk_bytes))
            w, h = img.size
            if h >= 1000:
                gray = img.convert("L")
                content_end_y = 0
                for y in range(h - 1, -1, -5):
                    # Sample pixels in this row to check for variations (content)
                    row_pixels = [gray.getpixel((x, y)) for x in range(10, w - 10, 10)]
                    min_p = min(row_pixels)
                    max_p = max(row_pixels)
                    if max_p - min_p >= 8:
                        content_end_y = y
                        break
                
                blank_height = h - content_end_y
                blank_pct = (blank_height / h) * 100
                
                if blank_height > 800 and blank_pct > 20.0:
                    logger.warning(
                        f"Truncation detected: {blank_height}px ({blank_pct:.1f}%) of the native screenshot is blank. "
                        "Triggering viewport-resizing fallback capture..."
                    )
                    # Get document's total scroll height
                    total_height = page.evaluate("""
                        (() => {
                            const body = document.body;
                            const html = document.documentElement;
                            const docElement = document.scrollingElement || html;
                            return Math.max(
                                body ? body.scrollHeight : 0,
                                body ? body.offsetHeight : 0,
                                html ? html.clientHeight : 0,
                                html ? html.scrollHeight : 0,
                                html ? html.offsetHeight : 0,
                                docElement ? docElement.scrollHeight : 0,
                                1000
                            );
                        })()
                    """)
                    capture_height = min(total_height, 15000)
                    
                    # Intercept window resize events so that the webpage scripts do not detect the resize event and trigger a page refresh/reload.
                    try:
                        page.evaluate("""
                            () => {
                                window.__blockResize = (e) => {
                                    e.stopImmediatePropagation();
                                };
                                window.addEventListener('resize', window.__blockResize, { capture: true, passive: false });
                            }
                        """)
                    except Exception as block_err:
                        logger.debug(f"Failed to register resize blocker: {block_err}")
                    
                    page.set_viewport_size({"width": current_width, "height": capture_height})
                    
                    try:
                        page.mouse.move(0, 0)
                    except:
                        pass
                    
                    page.wait_for_timeout(300)
                    page.evaluate("window.scrollTo(0, 0)")
                    page.wait_for_timeout(200)
                    
                    screenshot_args["full_page"] = False
                    chunk_bytes = page.screenshot(**screenshot_args)
                    
                    # Restore original viewport size
                    page.set_viewport_size({"width": current_width, "height": current_height})
                    
                    # Unblock window resize events
                    try:
                        page.evaluate("""
                            () => {
                                if (window.__blockResize) {
                                    window.removeEventListener('resize', window.__blockResize, true);
                                    delete window.__blockResize;
                                }
                            }
                        """)
                    except Exception as unblock_err:
                        logger.debug(f"Failed to remove resize blocker: {unblock_err}")
                        
                    logger.info("Viewport-resized fallback capture successful.")
        except Exception as detection_err:
            logger.debug(f"Truncation detection failed/skipped: {detection_err}")
            
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
