"""
Fetchers package - provides regular and stealthy web fetchers.
"""
from .response import Response
from .clock_browser import DynamicFetcher, AsyncDynamicFetcher
from .stealth_clock_browser import StealthyFetcher
from .stealth_clock_browser2 import AsyncStealthyFetcher, PersistentStealthyFetcher
__all__ = [
    "Response",
    "DynamicFetcher",
    "AsyncDynamicFetcher",
    "StealthyFetcher",
    "AsyncStealthyFetcher",
    "PersistentStealthyFetcher"
]