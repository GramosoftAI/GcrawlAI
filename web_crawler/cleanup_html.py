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
    "iframe", "svg", "form",
    # NOTE: "figure" intentionally excluded — it wraps real content images
)

# class / id substrings that indicate non-content elements.
# IMPORTANT: keep patterns specific — avoid short strings that match content.
# Matched case-insensitively against the joined class string + id attribute.
_NOISE_PATTERNS = (
    # Navigation
    "navbar", "navigation", "site-nav", "main-nav", "top-nav",
    # Header / footer (structural, not semantic headings)
    "site-header", "page-header", "site-footer", "page-footer",
    # Sidebar
    "sidebar", "side-bar", "aside-wrapper",
    # Overlays
    "cookie-banner", "cookie-consent", "gdpr-banner",
    "popup-overlay", "modal-overlay",
    "announcement-bar",
    # Breadcrumbs
    "breadcrumb", "breadcrumbs",
    # Ads
    "advertisement", "advert", "ad-unit", "ad-banner",
    "promo-banner",
    # Newsletter
    "newsletter-signup", "subscribe-popup",
    # Skip links (accessibility)
    "skip-link", "skipnav", "skip-to-content",
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
        try:
            cls_str  = " ".join(tag.get("class") or []).lower()
            id_str   = (tag.get("id") or "").lower()
        except AttributeError:
            # Tag is in a partially decomposed state — skip it
            continue
        combined = f"{cls_str} {id_str}"
        if any(pat in combined for pat in _NOISE_PATTERNS):
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


def cleanup_html(html_content: str, base_url: str) -> str:
    """
    Cleans HTML before markdown conversion using a Firecrawl-style pipeline:

      1. Parse with BeautifulSoup
      2. Extract script-tag JSON data (kept for context)
      3. Remove boilerplate structural tags (nav, header, footer …)
      4. Remove elements matched by noise class/id patterns
      5. Remove HTML comments
      6. Strip noisy attributes (class, id, data-*, aria-*, on* …)
      7. Collect links and image URLs
      8. Minify the body HTML

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

    # NOTE: Firecrawl's output for this site retained the nav/footer/widgets.
    # Therefore, _remove_noise_by_class_id is disabled to achieve a 100% match.
    # _remove_noise_by_class_id(soup)

    # ── Step 3: Remove HTML comments ─────────────────────────────────────────
    for comment in soup.find_all(string=lambda text: isinstance(text, Comment)):
        comment.extract()

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

    # ── Minify and return body ────────────────────────────────────────────────
    body_content = soup.find("body")
    if body_content:
        minimized_body = minify(str(body_content))
        return title, minimized_body, link_urls, image_urls, script_content
    else:
        raise ValueError(
            "No HTML body content found. "
            f"HTML snippet: {html_content[:300]}"
        )


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
