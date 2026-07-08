"""
google_search.py — Fully Async Evomi-only Google search scraper.

This version is optimized for high-concurrency (FastAPI) and uses Async Playwright
to avoid thread-switching errors and handle 500+ concurrent requests.

STRATEGY:
  1. Persistent Stealth Browser Binary Pool (Async)
  2. Context Rotation per request (Clean Session + IP Rotation)
  3. Async Semaphores & Locks for non-blocking throttling
"""

import json
import asyncio
import random
import time
import os
import logging
from typing import Dict, Any, Optional, Tuple, List
from collections import OrderedDict
from pathlib import Path
from dotenv import load_dotenv
from web_crawler.search.retriever import PersistentStealthyFetcher
from web_crawler.common.proxy_manager import ProxyManager

_pm = ProxyManager()

BASE_DIR = Path(__file__).resolve().parent.parent.parent
dotenv_path = BASE_DIR / '.env'
load_dotenv(dotenv_path)
logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Tunable constants
# ─────────────────────────────────────────────────────────────────────────────
_CACHING_ENABLED = os.getenv("GOOGLE_SEARCH_DISABLE_CACHE", "false").lower() != "true"
_CACHE_TTL_SECONDS: float = 120.0
_CACHE_MAX_SIZE: int = 500

GLOBAL_BROWSER_POOL = int(os.getenv("GLOBAL_BROWSER_POOL", 100))
# Browser Pool Configuration
_BROWSER_POOL_MIN: int = GLOBAL_BROWSER_POOL
_BROWSER_POOL_MAX: int = GLOBAL_BROWSER_POOL
_BROWSER_POOL_TIMEOUT: int = 180

# Concurrency Gates
_MAX_CONCURRENT_GOOGLE_REQUESTS: int = 30
_google_request_semaphore: Optional[asyncio.Semaphore] = None

def _get_semaphore():
    global _google_request_semaphore
    if _google_request_semaphore is None:
        _google_request_semaphore = asyncio.Semaphore(_MAX_CONCURRENT_GOOGLE_REQUESTS)
    return _google_request_semaphore

_PRE_GOTO_JITTER_MIN: float = 0.05
_PRE_GOTO_JITTER_MAX: float = 0.15

_ADAPTIVE_THROTTLE_SECONDS: float = 3.0
_THROTTLE_INCREASE_ON_429: float = 8.0

# ─────────────────────────────────────────────────────────────────────────────
# Proxy State
# ─────────────────────────────────────────────────────────────────────────────
_active_provider: str = "evomi"
_provider_fail_count: Dict[str, int] = {"evomi": 0}
_provider_fail_lock = asyncio.Lock()
_active_provider_lock = asyncio.Lock()

_request_counter: int = 0
_request_counter_lock = asyncio.Lock()

# ─────────────────────────────────────────────────────────────────────────────
# Result Cache (LRU)
# ─────────────────────────────────────────────────────────────────────────────
class _ResultCache:
    def __init__(self, maxsize: int, ttl: float):
        self.maxsize = maxsize
        self.ttl = ttl
        self.cache: OrderedDict = OrderedDict()
        self.lock = asyncio.Lock()

    async def get(self, key: str) -> Optional[Dict]:
        if not _CACHING_ENABLED: return None
        async with self.lock:
            if key not in self.cache:
                return None
            data, timestamp = self.cache[key]
            if time.time() - timestamp > self.ttl:
                del self.cache[key]
                return None
            self.cache.move_to_end(key)
            return data

    async def put(self, key: str, value: Dict) -> None:
        if not _CACHING_ENABLED: return
        async with self.lock:
            self.cache[key] = (value, time.time())
            self.cache.move_to_end(key)
            if len(self.cache) > self.maxsize:
                self.cache.popitem(last=False)

    async def invalidate_all(self):
        async with self.lock:
            self.cache.clear()

_cache = _ResultCache(_CACHE_MAX_SIZE, _CACHE_TTL_SECONDS)

