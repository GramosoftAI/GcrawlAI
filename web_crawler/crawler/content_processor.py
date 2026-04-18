"""
Content processing and extraction utilities
"""

from typing import List, Dict
from bs4 import BeautifulSoup
import html2text
from urllib.parse import urlparse, urljoin
from web_crawler.common.utils import absolutize_url
from web_crawler.crawler.cleanup_html import cleanup_html


def _post_process_markdown(md: str) -> str:
    """
    Firecrawl-style markdown post-processing:
      1. Strip trailing whitespace from every line
      2. Collapse 3+ consecutive blank lines into exactly 2
      3. Remove leading / trailing blank lines from the whole document
    """
    # 1. Strip trailing whitespace per line
    lines = [line.rstrip() for line in md.splitlines()]

    # 2. Collapse runs of 3+ blank lines → 2 blank lines
    result = []
    blank_run = 0
    for line in lines:
        if line == "":
            blank_run += 1
            if blank_run <= 2:
                result.append(line)
        else:
            blank_run = 0
            result.append(line)

    # 3. Fix multi-line links (Firecrawl style: add backslashes before newlines in links)
    # Also handle cases where html2text joined multiple elements inside a link.
    # We look for patterns like "![" or "**" or existing newlines inside [...] 
    # and ensure they are formatted as multi-line links with \\ escapes.
    
    # First, let's fix the specific joined text case for complex links:
    # Look for [ ... ![ ... ] ... ] and ensure proper spacing.
    import re
    
    def fix_link_formatting(match):
        content = match.group(1)
        # 1. Handle existing newlines
        content = content.replace("\n", "\\\\\n")
        # 2. Add extra breaks before internal elements (image/bold/headers)
        # We look for a position that is NOT the start of the content.
        def add_break(m):
            return f"{m.group(1)}\\\\\n{m.group(2)}"
        
        # If there's an image or bold text preceded by anything, insert a break
        content = re.sub(r'(.+?)\s*(!\[|\*\*)', add_break, content)
        return f"[{content}]"

    doc = "\n".join(result)
    doc = re.sub(r'\[(.*?)\](?=\()', fix_link_formatting, doc, flags=re.DOTALL)

    # 4. Remove "Skip to Content" links
    doc = re.sub(r'\[Skip to Content\]\(#[^\)]*\)', '', doc, flags=re.IGNORECASE)

    # 5. Collapse duplicate newlines inside escaped links if any
    doc = re.sub(r'(\\\\\n){2,}', '\\\\\n\\\\\n', doc)

    # 6. Final cleanup: strip leading/trailing blank lines
    return doc.strip() + "\n"



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
    def convert_to_markdown(html: str, url: str, only_main_content: bool = False) -> str:
        """Convert HTML to clean, LLM-ready markdown (Firecrawl-style)"""
        title, clean_body, links, images, script_data = cleanup_html(html, url, only_main_content)

        converter = html2text.HTML2Text()
        converter.ignore_links      = False
        converter.ignore_images     = False
        converter.ignore_tables     = False
        converter.ignore_emphasis   = False    # Firecrawl preserves bold "**"
        converter.ignore_style      = True
        converter.skip_internal_links = False
        converter.inline_links      = True
        converter.body_width        = 0        # Firecrawl does NOT wrap lines
        converter.protect_links     = False
        converter.wrap_links        = False

        markdown_body = converter.handle(clean_body)

        # Post-process: collapse blank lines, strip trailing whitespace
        markdown_body = _post_process_markdown(markdown_body)

        # Replace standard html2text list markers `* ` with Firecrawl's `- `
        import re
        markdown_body = re.sub(r'(?m)^(\s*)\*\s', r'\1- ', markdown_body)

        # Firecrawl renders lists compactly. html2text often inserts blank lines between list items.
        # Collapse double newlines between list items into a single newline.
        markdown_body = re.sub(r'\n{2,}(?=\s*- )', '\n', markdown_body)

        return markdown_body + "\n"