"""
Main web crawler orchestration
"""

import json
import logging
import pytz
import re
import os
import threading
import base64
from collections import deque
from datetime import datetime
from time import perf_counter
from typing import Set, List, Dict, Optional
from urllib.parse import urlparse
from threading import Semaphore, Thread
from concurrent.futures import ThreadPoolExecutor

from web_crawler.common.config import CrawlConfig
from web_crawler.crawler.helpers.file_manager import FileManager
from web_crawler.crawler.page_crawler import PageCrawler
from web_crawler.crawler.helpers.seo_report import CrawlReportWriter
from web_crawler.common.utils import normalize_url
from web_crawler.crawler.map.map_crawler import map_website
from api.core.database import upsert_job_result

# Import search and canonical delegates
from web_crawler.crawler.helpers.crawler_search import (
    _is_search_url,
    _extract_search_query,
    _format_search_results_markdown,
    _format_search_results_html,
)
from web_crawler.crawler.helpers.crawler_canonical import resolve_canonical_url

logger = logging.getLogger(__name__)


class WebCrawler:
    """Main crawler orchestrator"""

    def __init__(self, config: CrawlConfig):
        self.config = config
        self.file_manager = FileManager()
        self.page_crawler = PageCrawler(config, self.file_manager)

        # Shared state
        self.visited: Set[str] = set()
        self.visited_canonical: Set[str] = set()
        self.failed: Set[str] = set()
        self.all_links: Set[str] = set()
        self.pages_data: List[Dict] = []
        
        self.successful_pages = 0
        self.attempted_pages = 0

    def _effective_proxy_mode(self) -> str:
        mode = (self.config.proxy_mode or "auto").strip().lower()
        if mode in {"basic", "stealth", "enhanced", "auto"}:
            return mode
        return "auto"

    def _initial_proxy_type(self) -> str:
        """
        In auto mode, start with basic and escalate later only if needed.
        """
        mode = self._effective_proxy_mode()
        return "basic" if mode == "auto" else mode

    def _crawl_worker(
        self,
        url: str,
        page_no: int,
        enable_md: bool,
        enable_html: bool,
        enable_ss: bool,
        enable_seo: bool,
        enable_images: bool,
        enable_json: bool,
        client_id: Optional[str],
        websocket_manager,
        crawl_mode: str,
        start_time,
        start_perf,
        lock,
        user_id,
        seen_raw,
        queue
    ):
        try:
            proxy_type = self._effective_proxy_mode()
            result = self.page_crawler.crawl_page(
                url,
                page_no,
                enable_md,
                enable_html,
                enable_ss,
                enable_seo,
                enable_images,
                enable_json=enable_json,
                client_id=client_id,
                websocket_manager=websocket_manager,
                crawl_mode=crawl_mode
            )

            if not result or "error" in result:
                with lock:
                    self.failed.add(url)
                logger.warning(f"Failed: {url} - {result.get('error') if result else 'Unknown error'}")
                return

            canonical = result["canonical"]

            with lock:
                if canonical in self.visited_canonical:
                    logger.info(f"Skipping duplicate canonical: {canonical}")
                    return

                self.visited_canonical.add(canonical)
                self.successful_pages += 1

                if enable_json:
                    self.pages_data.append(result)

            # Save individual page summary
            try:
                save_payload = {
                    "start_url": result.get("url"),
                    "pages_crawled": 1,
                    "pages_failed": 0,
                    "started_at": start_time.strftime("%Y-%m-%d %H:%M:%S %Z"),
                    "time_taken": f"{int((perf_counter() - start_perf)//60)}m {int((perf_counter() - start_perf)%60)}s",
                    "crawl_mode": crawl_mode,
                    "html_content": result.get("html_content"),
                    "markdown_content": result.get("markdown_content"),
                    "screenshot_s3_url": result.get("screenshot_s3_url"),
                    "images_json": result.get("images_json")
                }
                if enable_seo:
                    if result.get("seo_json"):
                        try:
                            save_payload["seo_json"] = json.loads(result.get("seo_json"))
                        except Exception:
                            save_payload["seo_json"] = result.get("seo_json")
                    else:
                        save_payload["seo_json"] = None
                        
                    save_payload["seo_md"] = result.get("seo_md")
                    save_payload["seo_xlsx_s3_url"] = result.get("seo_xlsx_s3_url")

                upsert_job_result(client_id, save_payload, str(user_id) if user_id else None)
            except Exception as e:
                logger.error(f"Failed to upsert individual page summary: {e}")

            logger.info(f"✓ Success [{self.successful_pages}]: {canonical}")

            if crawl_mode == "all":
                for link in result["links"]:
                    with lock:
                        if link in seen_raw:
                            continue
                        seen_raw.add(link)
                        self.all_links.add(link)

                        def normalize_host(h):
                            h = h.lower()
                            return h[4:] if h.startswith("www.") else h

                        if normalize_host(urlparse(link).netloc) == normalize_host(urlparse(url).netloc):
                            queue.append((link, url))
        except Exception as e:
            logger.error(f"Error in _crawl_worker for {url}: {e}")

    def crawl(
        self,
        start_url: str,
        enable_md: bool = False,
        enable_html: bool = False,
        enable_ss: bool = False,
        enable_json: bool = True,
        enable_links: bool = True,
        enable_seo: bool = False,
        enable_images: bool = False,
        client_id: Optional[str] = None,
        user_id: Optional[int] = None,
        websocket_manager=None,
        crawl_mode: str = "all"
    ) -> Dict:
        """Main crawl orchestration"""

        max_pages = 1 if crawl_mode in ("single", "screenshot") else self.config.max_pages

        tz = pytz.timezone(self.config.timezone)
        start_time = datetime.now(tz)
        start_perf = perf_counter()

        parsed_start = urlparse(start_url)
        domain = parsed_start.netloc
        if domain.startswith("www."):
            domain = domain[4:]
        domain = domain.split('.')[0]
        path = parsed_start.path.strip('/')
        main_prefix = domain
        if path:
            path = re.sub(r'[^a-zA-Z0-9]+', '_', path)
            main_prefix = f"{domain}_{path}"
        
        self.config.summary_file = os.path.join(str(self.config.output_dir), f"{main_prefix}_summary.json")

        queue = deque([(start_url, "START")])
        seen_raw = {start_url}

        self.attempted_pages = 0
        self.successful_pages = 0

        semaphore = Semaphore(self.config.max_workers)
        threads: List[Thread] = []
        lock = threading.Lock()

        logger.info("🚀 Crawl started")

        # =========================================================
        # MAP MODE
        # =========================================================
        if crawl_mode == "links":
            logger.info("🗺️  Map mode — sitemap-based URL discovery (no browser)")

            providers = [
                ("Evomi Premium", "evomi_premium"),
                ("Nodemaven", "nodemaven"),
                ("Evomi Core", "evomi_core")
            ]
            
            map_result = {"total": 0, "urls": []}
            for attempt, (provider_name, provider_id) in enumerate(providers, 1):
                logger.info(f"  → Attempting map discovery with {provider_name} proxy (Attempt {attempt}/3)...")
                proxy_geo = getattr(self.config, "proxy_geo", None)
                use_hs = (provider_id in {"nodemaven", "evomi_premium"})
                p_dict = self.page_crawler.proxy_manager.get_requests_proxies(
                    target_url=start_url, provider=provider_id, use_high_speed=use_hs, proxy_geo=proxy_geo
                )
                if p_dict:
                    map_limit = self.config.max_pages if self.config.max_pages else 5000
                    map_result = map_website(start_url, limit=map_limit, proxy_dict=p_dict)
                    if map_result["total"] > 1:
                        logger.info(f"  ✓ Map discovery succeeded with {provider_name}")
                        break
                    logger.warning(f"  ! Map discovery yielded {map_result['total']} results with {provider_name}. Escalating...")

            elapsed = perf_counter() - start_perf

            discovered_urls = map_result["urls"]
            
            if self.config.max_pages and len(discovered_urls) > self.config.max_pages:
                discovered_urls = discovered_urls[:self.config.max_pages]
                map_result["total"] = len(discovered_urls)

            pass

            summary = {
                "start_url": start_url,
                "pages_crawled": 0,
                "pages_failed": 0,
                "started_at": start_time.strftime("%Y-%m-%d %H:%M:%S %Z"),
                "time_taken": f"{int(elapsed//60)}m {int(elapsed%60)}s",
                "crawl_mode": crawl_mode,
                "links": discovered_urls,
            }

            upsert_job_result(client_id, summary, str(user_id) if user_id else None)
            logger.info("✅ Map crawl finished")
            logger.info(json.dumps(summary, indent=2))
            return summary

        # =========================================================
        # SEARCH MODE
        # =========================================================
        if _is_search_url(start_url):
            query = _extract_search_query(start_url)
            logger.info(f"🔍 Search URL detected. Routing query '{query}' through search engine router...")
            
            import asyncio
            from web_crawler.search.search_engine import execute_search_router
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = None

            if loop and loop.is_running():
                search_results = asyncio.run_coroutine_threadsafe(
                    execute_search_router(query, limit=10), loop
                ).result()
            else:
                search_results = asyncio.run(execute_search_router(query, limit=10))
            elapsed = perf_counter() - start_perf
            
            if search_results:
                self.successful_pages = 1
                md_content = _format_search_results_markdown(query, search_results)
                html_content = _format_search_results_html(query, search_results)
                result_links = [r.get("url") for r in search_results if r.get("url")]
                
                if enable_md:
                    logger.info(f"📄 Search markdown generated in memory")
                
                screenshot_s3_url = None
                if enable_ss:
                    try:
                        from playwright.sync_api import sync_playwright
                        from web_crawler.common.s3_utils import upload_to_s3
                        with sync_playwright() as p:
                            browser = p.chromium.launch(headless=True)
                            page = browser.new_page(viewport={"width": 1280, "height": 800})
                            page.set_content(html_content)
                            page.wait_for_timeout(500)
                            screenshot_bytes = page.screenshot(full_page=True)
                            browser.close()
                            
                        screenshot_s3_url = upload_to_s3(
                            screenshot_bytes,
                            client_id if client_id else "search_crawl",
                            f"search_{query[:50].replace(' ', '_')}.png",
                            "image/png"
                        )
                    except Exception as e:
                        logger.error(f"Failed to capture search screenshot: {e}")
                
                result = {
                    "url": start_url,
                    "html_content": html_content if enable_html else None,
                    "markdown_content": md_content if enable_md else None,
                    "screenshot_s3_url": screenshot_s3_url,
                    "links": result_links,
                    "status_code": 200,
                }
                
                if enable_seo:
                    try:
                        seo_data = {
                            "url": start_url,
                            "title": f"Search Results: {query}",
                            "meta_description": f"Search results for '{query}' via DuckDuckGo",
                            "h1": f"Search Results: {query}",
                            "results_count": len(search_results),
                            "results": [
                                {"position": i+1, "title": r.get("title"), "url": r.get("url"), "description": r.get("description")}
                                for i, r in enumerate(search_results)
                            ]
                        }
                        
                        seo_result = {
                            "url": start_url,
                            "canonical": start_url,
                            "seo": seo_data,
                            "links": result_links,
                        }
                        
                        writer = CrawlReportWriter(self.config.output_dir)
                        domain = urlparse(start_url).netloc
                        writer.save_json(domain, [seo_result], result_links)
                        writer.save_markdown(domain, [seo_result], result_links)
                        writer.save_excel(domain, [seo_result])
                        logger.info(f"📊 Search SEO report saved")
                    except Exception as e:
                        logger.warning(f"SEO report generation failed: {e}")
                
            else:
                logger.warning(f"Search engine router returned no results for: {query}")
                result = {"url": start_url, "error": "No search results", "status_code": 404}
            
            summary = {
                "start_url": start_url,
                "pages_crawled": 1 if result and "error" not in result else 0,
                "pages_failed": 1 if not result or "error" in result else 0,
                "started_at": start_time.strftime("%Y-%m-%d %H:%M:%S %Z"),
                "time_taken": f"{int(elapsed//60)}m {int(elapsed%60)}s",
                "crawl_mode": "search",
                "search_query": query,
            }
            
            if result and "error" not in result:
                summary["html_content"] = result.get("html_content")
                summary["markdown_content"] = result.get("markdown_content")
                summary["screenshot_s3_url"] = result.get("screenshot_s3_url")
            
            upsert_job_result(client_id, summary, str(user_id) if user_id else None)            
            logger.info("✅ Search crawl finished")
            logger.info(json.dumps(summary, indent=2))
            return summary

        # =========================================================
        # SINGLE PAGE MODE
        # =========================================================
        if crawl_mode in ("single", "screenshot"):
            logger.info(f"🔹 Single-page crawl mode ({crawl_mode})")

            canonical_url = start_url

            result = self.page_crawler.crawl_page(
                canonical_url,
                count=1,
                enable_md=enable_md,
                enable_html=enable_html,
                enable_ss=enable_ss,
                enable_seo=enable_seo,
                enable_images=enable_images,
                enable_json=enable_json,
                client_id=client_id,
                websocket_manager=websocket_manager,
                crawl_mode=crawl_mode
            )

            if result and "error" not in result:
                self.successful_pages = 1

            elapsed = perf_counter() - start_perf
            
            summary = {
                "start_url": start_url,
                "pages_crawled": self.successful_pages,
                "pages_failed": 1 - self.successful_pages,
                "started_at": start_time.strftime("%Y-%m-%d %H:%M:%S %Z"),
                "time_taken": f"{int(elapsed//60)}m {int(elapsed%60)}s",
                "crawl_mode": crawl_mode,
            }
            
            if result and "error" not in result:
                if crawl_mode == "screenshot":
                    summary["screenshot_s3_url"] = result.get("screenshot_s3_url")
                else:
                    summary["html_content"] = result.get("html_content")
                    summary["markdown_content"] = result.get("markdown_content")
                    summary["screenshot_s3_url"] = result.get("screenshot_s3_url")
                    summary["images_json"] = result.get("images_json")
                    
                    if enable_seo:
                        if result.get("seo_json"):
                            try:
                                summary["seo_json"] = json.loads(result.get("seo_json"))
                            except Exception:
                                summary["seo_json"] = result.get("seo_json")
                        else:
                            summary["seo_json"] = None
                            
                        summary["seo_md"] = result.get("seo_md")
                        summary["seo_xlsx_s3_url"] = result.get("seo_xlsx_s3_url")

            upsert_job_result(client_id, summary, str(user_id) if user_id else None)
            logger.info("✅ Single-page crawl finished")
            logger.info(json.dumps(summary, indent=2))
            return summary

        # =========================================================
        # MAIN THREADPOOL-BASED CRAWL LOOP
        # =========================================================
        active_tasks = 0
        
        def worker_task(task_url, task_page_no):
            nonlocal active_tasks
            try:
                self._crawl_worker(
                    url=task_url,
                    page_no=task_page_no,
                    enable_md=enable_md,
                    enable_html=enable_html,
                    enable_ss=enable_ss,
                    enable_seo=enable_seo,
                    enable_images=enable_images,
                    enable_json=enable_json,
                    client_id=client_id,
                    websocket_manager=websocket_manager,
                    crawl_mode=crawl_mode,
                    start_time=start_time,
                    start_perf=start_perf,
                    lock=lock,
                    user_id=user_id,
                    seen_raw=seen_raw,
                    queue=queue
                )
            finally:
                with lock:
                    active_tasks -= 1

        with ThreadPoolExecutor(max_workers=self.config.max_workers) as executor:
            while (queue or active_tasks > 0) and self.attempted_pages < max_pages:
                if queue:
                    url, source = queue.popleft()
                    url = normalize_url(url)

                    with lock:
                        if url in self.visited:
                            continue
                        self.visited.add(url)
                        self.attempted_pages += 1
                        page_no = self.attempted_pages
                        active_tasks += 1

                    logger.info(f"Queued [{self.attempted_pages}/{max_pages}]: {url}")
                    executor.submit(worker_task, url, page_no)
                else:
                    threading.Event().wait(0.05)

            # Submit cleanup tasks to all threads in the pool to close the browsers cleanly
            cleanup_futures = []
            for _ in range(self.config.max_workers):
                def shutdown_task():
                    try:
                        from web_crawler.crawler.page.page_crawler1 import browser_manager
                        browser_manager.shutdown()
                    except Exception as e:
                        logger.warning(f"Error shutting down browser in thread cleanup: {e}")
                cleanup_futures.append(executor.submit(shutdown_task))
            
            # Wait for all cleanups to complete
            for future in cleanup_futures:
                try:
                    future.result()
                except Exception as e:
                    logger.warning(f"Error waiting for browser manager cleanup future: {e}")

        # =========================================================
        # SUMMARY & DATA CONSOLIDATION
        # =========================================================
        elapsed = perf_counter() - start_perf

        summary = {
            "start_url": start_url,
            "pages_attempted": self.attempted_pages,
            "pages_crawled": self.successful_pages,
            "pages_failed": len(self.failed),
            "started_at": start_time.strftime("%Y-%m-%d %H:%M:%S %Z"),
            "time_taken": f"{int(elapsed//60)}m {int(elapsed%60)}s",
        }
        
        if enable_seo and self.pages_data:
            try:
                from web_crawler.crawler.helpers.seo_report import CrawlReportWriter
                writer = CrawlReportWriter(self.config.output_dir)
                domain = urlparse(start_url).netloc
                all_links_list = sorted(list(self.all_links))
                
                summary["seo_aggregated_json"] = json.loads(writer.render_json(self.pages_data, all_links_list))
                summary["seo_aggregated_md"] = writer.render_markdown(domain, self.pages_data, all_links_list)
                
                from web_crawler.common.s3_utils import upload_to_s3
                seo_excel_b64 = writer.render_excel_base64(self.pages_data)
                seo_excel_url = upload_to_s3(
                    base64.b64decode(seo_excel_b64),
                    client_id if client_id else "unknown_crawl",
                    f"{domain}_seo.xlsx",
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                )
                summary["seo_aggregated_xlsx_s3_url"] = seo_excel_url
            except Exception as e:
                logger.error(f"Failed to generate SEO report in memory: {e}")

        if crawl_mode != "all":
            upsert_job_result(self.config.client_id, summary, str(user_id) if user_id else None)

        logger.info("✅ Crawl finished")
        logger.info(json.dumps(summary, indent=2))
        return summary
