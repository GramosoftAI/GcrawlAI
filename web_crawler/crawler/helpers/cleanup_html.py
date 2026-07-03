"""
Module for cleaning and minimizing HTML before markdown conversion.

Key steps (mirrors Firecrawl's onlyMainContent pipeline):
  1. Remove boilerplate structural tags (nav, header, footer, aside …)
  2. Remove elements matched by common noise class/id patterns
  3. Strip class, id, data-* attributes (cuts markdown noise)
  4. Strip remaining unwanted tags (style, script, svg, form …)
  5. Minify the body HTML
"""

import json
import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Comment
from minify_html import minify

# ── Constants ─────────────────────────────────────────────────────────────────

# HTML tags that are structural boilerplate — never useful in markdown
_BOILERPLATE_TAGS = (
    "style", "script", "noscript",
    "iframe", "svg", "meta", "head",
    # NOTE: "figure" intentionally excluded — it wraps real content images
)

# class / id substrings that indicate non-content elements. (From Firecrawl excludeNonMainTags)
_NOISE_PATTERNS = (
    "navbar", "navigation", "site-nav", "main-nav", "top-nav", "nav",
    "site-header", "page-header", "header", "#header", ".header",
    "site-footer", "page-footer", "footer", "#footer", ".footer",
    "sidebar", "side-bar", "side", "aside", "#sidebar", ".sidebar",
    "cookie-banner", "cookie-consent", "gdpr-banner", "cookie", "#cookie",
    "popup-overlay", "modal-overlay", "modal", "popup", "overlay",
    "announcement-bar", "breadcrumbs", "breadcrumb", "#breadcrumbs",
    "advertisement", "advert", "ad-unit", "ad-banner", "ad", "ads", "promo-banner",
    "newsletter-signup", "subscribe-popup", "lang-selector", "language",
    "social", "social-media", "social-links", "share", "#share",
    "menu", "widget", "#widget",
    "skip-link", "skipnav", "skip-to-content",
)

# Elements that should be preserved even if they match noise patterns (From Firecrawl forceIncludeMainTags)
_FORCE_INCLUDE_PATTERNS = (
    "#main", "main-content", ".swoogo-cols", ".swoogo-text", ".swoogo-table-div",
    ".swoogo-space", ".swoogo-alert", ".swoogo-sponsors", ".swoogo-title",
    ".swoogo-tabs", ".swoogo-logo", ".swoogo-image", ".swoogo-button", ".swoogo-agenda",
    "elementor", "wp-block"
)

# Attributes to keep — everything else is stripped
_KEEP_ATTRS = {"href", "src", "alt", "title", "colspan", "rowspan"}


def extract_from_script_tags(soup):
    script_content = []

    for script in soup.find_all("script"):
        content = script.string
        if content:
            try:
                json_pattern = r"(?:const|let|var)?\s*\w+\s*=\s*({[\s\S]*?});?$"
                json_matches = re.findall(json_pattern, content)

                for potential_json in json_matches:
                    try:
                        parsed = json.loads(potential_json)
                        if parsed:
                            script_content.append(
                                f"JSON data from script: {json.dumps(parsed, indent=2)}"
                            )
                    except json.JSONDecodeError:
                        pass

                if "window." in content or "document." in content:
                    data_pattern = r"(?:window|document)\.(\w+)\s*=\s*([^;]+);"
                    data_matches = re.findall(data_pattern, content)

                    for var_name, var_value in data_matches:
                        script_content.append(
                            f"Dynamic data - {var_name}: {var_value.strip()}"
                        )
            except Exception:
                if len(content) < 1000:
                    script_content.append(f"Script content: {content.strip()}")

    return "\n\n".join(script_content)


# Compile regexes for noise matching to prevent substrings from matching inside unrelated words (like 'celwidget' matching 'widget')
_NOISE_REGEXES = []
for pat in _NOISE_PATTERNS:
    clean_pat = pat.lstrip("#.")
    regex_str = rf"(?:^|[^a-zA-Z0-9]){re.escape(clean_pat)}(?:$|[^a-zA-Z0-9])"
    _NOISE_REGEXES.append(re.compile(regex_str, re.IGNORECASE))


