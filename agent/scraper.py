import asyncio
import logging
import random
from typing import List

import requests
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright

from agent.models import ScrapeResult
from agent.settings import AgentSettings

logger = logging.getLogger(__name__)

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_5) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
]


class AgentScraper:
    def __init__(self, settings: AgentSettings):
        self.settings = settings

    async def scrape_many(self, urls: List[str]) -> List[ScrapeResult]:
        semaphore = asyncio.Semaphore(self.settings.scrape_concurrency)
        results: List[ScrapeResult] = []

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)

            async def fetch(url: str) -> ScrapeResult:
                async with semaphore:
                    await asyncio.sleep(self.settings.scrape_delay_sec)
                    return await self._scrape_with_playwright(browser, url)

            tasks = [fetch(url) for url in urls]
            for result in await asyncio.gather(*tasks):
                results.append(result)

            await browser.close()

        return results

    async def _scrape_with_playwright(self, browser, url: str) -> ScrapeResult:
        user_agent = random.choice(USER_AGENTS)
        last_error = None
        for attempt in range(self.settings.scrape_retries + 1):
            try:
                context = await browser.new_context(user_agent=user_agent,locale="en-US",timezone_id="America/New_York")
                page = await context.new_page()
                response = await page.goto(
                    url,
                    wait_until="domcontentloaded",
                    timeout=self.settings.scrape_timeout_sec * 1000,
                )
                if not response:
                    await context.close()
                    raise ValueError("no response")

                html = await page.content()
                title = await page.title()
                text = self._extract_text(html)
                status_code = response.status
                await context.close()
                return ScrapeResult(
                    url=url,
                    title=title,
                    text=text,
                    html=html,
                    status_code=status_code,
                )
            except Exception as exc:
                last_error = exc
                logger.warning(f"Playwright attempt {attempt + 1} failed for {url}: {exc}")
                await asyncio.sleep(self.settings.scrape_delay_sec * (attempt + 1))

        return self._fallback_requests(url, str(last_error))

    def _fallback_requests(self, url: str, error: str) -> ScrapeResult:
        last_error = error
        for attempt in range(self.settings.scrape_retries + 1):
            try:
                headers = {"User-Agent": random.choice(USER_AGENTS)}
                resp = requests.get(url, headers=headers, timeout=self.settings.scrape_timeout_sec)
                html = resp.text
                text = self._extract_text(html)
                title = self._extract_title(html)
                return ScrapeResult(
                    url=url,
                    title=title,
                    text=text,
                    html=html,
                    status_code=resp.status_code,
                    error=None if resp.status_code == 200 else error,
                )
            except Exception as exc:
                last_error = str(exc)
        return ScrapeResult(url=url, error=last_error)

    @staticmethod
    def _extract_text(html: str) -> str:
        soup = BeautifulSoup(html or "", "lxml")
        return soup.get_text(separator=" ", strip=True)

    @staticmethod
    def _extract_title(html: str) -> str:
        soup = BeautifulSoup(html or "", "lxml")
        if soup.title and soup.title.string:
            return soup.title.string.strip()
        return ""
