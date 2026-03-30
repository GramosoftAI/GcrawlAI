import json
import argparse
from typing import Dict, Any
from web_crawler.retriever import DynamicFetcher, StealthyFetcher


def build_google_search_url(query: str, num: int = 10) -> str:
    """Build Google search URL from query."""
    base_url = "https://www.google.com/search"
    import urllib.parse
    params = urllib.parse.urlencode({"q": query, "num": num})
    return f"{base_url}?{params}"



def extract_search_results(response, limit: int = 20) -> Dict[str, Any]:
    """
    Extract structured search results from Google SERP.
    Returns organized data in dict format.
    """
    results = {
        "query": "",
        "status": response.status,
        "results": [],
    }

    # Google's organic results - use broad selector to catch all links
    # Look for anchor tags within the main content area
    for link in response.select("a[href]"):
        href = link.get("href")
        title = link.get_text(strip=True)

        # Filter for actual search results (not Google navigation)
        if href and href.startswith("http") and len(title) > 3:
            # Skip Google's own links
            if "google." in href or "/search?" in href or "/url?" in href:
                continue

            # Find parent container for snippet
            parent = link.find_parent("div")
            snippet = ""
            if parent:
                # Look for snippet text in parent
                for div in parent.find_all(["div", "span"]):
                    text = div.get_text(strip=True)
                    if text and len(text) > 10:
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

    results["results"] = unique_results[:limit]  # Limit to requested number

    return results


def search(
    query: str,
    limit: int = 20,
    use_stealth: bool = True,
    headless: bool = False,
    output_file: str = True,
    proxy_url: str = None,
) -> Dict[str, Any]:
    """
    Perform Google search and return results as JSON-serializable dict.

    Args:
        query: Search query (e.g., "turf in iyyapanthagnal")
        limit: Number of results to fetch
        use_stealth: Use StealthyFetcher to bypass bot detection
        headless: Run browser in headless mode
        output_file: Optional file path to save JSON output
        proxy_url: Optional proxy URL to bypass IP blocking

    Returns:
        Dictionary with search results
    """
    # Request more results than limit to account for deduplication and internal links
    request_num = max(10, limit)
    # Build the search URL
    url = build_google_search_url(query, num=request_num)
    print(f"Searching: {query}")
    print(f"URL: {url}")

    # Choose fetcher
    fetcher_class = StealthyFetcher if use_stealth else DynamicFetcher
    
    # Load environment variables
    import os
    from dotenv import load_dotenv
    load_dotenv()

    # Auto-configure proxy from .env if not provided
    if not proxy_url:
        evomi_server = os.getenv("EVOMI_PROXY_SERVER")
        evomi_user = os.getenv("EVOMI_PROXY_USERNAME")
        evomi_pass = os.getenv("EVOMI_PROXY_PASSWORD")
        if evomi_server and evomi_user and evomi_pass:
            import random
            session_id = random.randint(10000, 999999)
            # Format: http://user:pass@host:port?session=12345
            server_no_scheme = evomi_server.split("://")[-1]
            scheme = evomi_server.split("://")[0] if "://" in evomi_server else "http"
            proxy_url = f"{scheme}://{evomi_user}:{evomi_pass}@{server_no_scheme}?session={session_id}"
            print(f"[*] Using proxy: {proxy_url}")

    proxy_config = None
    if proxy_url:
        import urllib.parse
        parsed = urllib.parse.urlparse(proxy_url)
        if parsed.username and parsed.password:
            # Preserve query string (like ?session=...) in the server URL for Playwright proxy
            server_url = f"{parsed.scheme}://{parsed.hostname}:{parsed.port}"
            if parsed.query:
                server_url += f"?{parsed.query}"
            
            proxy_config = {
                "server": server_url,
                "username": parsed.username,
                "password": parsed.password,
            }
        else:
            proxy_config = {"server": proxy_url}
            
    # Use a modern, randomized User-Agent to prevent headless detection
    import random
    user_agents = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_3_1) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.3.1 Safari/605.1.15",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:124.0) Gecko/20100101 Firefox/124.0"
    ]
    random_ua = random.choice(user_agents)
    
    if proxy_url:
        import requests
        try:
            proxies = {"http": proxy_url, "https": proxy_url}
            ip_test = requests.get("https://api.ipify.org?format=json", proxies=proxies, timeout=10)
            print(f"[*] Proxy Exit IP for this run: {ip_test.json()['ip']}")
        except Exception as e:
            print(f"[*] Could not verify proxy IP: {e}")
            
    fetcher_kwargs = {
        "headless": headless,
        "block_resources": False,  # Speed up by blocking images/fonts
        "proxy": proxy_config,
        "timeout": 60000, # Increased timeout for slow residential proxies
        "user_agent": random_ua,
    }
    if use_stealth:
        fetcher_kwargs["solve_cloudflare"] = True
        
    fetcher = fetcher_class(**fetcher_kwargs)

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
    results = extract_search_results(response, limit=limit)
    results["query"] = query
    results["final_url"] = response.url
    results["status"] = response.status

    # Save to file if specified
    if output_file:
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2, ensure_ascii=False)
        print(f"Results saved to: {output_file}")

    return results


async def scrape_google(query: str, limit: int, ip: str = None, headless: bool = True, fast_mode: bool = True) -> list:
    import asyncio
    import logging
    logger = logging.getLogger(__name__)
    
    loop = asyncio.get_event_loop()
    
    def run_search():
        return search(query=query, limit=limit, use_stealth=not fast_mode, headless=headless, output_file=None)
        
    try:
        # Enforce a 30-second hard deadline so fallback engines can take over
        search_results = await asyncio.wait_for(
            loop.run_in_executor(None, run_search),
            timeout=30.0
        )
    except asyncio.TimeoutError:
        logger.warning("⚠️ [GOOGLE] Hard deadline of 30s exceeded — skipping to fallback.")
        return []
    except Exception as e:
        logger.error(f"❌ [GOOGLE] Search failed: {e}")
        return []
    
    formatted = []
    if "results" in search_results:
        for r in search_results["results"][:limit]:
            formatted.append({
                "url": r.get("url"),
                "title": r.get("title"),
                "description": r.get("snippet", "")
            })
    return formatted


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
    parser.add_argument(
        "--proxy", "-p",
        type=str,
        help="Proxy URL (e.g., http://user:pass@host:port) to bypass IP blocking"
    )

    args = parser.parse_args()

    results = search(
        query=args.query,
        limit=20, # Default limit for CLI
        use_stealth=not args.no_stealth,
        headless=not args.headful,
        output_file=args.output,
        proxy_url=args.proxy,
    )

    # Print JSON output
    if not args.quiet:
        print("\n=== Search Results (JSON) ===\n")

    print(json.dumps(results, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