def _remove_noise_by_class_id(soup: BeautifulSoup) -> None:
    """
    Remove elements whose class or id contains any of the noise pattern keywords.

    Two-pass approach:
      1. Collect all matching tags into a list (snapshot of the tree)
      2. Decompose them — safe because children of already-decomposed
         parents are skipped via the `tag.parent` check.
    """
    to_remove = []
    for tag in soup.find_all(True):
        # Skip tags that were already decomposed by a parent in this loop
        if tag.parent is None:
            continue
        # Never decompose body or html tags
        if tag.name in ("body", "html"):
            continue
        try:
            cls_str  = " ".join(tag.get("class") or []).lower()
            id_str   = (tag.get("id") or "").lower()
        except AttributeError:
            # Tag is in a partially decomposed state — skip it
            continue
        combined = f"{cls_str} {id_str}"
        
        # Check if it should be forced-included
        if any(pat in combined for pat in _FORCE_INCLUDE_PATTERNS):
            continue

        if any(r.search(combined) for r in _NOISE_REGEXES):
            to_remove.append(tag)

    for tag in to_remove:
        # Guard: parent may have already been decomposed
        if tag.parent is not None:
            tag.decompose()


def _absolutize_urls(soup: BeautifulSoup, base_url: str) -> None:
    """
    Resolve all relative href and src attributes to absolute URLs.
    Must run BEFORE attribute stripping so links survive into markdown.

    Without this, html2text produces broken links like:
      [View More](</web-application-development/>)
    Instead of:
      [View More](https://gramosoft.tech/web-application-development/)
    """
    for tag in soup.find_all(True):
        if tag.parent is None:
            continue
        try:
            if tag.get("href"):
                tag["href"] = urljoin(base_url, tag["href"])
            if tag.get("src"):
                tag["src"] = urljoin(base_url, tag["src"])
        except (AttributeError, TypeError):
            continue


def _strip_noisy_attributes(soup: BeautifulSoup) -> None:
    """
    Strip every HTML attribute except those in _KEEP_ATTRS.
    Removes class, id, data-*, aria-*, style, on* handlers, etc.
    This prevents class/id names from leaking into markdown output.
    """
    for tag in soup.find_all(True):
        if tag.parent is None:
            continue  # skip already-decomposed orphans
        try:
            for attr in list(tag.attrs):
                if attr not in _KEEP_ATTRS:
                    del tag[attr]
        except (AttributeError, TypeError):
            continue


def _process_srcset(soup: BeautifulSoup) -> None:
    """
    Firecrawl logic: pick the largest image from srcset and set it as src.
    """
    for img in soup.find_all("img", srcset=True):
        try:
            srcset = img.get("srcset", "")
            if not srcset:
                continue

            # Parse srcset: "url size, url size, ..."
            # size can be "1200w" or "2x"
            candidates = []
            for item in srcset.split(","):
                parts = item.strip().split()
                if not parts:
                    continue
                url = parts[0]
                size_str = parts[1] if len(parts) > 1 else "1x"
                
                # Extract numeric value from size_str (e.g., "1200w" -> 1200, "2x" -> 2)
                size_val = 1
                try:
                    if size_str.lower().endswith(("w", "x")):
                        size_val = int(size_str[:-1]) if size_str[:-1].isdigit() else 1
                except ValueError:
                    size_val = 1
                
                candidates.append({"url": url, "size": size_val})

            if candidates:
                # Sort by size descending
                candidates.sort(key=lambda x: x["size"], reverse=True)
                img["src"] = candidates[0]["url"]
        except Exception:
            continue


def clean_html_firecrawl_style(html_content: str, base_url: str) -> str:
    """
    Cleans HTML to match Firecrawl's clean HTML output format exactly:
      1. Removes <head> entirely.
      2. Removes all <script> and <noscript> tags.
      3. Removes all HTML comments.
      4. Converts all relative href and src attributes to absolute URLs.
      5. Wraps in standard clean <!DOCTYPE html><html lang="en"><body>...</body></html> format.
    """
    soup = BeautifulSoup(html_content, "html.parser")
    
    # 1. Remove <head>
    head = soup.find("head")
    if head:
        head.decompose()
        
    # 2. Remove all <script>, <noscript>, <style>, <meta>, and <iframe> tags
    for tag in soup.find_all(["script", "noscript", "style", "meta", "iframe"]):
        tag.decompose()
        
    # 3. Remove all HTML comments
    for comment in soup.find_all(string=lambda text: isinstance(text, Comment)):
        comment.extract()
        
    # 4. Absolutize relative links (href and src)
    for tag in soup.find_all(True):
        if tag.parent is None:
            continue
        try:
            if tag.get("href"):
                tag["href"] = urljoin(base_url, tag["href"])
            if tag.get("src"):
                tag["src"] = urljoin(base_url, tag["src"])
        except (AttributeError, TypeError):
            continue
            
    # 5. Extract body or fallback to soup
    body = soup.find("body")
    if body:
        body_content = str(body)
    else:
        body_content = f"<body>{str(soup)}</body>"
        
    cleaned_html = (
        "<!DOCTYPE html>\n"
        '<html lang="en">\n'
        f"{body_content}\n"
        "</html>"
    )
    return cleaned_html


