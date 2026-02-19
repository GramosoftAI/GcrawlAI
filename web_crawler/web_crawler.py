"""
Main web crawler orchestration
"""

import json
import logging
import pytz
from collections import deque
from datetime import datetime
from time import perf_counter
from typing import Set, List, Dict, Optional
from urllib.parse import urlparse
import threading
from threading import Semaphore, Thread

from web_crawler.config import CrawlConfig
from web_crawler.file_manager import FileManager
from web_crawler.page_crawler import PageCrawler
from web_crawler.seo_report import CrawlReportWriter
from web_crawler.utils import normalize_url

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

    def crawl(
        self,
        start_url: str,
        enable_md: bool = False,
        enable_html: bool = False,
        enable_ss: bool = False,
        enable_json: bool = True,
        enable_links: bool = True,
        enable_seo: bool = False,
        client_id: Optional[str] = None,
        websocket_manager=None,
        crawl_mode: str = "all"
    ) -> Dict:
        """Main crawl orchestration"""

        max_pages = 1 if crawl_mode == "single" else self.config.max_pages

        tz = pytz.timezone(self.config.timezone)
        start_time = datetime.now(tz)
        start_perf = perf_counter()

        queue = deque([(start_url, "START")])
        seen_raw = {start_url}

        attempted_pages = 0
        successful_pages = 0

        semaphore = Semaphore(self.config.max_workers)
        threads: List[Thread] = []
        lock = threading.Lock()

        logger.info("🚀 Crawl started")

        # =========================================================
        # SINGLE PAGE MODE (NO THREADING)
        # =========================================================
        if crawl_mode == "single":
            logger.info("🔹 Single-page crawl mode")

            result = self.page_crawler.crawl_page(
                start_url,
                count=1,
                enable_md=enable_md,
                enable_html=enable_html,
                enable_ss=enable_ss,
                enable_seo=enable_seo,
                client_id=client_id,
                websocket_manager=websocket_manager,
            )

            elapsed = perf_counter() - start_perf
            
            if result:
                if enable_seo:
                    try:
                        writer = CrawlReportWriter(self.config.output_dir)
                        domain = urlparse(start_url).netloc
                        
                        # For single page, links are just from that page
                        page_links = result.get("links", [])
                        
                        writer.save_json(domain, [result], page_links)
                        writer.save_markdown(domain, [result], page_links)
                        writer.save_excel(domain, [result])
                    except Exception as e:
                        logger.error(f"Failed to save SEO report: {e}")

                if enable_links and "links" in result:
                    with open(self.config.links_file, "w", encoding="utf-8") as f:
                        f.write("\n".join(sorted(result["links"])))
            
            file_name = result.get("markdown_file", "None") if result and crawl_mode == "single" else "None"

            summary = {
                "start_url": start_url,
                "pages_crawled": 1 if result else 0,
                "pages_failed": 0 if result else 1,
                "total_links_found": len(result.get("links", [])) if result else 0,
                "started_at": start_time.strftime("%Y-%m-%d %H:%M:%S %Z"),
                "time_taken": f"{int(elapsed//60)}m {int(elapsed%60)}s",
                "crawl_mode": crawl_mode,
                "markdown_file": file_name,
            }

            with open(self.config.summary_file, "w", encoding="utf-8") as f:
                json.dump(summary, f, indent=2)

            logger.info("✅ Single-page crawl finished")
            logger.info(json.dumps(summary, indent=2))
            return summary

        # =========================================================
        # WORKER FUNCTION
        # =========================================================
        def crawl_worker(url: str, page_no: int):
            nonlocal successful_pages

            try:
                result = self.page_crawler.crawl_page(
                    url,
                    page_no,
                    enable_md,
                    enable_html,
                    enable_ss,
                    enable_seo,
                    client_id,
                    websocket_manager,
                )

                if not result:
                    with lock:
                        self.failed.add(url)
                    logger.warning(f"Failed: {url}")
                    return

                canonical = result["canonical"]

                with lock:
                    if canonical in self.visited_canonical:
                        logger.info(f"Skipping duplicate canonical: {canonical}")
                        return

                    self.visited_canonical.add(canonical)
                    successful_pages += 1

                    if enable_json:
                        self.pages_data.append(result)

                logger.info(f"✓ Success [{successful_pages}]: {canonical}")

                if crawl_mode == "all":
                    for link in result["links"]:
                        with lock:
                            if link in seen_raw:
                                continue
                            seen_raw.add(link)
                            self.all_links.add(link)

                            if urlparse(link).netloc == urlparse(start_url).netloc:
                                queue.append((link, url))

            finally:
                semaphore.release()

        # =========================================================
        # MAIN SEMAPHORE-BASED CRAWL LOOP
        # =========================================================
        while (queue or semaphore._value < self.config.max_workers) and attempted_pages < max_pages:

            if queue:
                url, source = queue.popleft()
                url = normalize_url(url)

                with lock:
                    if url in self.visited:
                        continue
                    self.visited.add(url)
                    attempted_pages += 1
                    page_no = attempted_pages

                logger.info(f"Queued [{attempted_pages}/{max_pages}]: {url}")

                semaphore.acquire()

                t = Thread(
                    target=crawl_worker,
                    args=(url, page_no),
                    daemon=True,
                )
                t.start()
                threads.append(t)

            else:
                # Workers are still running, wait for them to enqueue links
                threading.Event().wait(0.05)


        # =========================================================
        # WAIT FOR ALL THREADS
        # =========================================================
        for t in threads:
            t.join()

        # =========================================================
        # SAVE OUTPUTS
        # =========================================================
        if enable_links:
            with open(self.config.links_file, "w", encoding="utf-8") as f:
                f.write("\n".join(sorted(self.all_links)))

        if enable_json:
            with open(self.config.json_file, "w", encoding="utf-8") as f:
                json.dump(self.pages_data, f, indent=2)

        if enable_seo:
            try:
                writer = CrawlReportWriter(self.config.output_dir)
                domain = urlparse(start_url).netloc
                
                # Match seo.py structure: expects (domain, seo_data, links)
                # But CrawlReportWriter.save_outputs matches seo.py logic if we update it
                # For now, let's use the existing writer methods but ensure data is correct
                
                # We need to pass the list of all links found
                all_links_list = sorted(list(self.all_links))
                
                writer.save_json(domain, self.pages_data, all_links_list)
                writer.save_markdown(domain, self.pages_data, all_links_list)
                writer.save_excel(domain, self.pages_data)
            except Exception as e:
                logger.error(f"Failed to save SEO report: {e}")

        # =========================================================
        # SUMMARY
        # =========================================================
        elapsed = perf_counter() - start_perf

        summary = {
            "start_url": start_url,
            "pages_attempted": attempted_pages,
            "pages_crawled": successful_pages,
            "pages_failed": len(self.failed),
            "total_links_found": len(self.all_links),
            "started_at": start_time.strftime("%Y-%m-%d %H:%M:%S %Z"),
            "time_taken": f"{int(elapsed//60)}m {int(elapsed%60)}s",
        }

        with open(self.config.summary_file, "w", encoding="utf-8") as f:
            json.dump(summary, f, indent=2)

        logger.info("✅ Crawl finished")
        logger.info(json.dumps(summary, indent=2))
        return summary