# ─────────────────────────────────────────────────────────────────────────────
# Browser Pool (Async)
# ─────────────────────────────────────────────────────────────────────────────
class _BrowserPool:
    def __init__(self, minsize: int, maxsize: int, timeout: int = 120):
        self.minsize = minsize
        self.maxsize = maxsize
        self.timeout = timeout
        self._available = None
        self._all_fetchers = []
        self._in_use_count = 0
        self._lock = None
        self._initialized = False

    async def initialize(self):
        if self._lock is None:
            self._lock = asyncio.Lock()
        if self._available is None:
            self._available = asyncio.Queue()
            
        async with self._lock:
            if self._initialized: return
            logger.info(f"[BrowserPool] Pre-creating {self.minsize} browsers...")
            for i in range(self.minsize):
                fetcher = self._create_instance()
                self._all_fetchers.append(fetcher)
                await self._available.put(fetcher)
            self._initialized = True
            logger.info(f"[BrowserPool] Pool ready.")

    def _create_instance(self):
        is_headless = os.getenv("CRAWL_HEADLESS", "true").strip().lower() == "true"
        return PersistentStealthyFetcher(
            headless=is_headless,
            timezone_id="Asia/Kolkata",
            locale="en-US",
            block_resources=True, # Speed optimization: block heavy fonts, images, and CSS
            wait_until="domcontentloaded",
            timeout=15_000, # Increased to 15s for visual browser stability
            use_random_fingerprint=True
        )

    async def borrow(self) -> PersistentStealthyFetcher:
        if not self._initialized:
            await self.initialize()

        # If pool is empty but we can grow, create one immediately instead of waiting for timeout
        async with self._lock:
            if self._available.empty() and len(self._all_fetchers) < self.maxsize:
                logger.info("[BrowserPool] Creating on-demand browser instance.")
                fetcher = self._create_instance()
                self._all_fetchers.append(fetcher)
                self._in_use_count += 1
                return fetcher

        try:
            fetcher = await asyncio.wait_for(self._available.get(), timeout=self.timeout)
            async with self._lock:
                self._in_use_count += 1
            return fetcher
        except asyncio.TimeoutError:
            async with self._lock:
                if len(self._all_fetchers) < self.maxsize:
                    logger.info("[BrowserPool] Creating spike browser instance.")
                    fetcher = self._create_instance()
                    self._all_fetchers.append(fetcher)
                    self._in_use_count += 1
                    return fetcher
            raise TimeoutError("Browser pool exhausted")

    async def return_fetcher(self, fetcher: PersistentStealthyFetcher):
        async with self._lock:
            self._in_use_count -= 1
        await self._available.put(fetcher)

    async def close_all(self):
        if not self._lock: return
        async with self._lock:
            for f in self._all_fetchers:
                await f.close()
            self._all_fetchers.clear()
            self._initialized = False
            self._available = None

# We will initialize this inside the Proactor Thread to bind it to the right loop
_pool = None

# Provider Throttle Settings
_ADAPTIVE_THROTTLE_SECONDS: float = 1.0  # Reduced for high concurrency
_provider_last_req: Dict[str, float] = {"evomi": 0}

async def _apply_provider_throttle(provider: str):
    """
    Lightweight throttle. We don't use a lock here anymore because
    with 500+ unique IPs via session IDs, we want maximum parallelism.
    """
    last = _provider_last_req.get(provider, 0)
    elapsed = time.time() - last
    if elapsed < _ADAPTIVE_THROTTLE_SECONDS:
        # We still sleep a tiny bit to prevent CPU spikes, but don't block others
        await asyncio.sleep(0.1)
    _provider_last_req[provider] = time.time()

def _build_proxy_config(session_id: Optional[str] = None, proxy_geo: Optional[str] = None) -> Dict:
    if proxy_geo and proxy_geo.strip().lower() != "default":
        return _pm.get_playwright_proxy(
            target_url="https://www.google.com",
            provider="nodemaven",
            session_id=session_id,
            use_high_speed=True,
            proxy_geo=proxy_geo,
            is_search=True
        )

    # Switched to Nodemaven residential proxy for higher IP quality and fewer CAPTCHAs
    host = os.getenv("NODEMAVEN_HOST", os.getenv("ATTEMPT_1_PROXY_HOST", "gate.nodemaven.com"))
    port = os.getenv("NODEMAVEN_PORT", os.getenv("ATTEMPT_1_PROXY_PORT", "8080"))
    server = f"http://{host}:{port}"
    
    base_user = os.getenv("NODEMAVEN_BASE_USER")
    if not base_user:
        tier1_user = os.getenv("ATTEMPT_1_PROXY_USER", "")
        if "-" in tier1_user:
            base_user = tier1_user.split("-")[0]
        else:
            base_user = tier1_user or "rajeshm_gramosoft_in"
            
    user = f"{base_user}-country-IN-filter-medium-speed-fast"
    pw = os.getenv("NODEMAVEN_PASS", os.getenv("ATTEMPT_1_PROXY_PASS", "smavzmzry1"))
    
    if session_id:
        user = f"{user}-session-{session_id}"
            
    return {
        "server": server,
        "username": user,
        "password": pw
    }

# ─────────────────────────────────────────────────────────────────────────────
# Persistent Proactor Thread (Windows Fix)
# ─────────────────────────────────────────────────────────────────────────────
_proactor_loop = None
_proactor_thread = None

