"""
Response wrapper class that holds content, headers, status, and URL.
"""
from typing import Optional, Dict


class Response:
    """
    A custom Response object that wraps the scraped page data.
    """

    def __init__(
        self,
        content: str,
        headers: Dict[str, str],
        status: int,
        url: str,
        ok: bool = True,
        error: Optional[str] = None,
        bandwidth_bytes: int = 0,
    ):
        """Init."""
        self.content = content
        self.headers = headers
        self.status = status
        self.url = url
        self.ok = ok
        self.error = error
        self.bandwidth_bytes = bandwidth_bytes

    def __repr__(self) -> str:
        """Repr."""
        return f"Response(status={self.status}, url={self.url}, ok={self.ok})"