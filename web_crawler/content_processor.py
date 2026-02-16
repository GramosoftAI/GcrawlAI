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
        """Extract SEO metadata"""
        def get_meta(name=None, prop=None):
            attrs = {"name": name} if name else {"property": prop}
            tag = soup.find("meta", attrs=attrs)
            return tag.get("content", "").strip() if tag else ""
        
        canonical_tag = soup.find("link", rel="canonical")
        
        return {
            "title": soup.title.text.strip() if soup.title else "",
            "meta_description": get_meta(name="description"),
            "canonical": canonical_tag["href"] if canonical_tag else page_url,
            "h1_count": len(soup.find_all("h1")),
            "word_count": len(" ".join(soup.stripped_strings).split()),
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