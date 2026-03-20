import asyncio
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from agent.credits import CreditLimitExceeded, CreditTracker
from agent.db import AgentRepository
from agent.extractor import Extractor, ExtractionError
from agent.llm import ClaudeProvider, LLMRouter, OpenAIProvider
from agent.models import Plan, ScrapeResult
from agent.planner import Planner
from agent.search import SearchClient
from agent.scraper import AgentScraper
from agent.settings import AgentSettings

logger = logging.getLogger(__name__)


class JobCancelled(Exception):
    pass


class AgentPipeline:
    def __init__(self, settings: Optional[AgentSettings] = None):
        self.settings = settings or AgentSettings()
        self.settings.validate()

        self.repo = AgentRepository()
        self.search_client = SearchClient(self.settings)
        self.scraper = AgentScraper(self.settings)

        if self.settings.llm_provider == "anthropic":
            primary_provider = ClaudeProvider(self.settings.anthropic_api_key)
            fallback_provider = OpenAIProvider(self.settings.openai_api_key)
            planner_router = LLMRouter(
                primary=primary_provider,
                fallback=fallback_provider,
                fallback_model=self.settings.planner_model,
            )
            extractor_router = LLMRouter(
                primary=primary_provider,
                fallback=fallback_provider,
                fallback_model=self.settings.extraction_model,
            )
        else:
            primary_provider = OpenAIProvider(self.settings.openai_api_key)
            fallback_provider = ClaudeProvider(self.settings.anthropic_api_key)
            planner_router = LLMRouter(
                primary=primary_provider,
                fallback=fallback_provider,
                fallback_model=self.settings.fallback_model,
            )
            extractor_router = planner_router

        self.planner = Planner(planner_router, self.settings.planner_model)
        self.extractor = Extractor(
            extractor_router,
            self.settings.extraction_model,
            max_retries=self.settings.schema_max_retries,
        )

    def run(self, job_id: str) -> None:
        job = self.repo.get_job(job_id)
        if not job:
            logger.error(f"Agent job {job_id} not found")
            return

        tracker = CreditTracker(job["max_credits"])
        tracker.used = job.get("credits_used", 0)

        try:
            self._log(job_id, "start", "Starting agent pipeline")
            self._ensure_not_cancelled(job_id)

            plan = self._plan(job, tracker)
            self._ensure_not_cancelled(job_id)

            urls = self._resolve_urls(job, plan, tracker)
            self._ensure_not_cancelled(job_id)

            pages = self._scrape_pages(job_id, urls, tracker)
            self._ensure_not_cancelled(job_id)

            data = self._extract_data(job, pages, tracker)
            self._ensure_not_cancelled(job_id)

            expires_at = datetime.utcnow() + timedelta(hours=self.settings.result_ttl_hours)
            self.repo.update_job(
                job_id,
                status="completed",
                result_json=data,
                error=None,
                expires_at=expires_at,
            )
            self._log(job_id, "complete", "Job completed successfully")
        except CreditLimitExceeded as exc:
            self.repo.update_job(job_id, status="failed", result_json=None, error=str(exc))
            self._log(job_id, "credits", f"Credit limit exceeded: {exc}")
        except JobCancelled:
            self.repo.update_job(job_id, status="cancelled", result_json=None, error="Cancelled by user")
            self._log(job_id, "cancel", "Job cancelled")
        except ExtractionError as exc:
            self.repo.update_job(job_id, status="failed", result_json=None, error=str(exc))
            self._log(job_id, "extract", f"Extraction failed: {exc}")
        except Exception as exc:
            logger.exception("Agent pipeline failed")
            self.repo.update_job(job_id, status="failed", result_json=None, error=str(exc))
            self._log(job_id, "error", f"Pipeline failed: {exc}")

    def _plan(self, job: Dict[str, Any], tracker: CreditTracker) -> Plan:
        self._log(job["job_id"], "plan", "Running planning model")
        result = self.planner.plan(
            prompt=job["prompt"],
            urls=job.get("urls"),
            schema=job.get("schema_json"),
            strict=job.get("strict_constrain", False),
        )
        self._charge(job["job_id"], tracker, self.settings.credit_cost_planner, "planning")
        return result

    def _resolve_urls(self, job: Dict[str, Any], plan: Plan, tracker: CreditTracker) -> List[str]:
        urls: List[str] = []
        provided_urls = job.get("urls") or []
        strict = job.get("strict_constrain", False)

        if provided_urls:
            urls.extend(provided_urls)

        if not strict:
            urls.extend(plan.target_urls or [])

            queries = plan.search_queries or [job["prompt"]]
            for query in queries:
                self._log(job["job_id"], "search", f"Searching: {query}")
                results = self.search_client.search(query, self.settings.search_results_per_query)
                self._charge(job["job_id"], tracker, self.settings.credit_cost_search, "search")
                urls.extend([item.url for item in results if item.url])

        urls = self._dedupe_urls(urls)
        limit = plan.max_pages or self.settings.max_urls
        urls = urls[:limit]

        if strict and not urls:
            raise ValueError("strictConstrainToURLs enabled but no URLs provided")
        if not urls:
            raise ValueError("No URLs found for extraction")

        return urls

    def _scrape_pages(self, job_id: str, urls: List[str], tracker: CreditTracker) -> List[ScrapeResult]:
        self._log(job_id, "scrape", f"Scraping {len(urls)} URLs")

        total_cost = self.settings.credit_cost_scrape * len(urls)
        self._charge(job_id, tracker, total_cost, "scrape")

        pages = asyncio.run(self.scraper.scrape_many(urls))
        usable = [page for page in pages if page.text and not page.error]
        if not usable:
            raise ValueError("All scraping attempts failed")
        return usable

    def _extract_data(
        self,
        job: Dict[str, Any],
        pages: List[ScrapeResult],
        tracker: CreditTracker,
    ) -> Dict[str, Any]:
        schema = job.get("schema_json")
        if not schema:
            schema = {
                "type": "object",
                "properties": {
                    "answer": {"type": "string"},
                    "sources": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                },
                "required": ["answer", "sources"],
                "additionalProperties": False,
            }
            combined = "\n\n".join([page.text or "" for page in pages])
            context = {"sources": [page.url for page in pages]}
            result = self.extractor.extract(schema, combined, context)
            self._charge(job["job_id"], tracker, self.settings.credit_cost_extraction, "extract")
            if result.used_fallback:
                self._charge(job["job_id"], tracker, self.settings.credit_cost_fallback, "fallback")
            return result.data

        results: List[Dict[str, Any]] = []
        for page in pages:
            context = {"url": page.url, "title": page.title or ""}
            try:
                result = self.extractor.extract(schema, page.text or "", context)
                self._charge(job["job_id"], tracker, self.settings.credit_cost_extraction, "extract")
                if result.used_fallback:
                    self._charge(job["job_id"], tracker, self.settings.credit_cost_fallback, "fallback")
                results.append(result.data)
            except Exception as exc:
                self._log(job["job_id"], "extract", f"Extraction failed for {page.url}: {exc}")
                continue

        if not results:
            raise ExtractionError("No valid extraction results")

        return self._merge_results(schema, results)

    def _merge_results(self, schema: Dict[str, Any], results: List[Dict[str, Any]]) -> Dict[str, Any]:
        if not results:
            return {}

        schema_type = schema.get("type", "object")
        if schema_type == "array":
            merged = []
            for item in results:
                if isinstance(item, list):
                    merged.extend(item)
                else:
                    merged.append(item)
            return merged

        if schema_type != "object":
            return results[0]

        merged: Dict[str, Any] = {}
        properties = schema.get("properties", {})
        for item in results:
            if not isinstance(item, dict):
                continue
            for key, value in item.items():
                prop_schema = properties.get(key, {})
                merged[key] = self._merge_value(merged.get(key), value, prop_schema)
        return merged

    @staticmethod
    def _merge_value(existing: Any, new: Any, schema: Dict[str, Any]) -> Any:
        if existing is None:
            return new
        if new is None:
            return existing
        if schema.get("type") == "array":
            merged = []
            merged.extend(existing if isinstance(existing, list) else [existing])
            merged.extend(new if isinstance(new, list) else [new])
            seen = set()
            deduped = []
            for item in merged:
                key = str(item)
                if key in seen:
                    continue
                seen.add(key)
                deduped.append(item)
            return deduped
        if schema.get("type") == "object" and isinstance(existing, dict) and isinstance(new, dict):
            combined = dict(existing)
            for k, v in new.items():
                combined[k] = v if combined.get(k) is None else combined[k]
            return combined
        return existing if existing else new

    def _charge(self, job_id: str, tracker: CreditTracker, amount: int, label: str) -> None:
        if amount <= 0:
            return
        self.repo.increment_credits(job_id, amount)
        tracker.add(amount)
        self._log(job_id, "credits", f"{label}: +{amount}")

    def _log(self, job_id: str, step: str, message: str) -> None:
        try:
            self.repo.append_log(job_id, step, message)
        except Exception:
            logger.warning("Failed to log job step")

    def _ensure_not_cancelled(self, job_id: str) -> None:
        if self.repo.is_cancelled(job_id):
            raise JobCancelled()

    @staticmethod
    def _dedupe_urls(urls: List[str]) -> List[str]:
        seen = set()
        deduped = []
        for url in urls:
            if not url or url in seen:
                continue
            seen.add(url)
            deduped.append(url)
        return deduped
