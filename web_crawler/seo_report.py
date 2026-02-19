import json
from pathlib import Path
from typing import List, Dict
from openpyxl import Workbook


class CrawlReportWriter:
    """
    Handle crawl output formats:
    - JSON
    - Markdown
    - Excel
    """

    def __init__(self, output_dir: Path):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------
    # 1️⃣ JSON
    # ------------------------------------------------
    def save_json(self, domain: str, pages: List[Dict], links: List[str] = None) -> str:
        file_path = self.output_dir / f"{domain}_seo.json"

        output = {
            "total_pages": len(pages),
            "links": links or [],
            "pages": pages
        }

        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(output, f, indent=4, ensure_ascii=False)

        return str(file_path)

    # ------------------------------------------------
    # 2️⃣ Markdown
    # ------------------------------------------------
    def save_markdown(self, domain: str, pages: List[Dict], links: List[str] = None) -> str:
        file_path = self.output_dir / f"{domain}_seo.md"

        md = f"# SEO Crawl Report — {domain}\n\n"
        md += f"## Total Pages: {len(pages)}\n\n"
        
        if links:
            md += "## Crawled Links\n"
            for l in links:
                md += f"- {l}\n"
            md += "\n"

        for page in pages:
            # seo is now directly part of page dict or under "seo" key depending on how we structured it
            # In seo.py, seo_data IS the page dict. In web_crawler, result has "seo" key.
            # We need to handle both or standardize.
            # Based on ContentProcessor, seo data is flattened? No, it returns a dict.
            # web_crawler.py: result = { ..., "seo": seo, ... }
            # So we need to access page["seo"]
            
            seo = page.get("seo", {}) if "seo" in page else page
            
            # If seo is empty/None, skip or show error
            if not seo:
                continue

            md += f"---\n\n"
            md += f"## {seo.get('url')}\n"
            md += f"- **Title:** {seo.get('title')}\n"
            md += f"- **Meta Description:** {seo.get('meta_description')}\n"
            
            h1s = seo.get('h1', [])
            if isinstance(h1s, list):
                md += f"- **H1:** {', '.join(h1s)}\n"
            
            md += f"- **Images Missing ALT:** {seo.get('images_missing_alt')}\n"
            md += f"- **Internal Links:** {seo.get('internal_links')}\n"
            md += f"- **External Links:** {seo.get('external_links')}\n\n"

        with open(file_path, "w", encoding="utf-8") as f:
            f.write(md)

        return str(file_path)

    # ------------------------------------------------
    # 3️⃣ Excel
    # ------------------------------------------------
    def save_excel(self, domain: str, pages: List[Dict]) -> str:
        file_path = self.output_dir / f"{domain}_seo.xlsx"

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

        for page in pages:
            seo = page.get("seo", {})

            ws.append([
                page.get("url"),
                seo.get("title"),
                seo.get("title_length"),
                seo.get("meta_description"),
                seo.get("meta_description_length"),
                len(seo.get("h1", [])),
                len(seo.get("h2", [])),
                seo.get("images_total"),
                seo.get("images_missing_alt"),
                seo.get("internal_links"),
                seo.get("external_links"),
                seo.get("og_title"),
                seo.get("og_description"),
                seo.get("twitter_title"),
            ])

        wb.save(file_path)

        return str(file_path)

    # ------------------------------------------------
    # 4️⃣ Single Page Reports
    # ------------------------------------------------
    def save_single_json(self, filename: str, seo_data: Dict) -> str:
        file_path = self.output_dir / "seo" / f"{filename}.json"
        
        output = {
            "url": seo_data.get("url"),
            "data": seo_data
        }
        
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(output, f, indent=4, ensure_ascii=False)
            
        return str(file_path)

    def save_single_markdown(self, filename: str, seo_data: Dict) -> str:
        file_path = self.output_dir / "seo" / f"{filename}.md"
        
        md = f"# SEO Report: {seo_data.get('title')}\n\n"
        md += f"**URL:** {seo_data.get('url')}\n"
        md += f"**Title Length:** {seo_data.get('title_length')}\n"
        md += f"**Meta Description:** {seo_data.get('meta_description')}\n"
        md += f"**Meta Desc Length:** {seo_data.get('meta_description_length')}\n\n"
        
        md += "## Headers\n"
        md += f"- **H1 ({len(seo_data.get('h1', []))}):** {', '.join(seo_data.get('h1', []))}\n"
        md += f"- **H2 ({len(seo_data.get('h2', []))}):** {len(seo_data.get('h2', []))} found\n\n"
        
        md += "## Images\n"
        md += f"- Total: {seo_data.get('images_total')}\n"
        md += f"- Missing ALT: {seo_data.get('images_missing_alt')}\n\n"
        
        md += "## Links\n"
        md += f"- Internal: {seo_data.get('internal_links')}\n"
        md += f"- External: {seo_data.get('external_links')}\n\n"
        
        md += "## Social\n"
        md += f"- OG Title: {seo_data.get('og_title')}\n"
        md += f"- OG Description: {seo_data.get('og_description')}\n"
        md += f"- Twitter Title: {seo_data.get('twitter_title')}\n"
        
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(md)
            
        return str(file_path)

    def save_single_excel(self, filename: str, seo_data: Dict) -> str:
        file_path = self.output_dir / "seo" / f"{filename}.xlsx"
        
        wb = Workbook()
        ws = wb.active
        ws.title = "SEO Data"
        
        headers = [
            "Metric", "Value"
        ]
        ws.append(headers)
        
        rows = [
            ("URL", seo_data.get("url")),
            ("Title", seo_data.get("title")),
            ("Title Length", seo_data.get("title_length")),
            ("Meta Description", seo_data.get("meta_description")),
            ("Meta Description Length", seo_data.get("meta_description_length")),
            ("H1 Count", len(seo_data.get("h1", []))),
            ("H2 Count", len(seo_data.get("h2", []))),
            ("Images Total", seo_data.get("images_total")),
            ("Images Missing ALT", seo_data.get("images_missing_alt")),
            ("Internal Links", seo_data.get("internal_links")),
            ("External Links", seo_data.get("external_links")),
            ("OG Title", seo_data.get("og_title")),
            ("OG Description", seo_data.get("og_description")),
            ("Twitter Title", seo_data.get("twitter_title")),
        ]
        
        for row in rows:
            ws.append(row)
            
        wb.save(file_path)
        return str(file_path)
