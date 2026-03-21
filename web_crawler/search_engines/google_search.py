"""
Google Search Engine Module

Scrapes Google search results using Playwright with anti-bot evasion.
"""

import logging
from typing import List, Dict, Optional
from playwright.sync_api import sync_playwright

logger = logging.getLogger(__name__)


def scrape_google(query: str, limit: int = 10, ip: Optional[str] = None, headless: bool = True) -> List[Dict[str, str]]:
    """
    Scrape Google search results using Playwright.

    Args:
        query: Search query string
        limit: Maximum number of results to return
        headless: Run browser in headless mode

    Returns:
        List of search results with url, title, description, and position
    """
    all_results = []
    page_num = 0

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=headless,
                args=[
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-blink-features=AutomationControlled",
                ],
            )

            context = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                viewport={"width": 1280, "height": 800},
            )

            context.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            """)

            page = context.new_page()

            while len(all_results) < limit:
                # Build Google search URL with start parameter
                start = page_num * 10
                url = f"https://www.google.com/search?q={query}&start={start}&num=10"

                logger.info(f"📄 [GOOGLE] Fetching page {page_num + 1}: {url}")
                page.goto(url, wait_until="domcontentloaded", timeout=60000)

                # Check if we hit an error page or block
                try:
                    # Check for Google's actual error/verification page
                    error_selector = page.locator('div#main > div > div > div > h1')
                    if error_selector.is_visible(timeout=3000):
                        error_text = error_selector.inner_text()
                        if 'unusual traffic' in error_text.lower() or 'detected automated traffic' in error_text.lower():
                            logger.warning("⚠️ [GOOGLE] Hit verification page - waiting 5s")
                            page.wait_for_timeout(5000)
                    # Check for CAPTCHA challenge
                    captcha = page.locator('g-recaptcha')
                    if captcha.is_visible(timeout=3000):
                        logger.warning("⚠️ [GOOGLE] CAPTCHA challenge detected - waiting 5s")
                        page.wait_for_timeout(5000)
                except Exception:
                    pass

                # Accept cookie consent
                try:
                    accept_btn = page.locator('button:has-text("Accept all")')
                    if accept_btn.is_visible(timeout=5000):
                        accept_btn.click()
                        page.wait_for_timeout(1000)
                except Exception:
                    pass

                # Wait for results to render
                page.wait_for_selector('#rso', timeout=10000)
                page.wait_for_timeout(500)  # Brief wait for dynamic content

                # Scrape this page
                page_results = page.evaluate("""
                    () => {
                        const items = [];
                        const seenUrls = new Set();

                        const containers = document.querySelectorAll('#rso > div, .g, [data-ved]');

                        containers.forEach((container) => {
                            const titleEl = container.querySelector('h3, .LC20lb, .MBeuA, .DKV0m');
                            const linkEl = container.querySelector('a');
                            const snippetEl = container.querySelector('.VwiC3b, .y29Spd, .aCQRe');

                            const title = titleEl ? (titleEl.innerText || titleEl.textContent).trim() : null;
                            const url = linkEl ? linkEl.href : null;
                            const snippet = snippetEl ? (snippetEl.innerText || snippetEl.textContent).trim() : '';

                            if (!title || !url || !url.startsWith('http')) return;
                            if (url.includes('google')) return;
                            if (seenUrls.has(url)) return;
                            if (container.querySelector('text-ad, .pla-unit')) return;

                            seenUrls.add(url);
                            items.push({ title, url, snippet });
                        });

                        return items;
                    }
                """)

                if not page_results:
                    logger.info("[GOOGLE] No more results found")
                    break

                # Add positions and merge
                for item in page_results:
                    item['position'] = len(all_results) + 1
                    all_results.append({
                        'url': item['url'],
                        'title': item['title'],
                        'description': item['snippet']
                    })

                logger.info(f"✅ [GOOGLE] Page {page_num + 1}: found {len(page_results)} results, total: {len(all_results)}")

                if len(all_results) >= limit:
                    break

                page_num += 1

            # Keep only requested limit
            all_results = all_results[:limit]
            browser.close()
            logger.info(f"✅ [GOOGLE] Final: {len(all_results)} results for: {query}")

    except Exception as e:
        logger.error(f"[GOOGLE] Search failed: {e}")
        return []

    return all_results