def cleanup_html(html_content: str, base_url: str, only_main_content: bool = False, ignore_tags: list = None) -> str:
    """
    Cleans HTML before markdown conversion using a Firecrawl-style pipeline:

      1. Parse with BeautifulSoup
      2. Extract script-tag JSON data (kept for context)
      3. Remove boilerplate structural tags (nav, header, footer …)
      4. Remove elements matched by noise class/id patterns (if only_main_content=True)
      5. Remove custom ignore tags/selectors
      6. Remove HTML comments
      7. Strip noisy attributes (class, id, data-*, aria-*, on* …)
      8. Collect links and image URLs
      9. Minify the body HTML

    Returns:
        (title, minimized_body_html, link_urls, image_urls, script_content)
    """
    soup = BeautifulSoup(html_content, "html.parser")

    # ── Title ─────────────────────────────────────────────────────────────────
    title_tag = soup.find("title")
    title = title_tag.get_text(strip=True) if title_tag else ""

    # ── Script-tag data extraction (before scripts are removed) ───────────────
    script_content = extract_from_script_tags(soup)

    # ── Step 1: Remove completely unneeded tags ───────────────────────────────
    for tag_name in _BOILERPLATE_TAGS:
        for tag in soup.find_all(tag_name):
            tag.decompose()

    # Step 2: Remove noise (only if only_main_content is enabled)
    if only_main_content:
        _remove_noise_by_class_id(soup)
        # Remove hidden cookie banners/popups
        for tag in soup.find_all(attrs={"data-gcrawl-hidden": "true"}):
            if tag.name not in ("body", "html"):
                tag.decompose()
    else:
        # Even in non-main-content mode, we still remove the absolute unneeded tags
        # passed in _BOILERPLATE_TAGS already (script, style, etc.)
        pass

    # Step 2.5: Remove user-defined ignore_tags (CSS selectors supported)
    if ignore_tags:
        for selector in ignore_tags:
            try:
                for tag in soup.select(selector.strip()):
                    tag.decompose()
            except Exception:
                try:
                    for tag in soup.find_all(selector.strip()):
                        tag.decompose()
                except:
                    pass

    # ── Step 3: Remove HTML comments ─────────────────────────────────────────
    for comment in soup.find_all(string=lambda text: isinstance(text, Comment)):
        comment.extract()

    # ── Step 3b: Process srcset images ───────────────────────────────────────
    _process_srcset(soup)

    # ── Step 4: Absolutize href/src BEFORE stripping attributes ──────────────
    # This ensures html2text always sees full absolute URLs in links/images.
    _absolutize_urls(soup, base_url)

    # ── Step 5: Strip noisy attributes ──────────────────────────────────────────
    _strip_noisy_attributes(soup)

    # ── Collect links and images (after absolutizing, before minify) ──────────
    link_urls = [
        link["href"] for link in soup.find_all("a", href=True)
    ]

    image_urls = [
        img["src"] for img in soup.find_all("img", src=True)
    ]

    # ── return body ────────────────────────────────────────────────
    body_content = soup.find("body")
    if not body_content:
        # Fallback to entire soup structure wrapped/represented as body if no <body> exists
        body_content = soup
    return title, str(body_content), link_urls, image_urls, script_content


def minify_html(html):
    """
    minify_html function
    """
    # Combine multiple regex operations into one for better performance
    patterns = [
        (r"<!--.*?-->", "", re.DOTALL),
        (r">\s+<", "><", 0),
        (r"\s+>", ">", 0),
        (r"<\s+", "<", 0),
        (r"\s+", " ", 0),
        (r"\s*=\s*", "=", 0),
    ]

    for pattern, repl, flags in patterns:
        html = re.sub(pattern, repl, html, flags=flags)

    return html.strip()


