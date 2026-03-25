"""
Response wrapper class that holds content, headers, status, and provides selector methods.
"""
from typing import Optional, Dict, Any
from bs4 import BeautifulSoup


class Response:
    """
    A custom Response object that wraps the scraped page data.
    Provides convenient methods to extract content using CSS selectors.
    """

    def __init__(
        self,
        content: str,
        headers: Dict[str, str],
        status: int,
        url: str,
        ok: bool = True,
        error: Optional[str] = None,
    ):
        self.content = content
        self.headers = headers
        self.status = status
        self.url = url
        self.ok = ok
        self.error = error
        self._soup: Optional[BeautifulSoup] = None

    @property
    def soup(self) -> BeautifulSoup:
        """Lazy-load the BeautifulSoup parser."""
        if self._soup is None:
            self._soup = BeautifulSoup(self.content, "html.parser")
        return self._soup

    def select(self, css_selector: str) -> list:
        """
        Select elements using CSS selector.
        Returns a list of matching elements.
        """
        return self.soup.select(css_selector)

    def select_one(self, css_selector: str) -> Optional[Any]:
        """
        Select a single element using CSS selector.
        Returns the first matching element or None.
        """
        return self.soup.select_one(css_selector)

    def text(self, css_selector: Optional[str] = None) -> str:
        """
        Get text content. If selector provided, gets text of that element.
        """
        if css_selector:
            el = self.select_one(css_selector)
            return el.get_text(strip=True) if el else ""
        return self.soup.get_text(strip=True)

    def get_header(self, name: str) -> Optional[str]:
        """Get a specific header value (case-insensitive)."""
        name_lower = name.lower()
        for k, v in self.headers.items():
            if k.lower() == name_lower:
                return v
        return None

    def json(self) -> Optional[Dict]:
        """Try to parse content as JSON."""
        import json
        try:
            return json.loads(self.content)
        except (json.JSONDecodeError, TypeError):
            return None

    def __repr__(self) -> str:
        return f"Response(status={self.status}, url={self.url}, ok={self.ok})"
