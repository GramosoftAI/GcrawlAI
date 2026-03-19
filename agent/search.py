import logging
from typing import List

import requests
from ddgs import DDGS

from agent.models import SearchResult
from agent.settings import AgentSettings

logger = logging.getLogger(__name__)


class SearchClient:
    def __init__(self, settings: AgentSettings):
        self.settings = settings

    def search(self, query: str, limit: int) -> List[SearchResult]:
        provider = self.settings.search_provider
        if provider == "tavily":
            results = self._tavily_search(query, limit)
            if results:
                return results
        elif provider == "serpapi":
            results = self._serpapi_search(query, limit)
            if results:
                return results

        return self._duckduckgo_search(query, limit)

    def _tavily_search(self, query: str, limit: int) -> List[SearchResult]:
        if not self.settings.tavily_api_key:
            return []
        try:
            resp = requests.post(
                "https://api.tavily.com/search",
                json={
                    "api_key": self.settings.tavily_api_key,
                    "query": query,
                    "max_results": limit,
                },
                timeout=15,
            )
            resp.raise_for_status()
            payload = resp.json()
            results = []
            for item in payload.get("results", []):
                results.append(
                    SearchResult(
                        url=item.get("url"),
                        title=item.get("title"),
                        description=item.get("content"),
                    )
                )
            return results
        except Exception as exc:
            logger.warning(f"Tavily search failed: {exc}")
            return []

    def _serpapi_search(self, query: str, limit: int) -> List[SearchResult]:
        if not self.settings.serpapi_api_key:
            return []
        try:
            resp = requests.get(
                "https://serpapi.com/search.json",
                params={
                    "q": query,
                    "engine": self.settings.serpapi_engine,
                    "num": limit,
                    "api_key": self.settings.serpapi_api_key,
                },
                timeout=15,
            )
            resp.raise_for_status()
            payload = resp.json()
            results = []
            for item in payload.get("organic_results", []):
                results.append(
                    SearchResult(
                        url=item.get("link"),
                        title=item.get("title"),
                        description=item.get("snippet"),
                    )
                )
            return results
        except Exception as exc:
            logger.warning(f"SerpAPI search failed: {exc}")
            return []

    def _duckduckgo_search(self, query: str, limit: int) -> List[SearchResult]:
        try:
            ddgs = DDGS()
            raw_results = list(ddgs.text(query, max_results=limit))
            results = []
            for item in raw_results:
                results.append(
                    SearchResult(
                        url=item.get("href"),
                        title=item.get("title"),
                        description=item.get("body"),
                    )
                )
            return results
        except Exception as exc:
            logger.warning(f"DuckDuckGo search failed: {exc}")
            return []
