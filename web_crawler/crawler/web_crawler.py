"""
Main web crawler orchestration
"""

import json
import logging
import pytz
import urllib.request
from collections import deque
from datetime import datetime
from time import perf_counter
from typing import Set, List, Dict, Optional
from urllib.parse import urlparse
import requests
import threading
from threading import Semaphore, Thread
from web_crawler.common.config import CrawlConfig
from web_crawler.crawler.file_manager import FileManager
from web_crawler.crawler.page_crawler import PageCrawler
from web_crawler.crawler.seo_report import CrawlReportWriter
from web_crawler.common.utils import normalize_url
from web_crawler.crawler.map_crawler import map_website
from web_crawler.search.search_engine import execute_search_router
from urllib.parse import urlparse, parse_qs

logger = logging.getLogger(__name__)


# Search engine domains that should be routed through the search API
SEARCH_ENGINE_DOMAINS = [
    "google.com", "google.co.in", "google.co.uk",
    "bing.com", "yahoo.com", "yandex.com",
    "duckduckgo.com", "search.brave.com",
]

def _is_search_url(url: str) -> bool:
    """Detect if a URL is a search engine results page."""
    parsed = urlparse(url)
    domain = parsed.netloc.lower().lstrip("www.")
    path = parsed.path.lower()
    query = parse_qs(parsed.query)
    
    # Must have a query parameter and be on a search path
    has_query = "q" in query or "query" in query or "search_query" in query
    is_search_path = "/search" in path or path == "/"
    is_search_domain = any(d in domain for d in SEARCH_ENGINE_DOMAINS)
    
    return is_search_domain and has_query and is_search_path

def _extract_search_query(url: str) -> str:
    """Extract the search query from a search engine URL."""
    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    return query.get("q", query.get("query", query.get("search_query", [""])))[-1]

def _format_search_results_markdown(query: str, results: list) -> str:
    """Format search results as clean markdown."""
    lines = [f"# Search Results: {query}\n"]
    for i, r in enumerate(results, 1):
        title = r.get("title", "Untitled")
        url = r.get("url", "")
        desc = r.get("description", "")
        lines.append(f"## {i}. [{title}]({url})\n")
        if desc:
            lines.append(f"{desc}\n")
        lines.append("")
    return "\n".join(lines)

def _format_search_results_html(query: str, results: list) -> str:
    """Format search results as HTML."""
    items = []
    for r in results:
        title = r.get("title", "Untitled")
        url = r.get("url", "")
        desc = r.get("description", "")
        items.append(f'<div class="result"><h3><a href="{url}">{title}</a></h3><p>{desc}</p></div>')
    body = "\n".join(items)
    return f"<html><head><title>Search: {query}</title></head><body><h1>Search Results: {query}</h1>{body}</body></html>"


