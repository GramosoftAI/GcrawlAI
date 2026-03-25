"""
Google Search Scraper - Takes a search query, fetches results using headless Chromium,
and returns structured JSON output.

Usage:
    python google_search.py "turf in iyyapanthagnal"
    python google_search.py "best restaurants near me" --stealth
    python google_search.py "python tutorials" --output results.json
"""
import sys
import json
import argparse
import urllib.parse
from typing import Dict, Any, List, Optional
from .retriever import DynamicFetcher, StealthyFetcher


def build_google_search_url(query: str) -> str:
    """Build Google search URL from query."""
    base_url = "https://www.google.com/search"
    params = urllib.parse.urlencode({"q": query})
    return f"{base_url}?{params}"


def extract_search_results(response) -> Dict[str, Any]:
    """
    Extract structured search results from Google SERP.
    Returns organized data in dict format.
    """
    results = {
        "query": "",
        "status": response.status,
        "results": [],
    }

    # Target Google's organic search result containers
    # Multiple selectors to catch different SERP layouts
    selectors = [
        "div[data-ved]",      # Classic organic results
        "div[data-hve]",      # Alternative result marker
        "div.g",              # Legacy .g class for results
        "div[data-test-id]",  # Modern test IDs
        "div[jsname]",        # JS-powered result containers
    ]

    result_containers = []
    for selector in selectors:
        found = response.select(selector)
        if found:
            result_containers.extend(found)

    for container in result_containers:
        # Look for the main link within the result container
        link = container.select_one("a[href]")
        if not link:
            continue

        href = link.get("href")

        # Filter valid search result links
        if not href or not href.startswith("http"):
            continue
        if "google." in href or "/search?" in href or "/url?" in href:
            continue

        # Extract title from h3 tag (Google's title container)
        title_tag = container.select_one("h3")
        title = title_tag.get_text(strip=True) if title_tag else link.get_text(strip=True)

        # Clean title - remove URL artifacts that may be scraped
        if "›" in title:
            title = title.split("›")[0].strip()
        if "http" in title:
            title = title.split("http")[0].strip()

        if len(title) < 3:
            continue

        # Extract snippet from the result container
        snippet = ""
        # Google snippets are typically in divs with specific classes or data attributes
        # Try to find snippet text (exclude title, URLs, and nav text)
        for div in container.find_all(["div", "span"]):
            text = div.get_text(strip=True)
            if text and len(text) > 10:
                # Skip title duplicates, URL-like text, and navigation artifacts
                if text != title and "http" not in text and "›" not in text:
                    snippet = text
                    break

        results["results"].append({
            "title": title,
            "url": href,
            "snippet": snippet,
        })

    # Deduplicate results by URL
    seen = set()
    unique_results = []
    for r in results["results"]:
        if r["url"] not in seen:
            seen.add(r["url"])
            unique_results.append(r)

    results["results"] = unique_results  # Return all found results, limit handled by caller

    return results


def search(
    query: str,
    use_stealth: bool = True,
    headless: bool = False,
    output_file: str = None,
) -> Dict[str, Any]:
    """
    Perform Google search and return results as JSON-serializable dict.

    Args:
        query: Search query (e.g., "turf in iyyapanthagnal")
        use_stealth: Use StealthyFetcher to bypass bot detection
        headless: Run browser in headless mode
        output_file: Optional file path to save JSON output

    Returns:
        Dictionary with search results
    """
    # Build the search URL
    url = build_google_search_url(query)
    print(f"Searching: {query}")
    print(f"URL: {url}")

    # Choose fetcher
    fetcher_class = StealthyFetcher if use_stealth else DynamicFetcher
    fetcher = fetcher_class(
        headless=headless,
        block_resources=True,  # Speed up by blocking images/fonts
        solve_cloudflare=use_stealth,
    )

    # Fetch the page
    print("Fetching with headless Chromium...")
    response = fetcher.fetch(url)

    if not response.ok:
        return {
            "error": response.error or f"Request failed with status {response.status}",
            "query": query,
            "url": url,
        }

    print(f"Success! Status: {response.status}")

    # Extract structured results
    results = extract_search_results(response)
    results["query"] = query
    results["final_url"] = response.url
    results["status"] = response.status

    # Save to file if specified
    if output_file:
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2, ensure_ascii=False)
        print(f"Results saved to: {output_file}")

    return results


def scrape_google(
    query: str,
    limit: int = 10,
    ip: Optional[str] = None,
    headless: bool = True,
    fast_mode: bool = True,
) -> List[Dict[str, str]]:
    """
    Scrape Google search results - compatibility function for search_engine.py router.
    Implements pagination to fetch multiple pages when limit > 10.

    Args:
        query: Search query
        limit: Number of results to return
        ip: Client IP for locale detection (unused currently, kept for API compatibility)
        headless: Run browser in headless mode
        fast_mode: Use stealth mode with Cloudflare solving enabled

    Returns:
        List of search results with url, title, description
    """
    all_results = []
    start = 0
    num_per_page = 10

    # Calculate how many pages we need to fetch
    # Google typically shows 10 organic results per page
    while len(all_results) < limit:
        # Build the search URL with pagination (start parameter)
        base_url = "https://www.google.com/search"
        params = {"q": query, "num": 10}
        if start > 0:
            params["start"] = start
        url = f"{base_url}?{urllib.parse.urlencode(params)}"

        # Use stealth fetcher for Cloudflare bypass
        fetcher = StealthyFetcher(
            headless=headless,
            block_resources=True,
            solve_cloudflare=fast_mode,
        )

        try:
            response = fetcher.fetch(url)

            if not response.ok:
                break

            # Extract structured results
            raw_results = extract_search_results(response)

            # Format to match search engine interface
            for r in raw_results.get("results", []):
                formatted = {
                    "url": r.get("url"),
                    "title": r.get("title"),
                    "description": r.get("snippet"),
                }
                # Avoid duplicates
                if not any(f["url"] == formatted["url"] for f in all_results):
                    all_results.append(formatted)

            # Check if we got no results on this page (no more pages available)
            if len(raw_results.get("results", [])) == 0:
                break

        except Exception as e:
            break

        # Move to next page
        start += num_per_page

    return all_results[:limit]


def main():
    parser = argparse.ArgumentParser(
        description="Google Search Scraper - Returns results as JSON"
    )
    parser.add_argument(
        "query",
        type=str,
        help="Search query (e.g., 'turf in iyyapanthagnal')"
    )
    parser.add_argument(
        "--no-stealth",
        action="store_true",
        help="Use regular fetcher instead of stealthy (faster but detectable)"
    )
    parser.add_argument(
        "--headful",
        action="store_true",
        help="Show browser window (debug mode)"
    )
    parser.add_argument(
        "--output", "-o",
        type=str,
        help="Save JSON output to file"
    )
    parser.add_argument(
        "--quiet", "-q",
        action="store_true",
        help="Only output JSON (no progress messages)"
    )

    args = parser.parse_args()

    results = search(
        query=args.query,
        use_stealth=not args.no_stealth,
        headless=not args.headful,
        output_file=args.output,
    )

    # Print JSON output
    if not args.quiet:
        print("\n=== Search Results (JSON) ===\n")

    print(json.dumps(results, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
