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
from dotenv import load_dotenv

from web_crawler.search.retriever import PersistentStealthyFetcher

load_dotenv()
logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Tunable constants
# ─────────────────────────────────────────────────────────────────────────────
_CACHING_ENABLED = os.getenv("GOOGLE_SEARCH_DISABLE_CACHE", "false").lower() != "true"
_CACHE_TTL_SECONDS: float = 120.0
_CACHE_MAX_SIZE: int = 500

# Browser Pool Configuration
_BROWSER_POOL_MIN: int = 50
_BROWSER_POOL_MAX: int = 100
_BROWSER_POOL_TIMEOUT: int = 180

# Concurrency Gates
_MAX_CONCURRENT_GOOGLE_REQUESTS: int = 30
_google_request_semaphore: Optional[asyncio.Semaphore] = None

def _get_semaphore():
    global _google_request_semaphore
    if _google_request_semaphore is None:
        _google_request_semaphore = asyncio.Semaphore(_MAX_CONCURRENT_GOOGLE_REQUESTS)
    return _google_request_semaphore

_PRE_GOTO_JITTER_MIN: float = 0.5
_PRE_GOTO_JITTER_MAX: float = 8.0

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
        self._available = asyncio.Queue()
        self._all_fetchers = []
        self._in_use_count = 0
        self._lock = asyncio.Lock()
        self._initialized = False

    async def initialize(self):
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
        return PersistentStealthyFetcher(
            headless=True,
            block_resources=False,
            wait_until="commit",
            timeout=30_000, # Reduced to 30s for faster failover
            use_random_fingerprint=True
        )

    async def borrow(self) -> PersistentStealthyFetcher:
        if not self._initialized:
            await self.initialize()

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
        async with self._lock:
            for f in self._all_fetchers:
                await f.close()
            self._all_fetchers.clear()
            self._initialized = False

_pool = _BrowserPool(_BROWSER_POOL_MIN, _BROWSER_POOL_MAX, _BROWSER_POOL_TIMEOUT)

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

def _build_proxy_config(session_id_override: Optional[int] = None) -> Dict:
    server = os.getenv("EVOMI_PROXY_SERVER")
    user = os.getenv("EVOMI_PROXY_USERNAME")
    pw = os.getenv("EVOMI_PROXY_PASSWORD")
    
    # ── FIX: Ensure protocol exists ──
    # Playwright requires explicitly stating 'http://' or it will timeout
    if server and "://" not in server:
        server = f"http://{server}"
    
    # Session rotation:
    # Diagnostic test showed that port 1000 on this account does NOT support 
    # the "-session-" suffix (causes 407). 
    # Since we use Context Rotation in stealth_chrome2, Playwright creates a 
    # fresh connection for every search, which naturally rotates the IP 
    # on this rotating endpoint.
    return {
        "server": server,
        "username": user,
        "password": pw
    }

# ─────────────────────────────────────────────────────────────────────────────
# Search Implementation (Async)
# ─────────────────────────────────────────────────────────────────────────────
async def scrape_google(query: str, limit: int = 10, ip: Optional[str] = None, **kwargs) -> List[Dict]:
    """FastAPI-friendly async entry point."""
    try:
        results = await search(query, limit=limit)
        if isinstance(results, dict) and "error" in results:
            return []
        return results.get("results", [])
    except Exception as e:
        logger.error(f"scrape_google failed: {e}")
        return []

async def search(query: str, limit: int = 10) -> Dict:
    tid = random.randint(1000, 9999)
    url = f"https://www.google.com/search?q={query.replace(' ', '+')}&num={max(limit, 14)}"
    cache_key = f"google:{query}:{limit}"
    
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
        # Borrow Browser
        fetcher = await _pool.borrow()
        try:
            # Throttle
            await _apply_provider_throttle("evomi")
            
            # Rotation IP per attempt
            proxy = _build_proxy_config()
            fetcher.proxy = proxy
            
            logger.info(f"[Thread-{tid}] 🌐 [REQUEST] {query} | IP Rotation Active")
            
            response = await fetcher.fetch(url)
            
            if not response.ok:
                logger.error(f"[Thread-{tid}] Google fetch failed: {response.error}")
                return {"error": response.error or "Google blocked request", "query": query}

            # Extraction
            results = extract_search_results(response, limit=limit)
            results["query"] = query
            results["final_url"] = response.url
            results["status"] = response.status
            
            # ── FIX: Prevent Cache Poisoning ──
            # Only cache if we actually found results. Caching an empty result
            # forces subsequent retries to also fail via cache hits.
            if results.get("results"):
                await _cache.put(cache_key, results)
                
            return results
        finally:
            await _pool.return_fetcher(fetcher)

def extract_search_results(response: Any, limit: int) -> Dict:
    """Sync parsing logic with robust multi-selector support."""
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(response.content, 'html.parser')
    results = []
    
    # Google CSS Selectors - trying multiple common patterns
    # Pattern 1: Standard desktop
    search_results = soup.select('div.g, div.MjjYud')
    
    # Pattern 2: Alternative desktop classes
    if not search_results:
        search_results = soup.select('div.tF2Cxc, div.v7W49e')
        
    for g in search_results:
        title = g.select_one('h3')
        # Link usually inside h3's parent, or a tag with data-ved
        link = g.select_one('a[href^="http"]')
        if not link: link = g.select_one('a')
        
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