def resolve_canonical_url(url: str, timeout: int = 8, proxies: Optional[dict] = None) -> str:
    """
    Follow redirects to find the canonical URL of a page.
    Uses a lightweight HEAD request.
    Returns the original URL unchanged if resolution fails.
    """
    try:
        resp = requests.head(
            url, 
            timeout=timeout, 
            allow_redirects=True, 
            proxies=proxies,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/133.0.0.0 Safari/537.36",
            }
        )
        final_url = resp.url
        if final_url and final_url != url:
            parsed_orig = urlparse(url)
            parsed_final = urlparse(final_url)
            if parsed_orig.netloc != parsed_final.netloc:
                logger.info(f"🔀 URL canonicalized: {url} → {final_url}")
                return final_url
    except Exception:
        pass
    return url


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
        # MAP MODE  (Firecrawl-style: robots.txt → sitemap → homepage)
        # No browser — pure HTTP requests, returns full site URL list
        # =========================================================
        if crawl_mode == "links":
            logger.info("🗺️  Map mode — sitemap-based URL discovery (no browser)")

            p_dict = self.page_crawler.proxy_manager.get_requests_proxies(
                self._initial_proxy_type()
            )
            
            logger.info(f"  → Attempting map discovery with {self._initial_proxy_type()} proxy...")
            map_result = map_website(start_url, proxy_dict=p_dict)

            # Fallback to enhanced proxy if discovery failed
            if (
                map_result["total"] <= 1
                and self._effective_proxy_mode() == "auto"
            ):
                logger.info("Auto mode escalation: retrying map discovery with enhanced proxy.")
                p_dict_enhanced = self.page_crawler.proxy_manager.get_requests_proxies("enhanced")
                if p_dict_enhanced:
                    map_result = map_website(start_url, proxy_dict=p_dict_enhanced)

            elapsed = perf_counter() - start_perf

            discovered_urls = map_result["urls"]

            # Persist to links.txt (same path the rest of the system uses)
            if enable_links:
                with open(self.config.links_file, "w", encoding="utf-8") as f:
                    f.write("\n".join(discovered_urls))

            summary = {
                "start_url": start_url,
                "pages_crawled": 0,
                "pages_failed": 0,
                "total_links_found": map_result["total"],
                "capped": map_result["capped"],
                "from_sitemap": map_result["from_sitemap"],
                "from_homepage": map_result["from_homepage"],
                "sitemaps_used": map_result["sitemaps_used"],
                "started_at": start_time.strftime("%Y-%m-%d %H:%M:%S %Z"),
                "time_taken": f"{int(elapsed//60)}m {int(elapsed%60)}s",
                "crawl_mode": crawl_mode,
                "markdown_file": "None",
                "links_file_path": str(self.config.links_file),
                "summary_file_path": str(self.config.summary_file),
            }

            with open(self.config.summary_file, "w", encoding="utf-8") as f:
                json.dump(summary, f, indent=2)

            logger.info("✅ Map crawl finished")
            logger.info(json.dumps(summary, indent=2))
            return summary

        # =========================================================
        # SEARCH MODE (Firecrawl-style: route search URLs via API)
        # No browser — uses DuckDuckGo/SearXNG, returns structured results
        # =========================================================
        if _is_search_url(start_url):
            query = _extract_search_query(start_url)
            logger.info(f"🔍 Search URL detected. Routing query '{query}' through search engine router...")
            
            search_results = execute_search_router(query, limit=10)
            elapsed = perf_counter() - start_perf
            
            if search_results:
                successful_pages = 1
                md_content = _format_search_results_markdown(query, search_results)
                html_content = _format_search_results_html(query, search_results)
                result_links = [r.get("url") for r in search_results if r.get("url")]
                
                md_path = None
                html_path = None
                screenshot_path = None
                
                if enable_md:
                    md_path = self.config.md_dir / f"search_{query[:50].replace(' ', '_')}.md"
                    md_path.parent.mkdir(parents=True, exist_ok=True)
                    with open(md_path, "w", encoding="utf-8") as f:
                        f.write(md_content)
                    logger.info(f"📄 Search markdown saved: {md_path}")
                
                if enable_html:
                    html_path = self.config.html_dir / f"search_{query[:50].replace(' ', '_')}.html"
                    html_path.parent.mkdir(parents=True, exist_ok=True)
                    with open(html_path, "w", encoding="utf-8") as f:
                        f.write(html_content)
                
                if enable_links:
                    with open(self.config.links_file, "w", encoding="utf-8") as f:
                        f.write("\n".join(result_links))
                
                # Screenshot: render the HTML in a headless browser
                if enable_ss:
                    try:
                        from playwright.sync_api import sync_playwright
                        screenshot_path = self.config.screenshot_dir / f"search_{query[:50].replace(' ', '_')}.png"
                        screenshot_path.parent.mkdir(parents=True, exist_ok=True)
                        with sync_playwright() as p:
                            browser = p.chromium.launch(headless=True)
                            page = browser.new_page(viewport={"width": 1280, "height": 800})
                            page.set_content(html_content)
                            page.wait_for_timeout(500)
                            page.screenshot(path=str(screenshot_path), full_page=True)
                            browser.close()
                        logger.info(f"📸 Search screenshot saved: {screenshot_path}")
                    except Exception as e:
                        logger.warning(f"Screenshot generation failed: {e}")
                
                # SEO report from search results
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
                
                result = {
                    "url": start_url,
                    "canonical": start_url,
                    "markdown_file": str(md_path) if md_path else None,
                    "html_file": str(html_path) if html_path else None,
                    "screenshot": str(screenshot_path) if screenshot_path else None,
                    "links": result_links,
                    "status_code": 200,
                }
            else:
                logger.warning(f"Search engine router returned no results for: {query}")
                result = {"url": start_url, "error": "No search results", "status_code": 404}
            
            summary = {
                "start_url": start_url,
                "pages_crawled": successful_pages,
                "pages_failed": 1 - successful_pages,
                "total_links_found": len(result.get("links", [])) if successful_pages else 0,
                "started_at": start_time.strftime("%Y-%m-%d %H:%M:%S %Z"),
                "time_taken": f"{int(elapsed//60)}m {int(elapsed%60)}s",
                "crawl_mode": "search",
                "search_query": query,
                "markdown_file": result.get("markdown_file", "None"),
                "links_file_path": str(self.config.links_file),
                "summary_file_path": str(self.config.summary_file),
            }
            
            with open(self.config.summary_file, "w", encoding="utf-8") as f:
                json.dump(summary, f, indent=2)
            
            logger.info("✅ Search crawl finished")
            logger.info(json.dumps(summary, indent=2))
            return summary

        # =========================================================
        # SINGLE PAGE MODE (NO THREADING)
        # =========================================================
        if crawl_mode == "single":
            logger.info("🔹 Single-page crawl mode")

            p_dict = self.page_crawler.proxy_manager.get_requests_proxies(
                self._initial_proxy_type()
            )
            # Auto-resolve canonical URL (follows redirects: naukri.com → www.naukri.com)
            canonical_url = resolve_canonical_url(start_url, proxies=p_dict)

            result = self.page_crawler.crawl_page(
                canonical_url,
                count=1,
                enable_md=enable_md,
                enable_html=enable_html,
                enable_ss=enable_ss,
                enable_seo=enable_seo,
                enable_images=enable_images,
                client_id=client_id,
                websocket_manager=websocket_manager,
                crawl_mode=crawl_mode,
                proxy_type=self._effective_proxy_mode()
            )

            if result and "error" not in result:
                successful_pages = 1

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
            
            summary = {
                "start_url": start_url,
                "pages_crawled": successful_pages,
                "pages_failed": 1 - successful_pages,
                "total_links_found": len(result.get("links", [])) if (result and "error" not in result) else 0,
                "started_at": start_time.strftime("%Y-%m-%d %H:%M:%S %Z"),
                "time_taken": f"{int(elapsed//60)}m {int(elapsed%60)}s",
                "crawl_mode": crawl_mode,
                "markdown_file": result.get("markdown_file", None) if (result and "error" not in result) else None,
                "html_file": result.get("html_file", None) if (result and "error" not in result) else None,
                "screenshot": result.get("screenshot", None) if (result and "error" not in result) else None,
                "seo_md": result.get("seo_md", None) if (result and "error" not in result) else None,
                "seo_xlsx": result.get("seo_xlsx", None) if (result and "error" not in result) else None,
                "seo_json": result.get("seo_json", None) if (result and "error" not in result) else None,
                "images_path": result.get("images", None) if (result and "error" not in result) else None,
                "links_file_path": str(self.config.links_file),
                "summary_file_path": str(self.config.summary_file),
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
                # Initial attempt
                proxy_type = self._effective_proxy_mode()
                result = self.page_crawler.crawl_page(
                    url,
                    page_no,
                    enable_md,
                    enable_html,
                    enable_ss,
                    enable_seo,
                    enable_images,
                    client_id,
                    websocket_manager,
                    crawl_mode=crawl_mode,
                    proxy_type=proxy_type
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

                            def normalize_host(h):
                                h = h.lower()
                                return h[4:] if h.startswith("www.") else h

                            if normalize_host(urlparse(link).netloc) == normalize_host(urlparse(start_url).netloc):
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
            "links_file_path": str(self.config.links_file),
            "summary_file_path": str(self.config.summary_file),
        }

        with open(self.config.summary_file, "w", encoding="utf-8") as f:
            json.dump(summary, f, indent=2)

        logger.info("✅ Crawl finished")
        logger.info(json.dumps(summary, indent=2))
        return summary
