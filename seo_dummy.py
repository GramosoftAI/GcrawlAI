from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
import json
from openpyxl import Workbook


# ----------------------------
# Helpers
# ----------------------------

def get_domain_name(url):
    parsed = urlparse(url)
    return parsed.netloc.replace("www.", "")


def is_internal_link(base_domain, link):
    return base_domain in urlparse(link).netloc


def save_excel(domain, seo_data):
    file_name = f"{domain}_seo.xlsx"

    wb = Workbook()
    ws = wb.active
    ws.title = "SEO Report"

    headers = [
        "URL",
        "Title",
        "Title Length",
        "Meta Description",
        "Meta Description Length",
        "H1 Count",
        "H2 Count",
        "Images Total",
        "Images Missing ALT",
        "Internal Links",
        "External Links",
        "OG Title",
        "OG Description",
        "Twitter Title"
    ]

    ws.append(headers)

    for page in seo_data:
        ws.append([
            page["url"],
            page["title"],
            page["title_length"],
            page["meta_description"],
            page["meta_description_length"],
            len(page["h1"]),
            len(page["h2"]),
            page["images_total"],
            page["images_missing_alt"],
            page["internal_links"],
            page["external_links"],
            page["og_title"],
            page["og_description"],
            page["twitter_title"],
        ])

    wb.save(file_name)
    print(f"✅ Saved: {file_name}")


# ----------------------------
# Extract SEO data
# ----------------------------

def seo_extract_data(soup, base_url):

    def get_meta(name=None, prop=None):
        if name:
            tag = soup.find("meta", attrs={"name": name})
        else:
            tag = soup.find("meta", attrs={"property": prop})
        return tag.get("content").strip() if tag and tag.get("content") else None

    internal_links = 0
    external_links = 0

    for link in soup.find_all("a", href=True):
        href = link["href"]
        if href.startswith("/"):
            internal_links += 1
        elif href.startswith("http"):
            external_links += 1

    images = soup.find_all("img")

    seo_data = {
        "url": base_url,
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
        "images_missing_alt": len([img for img in images if not img.get("alt")]),
        "internal_links": internal_links,
        "external_links": external_links,
        "og_title": get_meta(prop="og:title"),
        "og_description": get_meta(prop="og:description"),
        "twitter_title": get_meta(name="twitter:title"),
    }

    return seo_data


# ----------------------------
# Extract all links
# ----------------------------

def extract_links(soup, base_url):
    base_domain = get_domain_name(base_url)
    links = set()

    for a in soup.find_all("a", href=True):
        href = a["href"].strip()

        if href.startswith("#") or href.startswith("mailto:") or href.startswith("tel:"):
            continue

        full_url = urljoin(base_url, href)
        full_url = full_url.split("#")[0]

        if is_internal_link(base_domain, full_url):
            links.add(full_url.rstrip("/"))

    return sorted(list(links))


# ----------------------------
# Scroll page
# ----------------------------

def scroll_to_bottom(page):
    prev_height = 0
    for _ in range(15):
        page.evaluate("window.scrollBy(0, window.innerHeight)")
        page.wait_for_timeout(800)
        height = page.evaluate("document.body.scrollHeight")
        if height == prev_height:
            break
        prev_height = height


# ----------------------------
# Main crawler
# ----------------------------

def crawl_site(base_url):
    domain = get_domain_name(base_url)
    all_seo_data = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0",
            viewport={"width": 1920, "height": 1080},
        )

        page = context.new_page()

        print("🔍 Loading base URL...")
        page.goto(base_url, wait_until="networkidle")
        scroll_to_bottom(page)

        soup = BeautifulSoup(page.content(), "html.parser")

        links = extract_links(soup, base_url)

        print(f"✅ Found {len(links)} internal links\n")

        # include homepage also
        links.insert(0, base_url)

        for link in links:
            try:
                print("➡ Crawling:", link)
                page.goto(link, wait_until="networkidle")
                scroll_to_bottom(page)

                soup = BeautifulSoup(page.content(), "html.parser")
                print(soup)
                print("----------------------------------------\n", link)
                seo_data = seo_extract_data(soup, link)

                all_seo_data.append(seo_data)

            except Exception as e:
                print("❌ Error:", link, e)

        browser.close()

    save_outputs(domain, all_seo_data, links)


# ----------------------------
# Save Outputs
# ----------------------------

def save_outputs(domain, seo_data, links):

    json_file = f"{domain}_seo.json"
    md_file = f"{domain}_seo.md"

    output = {
        "total_pages": len(seo_data),
        "links": links,
        "pages": seo_data
    }

    with open(json_file, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=4, ensure_ascii=False)

    md = f"# SEO Crawl Report — {domain}\n\n"
    md += f"## Total Pages: {len(seo_data)}\n\n"

    md += "## Crawled Links\n"
    for l in links:
        md += f"- {l}\n"

    md += "\n---\n"

    for page in seo_data:
        md += f"\n## {page['url']}\n"
        md += f"- Title: {page['title']}\n"
        md += f"- Meta Description: {page['meta_description']}\n"
        md += f"- H1: {', '.join(page['h1'])}\n"
        md += f"- Images Missing ALT: {page['images_missing_alt']}\n"
        md += f"- Internal Links: {page['internal_links']}\n"
        md += f"- External Links: {page['external_links']}\n"

    with open(md_file, "w", encoding="utf-8") as f:
        f.write(md)

    print(f"\n✅ Saved: {json_file}")
    print(f"✅ Saved: {md_file}")
    save_excel(domain, seo_data)


# ----------------------------
# RUN
# ----------------------------

crawl_site("https://gramosoft.tech/")