def reduce_html(html, reduction):
    """
    Reduces the size of the HTML content based on the specified level of reduction.

    Args:
        html (str): The HTML content to reduce.
        reduction (int): The level of reduction to apply to the HTML content.
            0: minification only,
            1: minification and removig unnecessary tags and attributes,
            2: minification, removig unnecessary tags and attributes,
            simplifying text content, removing of the head tag

    Returns:
        str: The reduced HTML content based on the specified reduction level.
    """
    if reduction == 0:
        return minify_html(html)

    soup = BeautifulSoup(html, "html.parser")

    for comment in soup.find_all(string=lambda text: isinstance(text, Comment)):
        comment.extract()

    for tag in soup(["style"]):
        tag.string = ""

    attrs_to_keep = ["class", "id", "href", "src", "type"]
    for tag in soup.find_all(True):
        for attr in list(tag.attrs):
            if attr not in attrs_to_keep:
                del tag[attr]

    if reduction == 1:
        return minify_html(str(soup))

    for tag in soup(["style"]):
        tag.decompose()

    body = soup.body
    if not body:
        return "No <body> tag found in the HTML"

    for tag in body.find_all(string=True):
        if tag.parent.name not in ["script"]:
            tag.replace_with(re.sub(r"\s+", " ", tag.strip())[:20])

    reduced_html = str(body)

    reduced_html = minify_html(reduced_html)

    return reduced_html


def clean_html_dynamic(html_content: str, base_url: str, config) -> str:
    """
    Dynamically cleans HTML content based on CrawlConfig options.
    """
    soup = BeautifulSoup(html_content, "html.parser")
    
    # 1. Remove ignore_tags (CSS selectors supported)
    if config.html_ignore_tags:
        for selector in config.html_ignore_tags:
            try:
                for tag in soup.select(selector.strip()):
                    tag.decompose()
            except Exception:
                try:
                    for tag in soup.find_all(selector.strip()):
                        tag.decompose()
                except:
                    pass
                
    # 2. General cleaning if clean is enabled
    if config.html_clean:
        # Remove head
        head = soup.find("head")
        if head:
            head.decompose()
            
        # Remove scripts, style, noscript, meta, iframe
        for tag_name in ["script", "noscript", "style", "meta", "iframe"]:
            for tag in soup.find_all(tag_name):
                tag.decompose()
            
        # Remove HTML comments
        for comment in soup.find_all(string=lambda text: isinstance(text, Comment)):
            comment.extract()
            
        # Remove hidden cookie banners/popups
        for tag in soup.find_all(attrs={"data-gcrawl-hidden": "true"}):
            if tag.name not in ("body", "html"):
                tag.decompose()
            
    # 3. Relative to absolute links conversion
    if config.html_relative_to_absolute_links:
        for tag in soup.find_all(True):
            if tag.parent is None:
                continue
            try:
                if tag.get("href"):
                    tag["href"] = urljoin(base_url, tag["href"])
                if tag.get("src"):
                    tag["src"] = urljoin(base_url, tag["src"])
            except (AttributeError, TypeError):
                continue
                
    # 4. Remove external links
    if config.html_remove_external_links:
        from urllib.parse import urlparse
        base_domain = urlparse(base_url).netloc.lower()
        if base_domain.startswith("www."):
            base_domain = base_domain[4:]
        
        for tag in soup.find_all("a", href=True):
            href = tag["href"]
            try:
                href_domain = urlparse(href).netloc.lower()
                if href_domain.startswith("www."):
                    href_domain = href_domain[4:]
                if href_domain and href_domain != base_domain:
                    tag.unwrap()
            except Exception:
                pass
                
    # 5. Remove data images (images starting with data:)
    if config.html_remove_data_images:
        for img in soup.find_all("img", src=True):
            src = img["src"].strip()
            if src.startswith("data:"):
                img.decompose()
                
    # 6. Extract body or fallback to soup if clean is requested, otherwise return the full document
    if not config.html_clean:
        return str(soup)

    body = soup.find("body")
    if body:
        body_content = str(body)
    else:
        body_content = f"<body>{str(soup)}</body>"
        
    cleaned_html = (
        "<!DOCTYPE html>\n"
        '<html lang="en">\n'
        f"{body_content}\n"
        "</html>"
    )
    return cleaned_html

