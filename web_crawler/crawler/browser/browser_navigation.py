import time
import random
import logging
from playwright.sync_api import Page
from web_crawler.common.config import CrawlConfig

logger = logging.getLogger(__name__)


def wait_for_ready(page: Page, quick: bool = False) -> bool:
    """
    Wait for page to be ready and stabilized using DOM content stability checks.
    Ensures the page has fully hydrated dynamic client-side content (SPAs) before proceeding.
    """
    check_interval = 150 if quick else 250
    max_wait = 4000 if quick else 15000
    stable_threshold = 2 if quick else 4
    hydration_timeout = 1500 if quick else 4000

    try:
        # Use an in-browser script to monitor DOM changes and stabilize.
        # It checks that the body exists, the element count and HTML length are stable,
        # and that we have actual text/content loaded (not just the initial blank SPA shell).
        stabilization_script_template = """
        async () => {
            return new Promise((resolve) => {
                let lastHtmlLength = 0;
                let lastElementCount = 0;
                let stableCount = 0;
                let elapsed = 0;
                const checkInterval = __CHECK_INTERVAL__; // check interval in ms
                const maxWait = __MAX_WAIT__; // absolute maximum wait time
                const stableThreshold = __STABLE_THRESHOLD__;
                const hydrationTimeout = __HYDRATION_TIMEOUT__;
                
                const check = () => {
                    const body = document.body;
                    if (!body) {
                        elapsed += checkInterval;
                        if (elapsed >= maxWait) {
                            resolve(false);
                            return;
                        }
                        setTimeout(check, checkInterval);
                        return;
                    }
                    
                    const htmlLength = body.innerHTML.length;
                    const elementCount = body.getElementsByTagName('*').length;
                    
                    // Strip whitespace and check if text has been loaded.
                    // SPAs typically start with 0-1 tags in body and no text, then render content.
                    const textContent = (body.innerText || body.textContent || "").trim();
                    const isSubstantial = textContent.length > 30 || elementCount > 10;
                    const isUnchanged = htmlLength === lastHtmlLength && elementCount === lastElementCount;
                    
                    // We count as stable if DOM size/elements are unchanged.
                    // If it's a blank template (not substantial yet), we wait longer to see if content hydrates.
                    if (isUnchanged && (isSubstantial || elapsed > hydrationTimeout)) {
                        stableCount++;
                        if (stableCount >= stableThreshold) {
                            resolve(true);
                            return;
                        }
                    } else {
                        stableCount = 0;
                        lastHtmlLength = htmlLength;
                        lastElementCount = elementCount;
                    }
                    
                    elapsed += checkInterval;
                    if (elapsed >= maxWait) {
                        // Resolve true on timeout to proceed with whatever content we managed to load
                        resolve(true);
                        return;
                    }
                    
                    setTimeout(check, checkInterval);
                };
                
                check();
            });
        }
        """
        stabilization_script = (
            stabilization_script_template
            .replace("__CHECK_INTERVAL__", str(check_interval))
            .replace("__MAX_WAIT__", str(max_wait))
            .replace("__STABLE_THRESHOLD__", str(stable_threshold))
            .replace("__HYDRATION_TIMEOUT__", str(hydration_timeout))
        )
        
        # Wait for execution of the stabilization script
        page.evaluate(stabilization_script)
        return True
    except BaseException as e:
        err_msg = str(e).lower()
        if "execution context was destroyed" in err_msg or "context was destroyed" in err_msg:
            logger.info("Execution context destroyed (navigation/redirect detected). Waiting for new page load state...")
            try:
                page.wait_for_load_state("domcontentloaded", timeout=10000)
                page.wait_for_timeout(1000)
                page.evaluate(stabilization_script)
                return True
            except Exception as retry_err:
                logger.warning(f"Retry stabilization failed: {retry_err}")
        else:
            logger.info(f"Page stabilization check encountered error/timeout: {e}")
        return False


def check_cloudflare(page: Page, config: CrawlConfig) -> bool:
    """Check and attempt to bypass Cloudflare"""
    if not config.bypass_cloudflare:
        return True
    
    try:
        content = page.content().lower()
        if "cloudflare" not in content and "ray id" not in content:
            return True
        
        logger.info("Cloudflare detected, waiting...")
        
        if config.simulate_human:
            for _ in range(2):
                page.mouse.move(100, 100)
                time.sleep(0.2)
                page.mouse.move(200, 200)
                time.sleep(0.2)
        
        time.sleep(3)
        return True
        
    except Exception as e:
        logger.warning(f"Cloudflare check failed: {e}")
        return False


def erratic_scroll(page: Page) -> None:
    """
    POC Parity: Perform human-like irregular scroll to trigger lazy loading 
    and generate behavioral telemetry. Enhanced with mouse jiggling.
    """
    try:
        logger.info("[Stealth Layer] Behavioral Simulation: Executing erratic scroll sequence.")
        
        # Initial random mouse move
        page.mouse.move(random.randint(100, 800), random.randint(100, 600))
        
        # Handle both window and nested div scrolling organically with smooth behavior
        page.evaluate("""
            async () => {
                const getTallestScrollable = () => {
                    const elements = document.querySelectorAll('*');
                    let tallest = document.scrollingElement || document.documentElement;
                    let maxH = tallest.scrollHeight;
                    
                    for (const el of elements) {
                        const h = el.scrollHeight;
                        if (h > maxH && getComputedStyle(el).overflowY !== 'hidden') {
                            maxH = h;
                            tallest = el;
                        }
                    }
                    return tallest;
                };

                const scrollTarget = getTallestScrollable();
                let currentY = 0;
                const maxScroll = 15000;
                
                while (currentY < maxScroll) {
                    const scrollHeight = scrollTarget.scrollHeight;
                    const step = Math.floor(Math.random() * 400) + 100;
                    
                    if (scrollTarget === window || scrollTarget === document.documentElement || scrollTarget === document.body) {
                        window.scrollBy({ top: step, behavior: 'smooth' });
                    } else {
                        scrollTarget.scrollBy({ top: step, behavior: 'smooth' });
                    }
                    
                    currentY += step;
                    if (currentY >= scrollHeight) break;
                    
                    // Add realistic read pauses (12% chance to pause longer, otherwise normal delay)
                    let delay = Math.floor(Math.random() * 80) + 40;
                    if (Math.random() < 0.12) {
                        delay += Math.floor(Math.random() * 1000) + 400;
                    }
                    
                    // 5% chance of scrolling back up slightly (re-reading)
                    if (Math.random() < 0.05 && currentY > 500) {
                        const backStep = -Math.floor(Math.random() * 150) - 50;
                        if (scrollTarget === window || scrollTarget === document.documentElement || scrollTarget === document.body) {
                            window.scrollBy({ top: backStep, behavior: 'smooth' });
                        } else {
                            scrollTarget.scrollBy({ top: backStep, behavior: 'smooth' });
                        }
                        currentY += backStep;
                        delay += Math.floor(Math.random() * 200) + 100;
                    }
                    
                    await new Promise(r => setTimeout(r, delay));
                }
                
                // Final small scroll adjustments to ensure completion
                if (scrollTarget.scrollTo) {
                    try {
                        scrollTarget.scrollTo({ top: scrollTarget.scrollHeight, behavior: 'smooth' });
                    } catch(e) {
                        scrollTarget.scrollTo(0, scrollTarget.scrollHeight);
                    }
                }
            }
        """)
        
        # Short wait for any late lazy-loading
        page.wait_for_timeout(1500)
        page.wait_for_timeout(200)
    except Exception as e:
        logger.debug(f"Erratic scroll failed (ignoring): {e}")
