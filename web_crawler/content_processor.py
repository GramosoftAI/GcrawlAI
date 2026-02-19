"""
Content processing and extraction utilities
"""

from typing import List, Dict
from bs4 import BeautifulSoup
import html2text
from web_crawler.utils import absolutize_url
from web_crawler.cleanup_html import cleanup_html


class ContentProcessor:
    """Process and extract content from pages"""
    
    @staticmethod
    def extract_links(soup: BeautifulSoup, base_url: str) -> List[str]:
        """Extract all valid links from page"""
        links = set()
        for anchor in soup.find_all("a", href=True):
            href = anchor["href"].strip()
            if href.startswith("#"):
                continue
            
            url = absolutize_url(href, base_url)
            if url.startswith("http"):
                links.add(url)
        
        return list(links)
    
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

        return {
            "url": page_url,
            "title": soup.title.string.strip() if soup.title else None,
            "title_length": len(soup.title.string.strip()) if soup.title else 0,
            "meta_description": get_meta(name="description"),
            "meta_description_length": len(get_meta(name="description") or ""),
            "canonical": (
                soup.find("link", rel="canonical").get("href")
                if soup.find("link", rel="canonical")
                else None
            ),
            "h1": [h.get_text(strip=True) for h in soup.find_all("h1")],
            "h2": [h.get_text(strip=True) for h in soup.find_all("h2")],
            "images_total": len(images),
            "images_missing_alt": images_missing_alt,
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