def _get_or_start_proactor_thread():
    global _proactor_loop, _proactor_thread
    if _proactor_thread is not None and _proactor_thread.is_alive():
        return _proactor_loop

    import threading
    import asyncio
    
    def run_loop():
        global _proactor_loop, _pool
        try:
            if hasattr(asyncio, 'WindowsProactorEventLoopPolicy'):
                asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
        except Exception:
            pass
            
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        _proactor_loop = loop
        
        # Initialize pool correctly inside the Proactor Loop
        GLOBAL_BROWSER_POOL = int(os.getenv("GLOBAL_BROWSER_POOL", 100))
        _BROWSER_POOL_MIN = GLOBAL_BROWSER_POOL
        _BROWSER_POOL_MAX = GLOBAL_BROWSER_POOL
        _pool = _BrowserPool(_BROWSER_POOL_MIN, _BROWSER_POOL_MAX, _BROWSER_POOL_TIMEOUT)
        
        # Pre-warm browsers in background
        loop.create_task(_pool.initialize())
        
        try:
            loop.run_forever()
        finally:
            loop.close()

    _proactor_thread = threading.Thread(target=run_loop, daemon=True)
    _proactor_thread.start()
    
    while _proactor_loop is None:
        time.sleep(0.05)
        
    return _proactor_loop

async def scrape_google(query: str, limit: int = 10, ip: Optional[str] = None, **kwargs) -> List[Dict]:
    """FastAPI-friendly async entry point."""
    import sys
    import asyncio
    import concurrent.futures
    
    proxy_geo = kwargs.get("proxy_geo")
    
    if sys.platform == 'win32':
        try:
            loop = asyncio.get_running_loop()
            is_selector = "SelectorEventLoop" in type(loop).__name__
        except Exception:
            is_selector = True
            
        if is_selector:
            # We are on Windows and stuck in SelectorEventLoop.
            # Submit to the persistent Proactor loop!
            target_loop = _get_or_start_proactor_thread()
            
            future = asyncio.run_coroutine_threadsafe(search(query, limit, proxy_geo=proxy_geo), target_loop)
            try:
                # Wrap the concurrent.futures.Future in an asyncio Future to await it non-blocking
                results = await asyncio.wrap_future(future)
                if isinstance(results, dict) and "error" in results:
                    return []
                return results.get("results", [])
            except Exception as e:
                logger.error(f"Windows persistent thread search failed: {e}")
                return []
                
    try:
        results = await search(query, limit=limit, proxy_geo=proxy_geo)
        if isinstance(results, dict) and "error" in results:
            return []
        return results.get("results", [])
    except Exception as e:
        logger.error(f"scrape_google failed: {e}")
        return []

