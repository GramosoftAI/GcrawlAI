from urllib.parse import urlparse, parse_qs

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
    lines = [f"# Search Results: {query}\\n"]
    for i, r in enumerate(results, 1):
        title = r.get("title", "Untitled")
        url = r.get("url", "")
        desc = r.get("description", "")
        lines.append(f"## {i}. [{title}]({url})\\n")
        if desc:
            lines.append(f"{desc}\\n")
        lines.append("")
    return "\\n".join(lines)


def _format_search_results_html(query: str, results: list) -> str:
    """Format search results as HTML."""
    items = []
    for r in results:
        title = r.get("title", "Untitled")
        url = r.get("url", "")
        desc = r.get("description", "")
        items.append(f'<div class="result"><h3><a href="{url}">{title}</a></h3><p>{desc}</p></div>')
    body = "\\n".join(items)
    return f"<html><head><title>Search: {query}</title></head><body><h1>Search Results: {query}</h1>{body}</body></html>"
