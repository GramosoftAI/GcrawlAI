import asyncio
import time
import logging
from typing import Dict, Any, Callable, Union
from pydantic import BaseModel
import concurrent.futures
import functools

logger = logging.getLogger(__name__)

# Priority Mapping (Lower number = Higher Priority)
PLAN_PRIORITIES = {
    "pro": 1,
    "growth": 2,
    "starter": 3,
    "free": 5
}

class QueueItem:
    def __init__(self, priority: int, user_id: Union[int, str], func: Callable, kwargs: dict):
        self.priority = priority
        self.timestamp = time.time()
        self.user_id = user_id
        self.func = func
        self.kwargs = kwargs
        self.future = asyncio.Future()

    def __lt__(self, other):
        # Sort by priority first, then by timestamp (FIFO for same priority)
        if self.priority == other.priority:
            return self.timestamp < other.timestamp
        return self.priority < other.priority

class PriorityQueueManager:
    def __init__(self, global_limit: int = 90):
        self.queue = asyncio.PriorityQueue()
        self.global_limit = global_limit
        self.active_global = 0
        self.user_active_counts: Dict[Union[int, str], int] = {}
        self.user_locks: Dict[Union[int, str], asyncio.Lock] = {}
        self._workers = []
        self._is_running = False
        self.thread_pool = concurrent.futures.ThreadPoolExecutor(max_workers=global_limit)

    def start_workers(self):
        if self._is_running:
            return
        self._is_running = True
        for _ in range(self.global_limit):
            worker = asyncio.create_task(self._worker_loop())
            self._workers.append(worker)
        logger.info(f"🚀 Started {self.global_limit} Global Priority Queue Workers")

    async def stop_workers(self):
        self._is_running = False
        for w in self._workers:
            w.cancel()
        await asyncio.gather(*self._workers, return_exceptions=True)
        self._workers.clear()
        self.thread_pool.shutdown(wait=False)

    def get_user_lock(self, user_id: Union[int, str]) -> asyncio.Lock:
        if user_id not in self.user_locks:
            self.user_locks[user_id] = asyncio.Lock()
        return self.user_locks[user_id]

    async def submit_task(self, user_id: Union[int, str], plan_type: str, user_limit: int, func: Callable, **kwargs):
        """
        Submits a task to the queue and waits for its execution.
        Respects both the User Concurrency Limit and the Global Priority Queue.
        """
        priority = PLAN_PRIORITIES.get(plan_type.lower(), 5)
        
        # 1. Enforce User Concurrency Limit
        lock = self.get_user_lock(user_id)
        while True:
            async with lock:
                current_active = self.user_active_counts.get(user_id, 0)
                if current_active < user_limit:
                    self.user_active_counts[user_id] = current_active + 1
                    break
            # If user has reached their limit, they wait here (queued) until one of their tasks finishes.
            await asyncio.sleep(0.5)

        # 2. Add to Global Priority Queue
        item = QueueItem(priority, user_id, func, kwargs)
        await self.queue.put(item)
        logger.info(f"📥 Queued task for User {user_id} (Plan: {plan_type}, Priority: {priority})")

        try:
            # 3. Wait for execution to complete
            result = await item.future
            return result
        finally:
            # 4. Decrement user active count
            async with lock:
                self.user_active_counts[user_id] -= 1
                if self.user_active_counts[user_id] <= 0:
                    self.user_active_counts.pop(user_id, None)

    async def submit_background_task(self, user_id: Union[int, str], plan_type: str, user_limit: int, func: Callable, **kwargs):
        """
        Submits a task to the queue and returns immediately.
        The worker will enforce limits and execute it in the background.
        """
        priority = PLAN_PRIORITIES.get(plan_type.lower(), 5)
        
        # Create a wrapper function that will enforce limits BEFORE execution inside the worker
        async def _background_wrapper():
            lock = self.get_user_lock(user_id)
            while True:
                async with lock:
                    current_active = self.user_active_counts.get(user_id, 0)
                    if current_active < user_limit:
                        self.user_active_counts[user_id] = current_active + 1
                        break
                await asyncio.sleep(0.5)
            
            try:
                if asyncio.iscoroutinefunction(func):
                    return await func(**kwargs)
                else:
                    loop = asyncio.get_running_loop()
                    return await loop.run_in_executor(self.thread_pool, functools.partial(func, **kwargs))
            finally:
                async with lock:
                    self.user_active_counts[user_id] -= 1
                    if self.user_active_counts[user_id] <= 0:
                        self.user_active_counts.pop(user_id, None)

        item = QueueItem(priority, user_id, _background_wrapper, {})
        await self.queue.put(item)
        logger.info(f"📥 Queued BACKGROUND task for User {user_id} (Plan: {plan_type}, Priority: {priority})")

    async def _worker_loop(self):
        """Worker that pulls from the priority queue and executes."""
        while self._is_running:
            try:
                item: QueueItem = await self.queue.get()
                self.active_global += 1
                
                logger.info(f"▶️ Executing task for User {item.user_id} (Priority {item.priority})")
                
                try:
                    # Execute the actual crawling/search function
                    if asyncio.iscoroutinefunction(item.func):
                        result = await item.func(**item.kwargs)
                    else:
                        loop = asyncio.get_running_loop()
                        result = await loop.run_in_executor(self.thread_pool, functools.partial(item.func, **item.kwargs))
                    
                    if not item.future.done():
                        item.future.set_result(result)
                except Exception as e:
                    logger.error(f"❌ Task failed for User {item.user_id}: {e}", exc_info=True)
                    if not item.future.done():
                        item.future.set_exception(e)
                finally:
                    self.active_global -= 1
                    self.queue.task_done()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Worker loop error: {e}")
                await asyncio.sleep(1)

import os
GLOBAL_BROWSER_POOL = int(os.getenv("GLOBAL_BROWSER_POOL", 100))
queue_manager = PriorityQueueManager(global_limit=GLOBAL_BROWSER_POOL)
