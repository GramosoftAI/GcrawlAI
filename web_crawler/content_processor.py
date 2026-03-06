"""
Content processing and extraction utilities
"""

from typing import List, Dict
from bs4 import BeautifulSoup
import html2text
from urllib.parse import urlparse, urljoin
from web_crawler.utils import absolutize_url
from web_crawler.cleanup_html import cleanup_html



class ContentProcessor:
    """Process and extract content from pages"""
    
    @staticmethod
    def extract_links(soup: BeautifulSoup, base_url: str) -> List[str]:
        """
        Extract valid internal links from the page.
        Only returns URLs that belong to the same domain (host) as base_url.
        External links (social media, other sites, subdomains) are excluded.
        """
        base_parsed = urlparse(base_url)
        base_host = base_parsed.netloc.lower()  # e.g. "gramosoft.tech"

        seen_paths = set()
        links = []

        for anchor in soup.find_all("a", href=True):
            href = anchor["href"].strip()

            # Skip fragment-only, mailto:, tel:, javascript:, etc.
            if not href or href.startswith(("#", "mailto:", "tel:", "javascript:", "data:")):
                continue

            # Resolve to absolute URL
            url = absolutize_url(href, base_url)
            if not url or not url.startswith("http"):
                continue

            parsed = urlparse(url)
            link_host = parsed.netloc.lower()

            # Only keep links from the EXACT same host (no subdomains)
            if link_host != base_host:
                continue

            # Normalize: strip query string and fragment, normalize trailing slash
            path = parsed.path
            if path != "/" and path.endswith("/"):
                path = path.rstrip("/")  # /about/ → /about

            # Rebuild clean URL: scheme + host + path only
            clean_url = f"{parsed.scheme}://{parsed.netloc}{path}"
            if path == "":
                clean_url = f"{parsed.scheme}://{parsed.netloc}/"

            # Deduplicate by normalized path
            if path in seen_paths:
                continue
            seen_paths.add(path)

            links.append(clean_url)

        return sorted(links)

    
    @staticmethod
    def extract_seo(soup: BeautifulSoup, page_url: str) -> Dict:
        """Extract SEO metadata (sync with seo.py)"""
        def get_meta(name=None, prop=None):
            if name:
                tag = soup.find("meta", attrs={"name": name})
            else:
                tag = soup.find("meta", attrs={"property": prop})
            return tag.get("content").strip() if tag and tag.get("content") else None

        # Link counts
        internal_links = 0
        external_links = 0
        for link in soup.find_all("a", href=True):
            href = link["href"]
            if href.startswith("/"):
                internal_links += 1
            elif href.startswith("http"):
                external_links += 1

        # Image stats
        images = soup.find_all("img")
        images_missing_alt = len([img for img in images if not img.get("alt")])

        # Use get_text() instead of .string — .string returns None when <title> has child elements
        title_text = soup.title.get_text(strip=True) if soup.title else None

        return {
            "url": page_url,
            "title": title_text,
            "title_length": len(title_text) if title_text else 0,
            "meta_description": get_meta(name="description"),
            "meta_description_length": len(get_meta(name="description") or ""),
            "keywords": get_meta(name="keywords"),
            "canonical": (
                soup.find("link", rel="canonical").get("href")
                if soup.find("link", rel="canonical")
                else None
            ),
            "h1": [h.get_text(strip=True) for h in soup.find_all("h1")],
            "h2": [h.get_text(strip=True) for h in soup.find_all("h2")],
            "images_total": len(images),
            "images_missing_alt": images_missing_alt,
            "image_alts": [img.get("alt").strip() for img in images if img.get("alt") and img.get("alt").strip()],
            "internal_links": internal_links,
            "external_links": external_links,
            "og_title": get_meta(prop="og:title"),
            "og_description": get_meta(prop="og:description"),
            "twitter_title": get_meta(name="twitter:title"),
        }
    
    @staticmethod
    def convert_to_markdown(html: str, url: str) -> str:
        """Convert HTML to clean markdown"""
        title, clean_body, links, images, script_data = cleanup_html(html, url)
        
        converter = html2text.HTML2Text()
        converter.ignore_links = False
        converter.ignore_images = False
        converter.ignore_tables = False
        converter.ignore_emphasis = False
        converter.ignore_style = True
        converter.skip_internal_links = True
        converter.inline_links = False
        converter.body_width = 0
        
        markdown_body = converter.handle(clean_body)
        
        header = [
            f"# {title}",
            f"URL: {url}",
            "",
            "---",
            ""
        ]
        
        return "\n".join(header) + markdown_body + "\n\n---\n"