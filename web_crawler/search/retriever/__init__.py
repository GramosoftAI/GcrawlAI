"""
Fetchers package - provides regular and stealthy web fetchers.
"""
from .response import Response
from .stealth_clock_browser2 import PersistentStealthyFetcher
__all__ = [
    "Response",
    "PersistentStealthyFetcher"
]