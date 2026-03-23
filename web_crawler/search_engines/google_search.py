"""
Google Search Engine Module

Scrapes Google search results using Playwright with anti-bot evasion.
"""

import os
import random
import logging
from typing import List, Dict, Optional
from playwright.sync_api import sync_playwright
from dotenv import load_dotenv

load_dotenv(override=True)

logger = logging.getLogger(__name__)


def scrape_google(query: str, limit: int = 10, ip: Optional[str] = None, headless: bool = False, fast_mode: bool = False) -> List[Dict[str, str]]:
    """
    Scrape Google search results using Playwright with residential proxy support.

    Args:
        query: Search query string
        limit: Maximum number of results to return
        ip: Client IP for locale detection (unused, kept for compatibility)
        headless: Run browser in headless mode (default False for production)
        fast_mode: If True, skip delays and return immediately when limit is met (default False)

    Returns:
        List of search results with url, title, description, and position
    """
    all_results = []
    page_num = 0

    # Load EVOMI proxy credentials from environment
    proxy_server = os.getenv("EVOMI_PROXY_SERVER")
    proxy_username = os.getenv("EVOMI_PROXY_USERNAME")
    proxy_password = os.getenv("EVOMI_PROXY_PASSWORD")

    use_proxy = bool(proxy_server and proxy_username and proxy_password)

    # Rotate user agents to avoid detection
    user_agents = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    ]

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

            # Configure context with proxy if credentials are available
            if use_proxy:
                logger.info(f"🔐 [GOOGLE] Using EVOMI residential proxy: {proxy_server}")
                context = browser.new_context(
                    proxy={
                        "server": proxy_server,
                        "username": proxy_username,
                        "password": proxy_password,
                    },
                    user_agent=user_agents[page_num % len(user_agents)],
                    viewport={"width": 1280, "height": 800},
                )
            else:
                logger.warning("⚠️ [GOOGLE] No proxy credentials found - running without proxy")
                context = browser.new_context(
                    user_agent=user_agents[page_num % len(user_agents)],
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

                # Add random delay before request (skip in fast_mode for first page)
                if not fast_mode or page_num > 0:
                    delay = random.uniform(3, 7) if page_num > 0 else random.uniform(1, 2)
                    logger.info(f"⏱️ [GOOGLE] Waiting {delay:.1f}s before request...")
                    page.wait_for_timeout(delay * 1000)

                page.goto(url, wait_until="networkidle", timeout=60000)

                # Scroll like a human would (skip in fast_mode)
                if not fast_mode:
                    try:
                        page.evaluate("window.scrollTo(0, 200)")
                        page.wait_for_timeout(random.uniform(500, 1000))
                        page.evaluate("window.scrollTo(0, 500)")
                        page.wait_for_timeout(random.uniform(500, 1000))
                    except Exception:
                        pass

                # Debug: log page title and check if we're being blocked
                page_title = page.title()
                logger.info(f"📄 [GOOGLE] Page title: {page_title}")

                # Check for "Our systems have detected unusual traffic" or similar blocks
                page_content = page.content()
                if 'detected unusual traffic' in page_content.lower() or 'automated traffic' in page_content.lower():
                    logger.warning("⚠️ [GOOGLE] Possible blocking detected - attempting to continue")

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

                # Wait for results to render - use modern Google selectors
                try:
                    # Try multiple selectors for Google's current layout
                    page.wait_for_selector('div.g, div.N54PNb, div[data-async-trigger]', timeout=15000)
                except Exception:
                    logger.warning("⚠️ [GOOGLE] Waiting for results with extended timeout")
                    page.wait_for_timeout(5000)

                # Scrape this page using updated selectors for Google's current HTML structure
                page_results = page.evaluate("""
                    () => {
                        const items = [];
                        const seenUrls = new Set();

                        // Try multiple container selectors for current Google layout
                        const containers = document.querySelectorAll(
                            'div.g, ' +
                            'div.N54PNb, ' +
                            'div[data-async-trigger], ' +
                            '#rso > div, ' +
                            '#search div'
                        );

                        for (const container of containers) {
                            // Skip ads and sponsored content
                            if (container.querySelector('text-ad, .pla-unit, .commercial-unit')) continue;

                            // Find title - try multiple selectors for current Google
                            const titleSelectors = [
                                'h3.LC20lb',
                                'h3.DDVkf',
                                'h3.rlfFr',
                                'div.nv3DT',
                                'span.qXLe8d',
                                'h3'
                            ];
                            let titleEl = null;
                            for (const sel of titleSelectors) {
                                titleEl = container.querySelector(sel);
                                if (titleEl) break;
                            }

                            // Find link
                            const linkEl = container.querySelector('a');

                            // Find snippet/description - try multiple selectors
                            const snippetSelectors = [
                                'div.VwiC3b',
                                'div.y29Spd',
                                'span.aCQRe',
                                'div.MUOJ1b',
                                'div.s3v9rd',
                                'div.IsZ2Pe'
                            ];
                            let snippetEl = null;
                            for (const sel of snippetSelectors) {
                                snippetEl = container.querySelector(sel);
                                if (snippetEl) break;
                            }

                            const title = titleEl ? (titleEl.innerText || titleEl.textContent).trim() : null;
                            const url = linkEl ? linkEl.href : null;
                            const snippet = snippetEl ? (snippetEl.innerText || snippetEl.textContent).trim() : '';

                            // Validate
                            if (!title || !url || !url.startsWith('http')) continue;
                            if (url.includes('google.com')) continue;
                            if (seenUrls.has(url)) continue;

                            seenUrls.add(url);
                            items.push({ title, url, snippet });
                        }

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

                # Return immediately if we have enough results (fast response)
                if len(all_results) >= limit:
                    logger.info(f"✅ [GOOGLE] Got {len(all_results)} results (>= {limit}), returning immediately")
                    break

                # Wait longer between pages to avoid rate limiting (skip in fast_mode)
                if not fast_mode:
                    wait_time = random.uniform(8, 15)
                    logger.info(f"⏱️ [GOOGLE] Waiting {wait_time:.1f}s between pages...")
                    page.wait_for_timeout(wait_time * 1000)

                page_num += 1

            # Keep only requested limit
            all_results = all_results[:limit]
            browser.close()
            logger.info(f"✅ [GOOGLE] Final: {len(all_results)} results for: {query}")

    except Exception as e:
        logger.error(f"[GOOGLE] Search failed: {e}")
        return []

    return all_results