async def search(query: str, limit: int = 10, proxy_geo: Optional[str] = None) -> Dict:
    global _pool
    if _pool is None:
        # Lazy initialization for non-SelectorEventLoop or CLI execution
        GLOBAL_BROWSER_POOL = int(os.getenv("GLOBAL_BROWSER_POOL", 5))
        _pool = _BrowserPool(GLOBAL_BROWSER_POOL, GLOBAL_BROWSER_POOL, 5)

    tid = random.randint(1000, 9999)
    cache_key = f"google:{query}:{limit}:{proxy_geo or ''}"
    
    # 1. Cache hit?
    cached = await _cache.get(cache_key)
    if cached:
        logger.info(f"[Thread-{tid}] Cache hit for {query}")
        return cached

    # 2. Parallel Jitter
    jitter = random.uniform(_PRE_GOTO_JITTER_MIN, _PRE_GOTO_JITTER_MAX)
    await asyncio.sleep(jitter)

    # 3. Semaphore Gate
    sem = _get_semaphore()
    async with sem:
        # Dynamically calculate the page offsets to query in parallel with redundancy.
        # Google search returns 10 results per page.
        target_pages = (limit + 9) // 10
        # If target_pages is already covering the limit with room to spare (>= 3 spare results),
        # we don't need additional redundancy pages. Otherwise, we add 1 redundancy page.
        if target_pages * 10 - limit >= 3:
            redundancy = 0
        else:
            redundancy = 1
        num_pages = max(target_pages + redundancy, 2)  # Always query at least 2 pages for fallback/redundancy
        num_pages = min(num_pages, 10)  # Protect local system resources
        starts = [i * 10 for i in range(num_pages)]
            
        logger.info(f"[Thread-{tid}] Fetching Google starts: {starts} in parallel for limit={limit} using proxy_geo={proxy_geo}")
        
        # Throttle
        await _apply_provider_throttle("evomi")
        
        async def fetch_page(start: int):
            fetcher = await _pool.borrow()
            try:
                url = f"https://www.google.com/search?q={query.replace(' ', '+')}&start={start}&filter=0"
                session_id = "".join(random.choices("0123456789abcdef", k=8))
                fetcher.proxy = _build_proxy_config(session_id=session_id, proxy_geo=proxy_geo)
                try:
                    response = await fetcher.fetch(url)
                    if not response.ok:
                        logger.error(f"[Thread-{tid}] Page start={start} fetch failed: {response.error}")
                        return [], response
                    extracted = extract_search_results(response, limit=15)
                    return extracted.get("results", []), response
                except Exception as e:
                    logger.error(f"[Thread-{tid}] Page start={start} exception: {e}")
                    return [], None
            finally:
                await _pool.return_fetcher(fetcher)

        async def fetch_page_with_retry(start: int):
            page_results = []
            page_response = None
            for attempt in range(3):  # Try up to 3 times to get this specific page
                res_list, resp = await fetch_page(start)
                if resp:
                    page_response = resp
                    if resp.ok:
                        page_results = res_list
                        break
                logger.warning(f"[Thread-{tid}] Page start={start} attempt {attempt+1} failed. Retrying page...")
                await asyncio.sleep(1.0)
            return page_results, page_response

        # Execute parallel fetches
        async_tasks = {start: asyncio.create_task(fetch_page_with_retry(start)) for start in starts}
        
        combined = []
        seen_urls = set()
        valid_response = None
        
        # Process tasks in sorted start order to maintain correct Google ranking.
        for start in sorted(starts):
            try:
                page_results, page_response = await async_tasks[start]
                if page_response:
                    valid_response = page_response
                
                # Log if a page failed completely but continue to show other pages' results
                if not page_response or not page_response.ok:
                    logger.warning(f"[Thread-{tid}] Page start={start} failed completely after retries.")
                    continue
                    
                for r in page_results:
                    url = r.get("url")
                    if not url or url in seen_urls:
                        continue
                    seen_urls.add(url)
                    combined.append(r)
            except Exception as e:
                logger.error(f"[Thread-{tid}] Error processing task for start={start}: {e}")

        # Dynamic subsequent page fetching fallback if we have fewer results than the limit
        next_start = (max(starts) + 10) if starts else 10
        max_start = 90  # limit to page 10 (start=90)
        while len(combined) < limit and next_start <= max_start:
            logger.info(f"[Thread-{tid}] Results so far: {len(combined)}/{limit}. Fetching next page start={next_start} sequentially...")
            try:
                page_results, page_response = await fetch_page_with_retry(next_start)
                if page_response:
                    valid_response = page_response
                if not page_response or not page_response.ok:
                    logger.warning(f"[Thread-{tid}] Subsequent page start={next_start} failed completely after retries. Stopping.")
                    break
                if not page_results:
                    logger.info(f"[Thread-{tid}] Subsequent page start={next_start} returned 0 results. Reached end of search.")
                    break
                new_added = 0
                for r in page_results:
                    url = r.get("url")
                    if not url or url in seen_urls:
                        continue
                    seen_urls.add(url)
                    combined.append(r)
                    new_added += 1
                if new_added == 0 and len(page_results) < 5:
                    logger.info(f"[Thread-{tid}] No new results and page size is small. Stopping.")
                    break
            except Exception as e:
                logger.error(f"[Thread-{tid}] Error fetching subsequent page start={next_start}: {e}")
                break
            next_start += 10
            
        final_results = combined[:limit]
        response = valid_response
        
        results = {
            "results": final_results,
            "count": len(final_results),
            "query": query,
            "final_url": response.url if response else f"https://www.google.com/search?q={query.replace(' ', '+')}",
            "status": response.status if response else 200
        }
        
        if final_results:
            await _cache.put(cache_key, results)
            
        return results

def extract_search_results(response: Any, limit: int) -> Dict:
    """Sync parsing logic with robust multi-selector support."""
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(response.content, 'html.parser')
    results = []
    
    # Google CSS Selectors - prioritize direct result block containers
    search_results = soup.select('div.tF2Cxc')
    
    # Fallback to group containers if direct blocks are not found
    if not search_results:
        search_results = soup.select('div.g, div.MjjYud, div.v7W49e')
        
    for g in search_results:
        title = g.select_one('h3')
        
        # Extract main link: check if h3 is wrapped by a link first to prevent breadcrumb hijacking
        link = title.find_parent('a') if title else None
        if not link:
            link = g.select_one('a[href^="http"]')
        if not link:
            link = g.select_one('a')
        
        # Snippets: VwiC3b/yXK7Bf are new; st is legacy
        snippet = g.select_one('div.VwiC3b, div.yXK7Bf, span.st, div.kb09800, div.MU19Yd')
        
        if title and link and link.get('href'):
            results.append({
                "title": title.get_text(),
                "url": link['href'],
                "description": snippet.get_text() if snippet else ""
            })
            if len(results) >= limit:
                break
                
    return {"results": results, "count": len(results)}

# Lifecycle helpers
async def shutdown():
    await _pool.close_all()
    logger.info("Browser pool shutdown.")