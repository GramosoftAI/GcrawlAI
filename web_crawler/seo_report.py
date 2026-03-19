import base64
import json
from io import BytesIO
from pathlib import Path
from typing import Dict, List

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

    def render_json(self, pages: List[Dict], links: List[str] = None) -> str:
        output = {
            "total_pages": len(pages),
            "links": links or [],
            "pages": pages,
        }
        return json.dumps(output, indent=4, ensure_ascii=False)

    def render_markdown(
        self,
        domain: str,
        pages: List[Dict],
        links: List[str] = None,
    ) -> str:
        md = f"# SEO Crawl Report - {domain}\n\n"
        md += f"## Total Pages: {len(pages)}\n\n"

        if links:
            md += "## Crawled Links\n"
            for link in links:
                md += f"- {link}\n"
            md += "\n"

        for page in pages:
            seo = page.get("seo", {}) if "seo" in page else page
            if not seo:
                continue

            md += "---\n\n"
            md += f"## {seo.get('url')}\n"
            md += f"- **Title:** {seo.get('title')}\n"
            md += f"- **Meta Description:** {seo.get('meta_description')}\n"
            md += f"- **Keywords:** {seo.get('keywords')}\n"

            h1s = seo.get("h1", [])
            if isinstance(h1s, list) and h1s:
                md += f"- **H1 Content:** {', '.join(h1s)}\n"

            h2s = seo.get("h2", [])
            if isinstance(h2s, list) and h2s:
                md += f"- **H2 Content:** {', '.join(h2s)}\n"

            image_alts = seo.get("image_alts", [])
            if isinstance(image_alts, list) and image_alts:
                suffix = "..." if len(image_alts) > 10 else ""
                md += f"- **Image Alts:** {', '.join(image_alts[:10])}{suffix}\n"

            md += f"- **Images Missing ALT:** {seo.get('images_missing_alt')}\n"
            md += f"- **Internal Links:** {seo.get('internal_links')}\n"
            md += f"- **External Links:** {seo.get('external_links')}\n\n"

        return md

    def render_excel_base64(self, pages: List[Dict]) -> str:
        wb = Workbook()
        ws = wb.active
        ws.title = "SEO Report"

        headers = [
            "URL",
            "Title",
            "Title Length",
            "Meta Description",
            "Meta Description Length",
            "Keywords",
            "H1 Count",
            "H1 Content",
            "H2 Count",
            "H2 Content",
            "Images Total",
            "Images Missing ALT",
            "Image Alts",
            "Internal Links",
            "External Links",
            "OG Title",
            "OG Description",
            "Twitter Title",
        ]
        ws.append(headers)

        for page in pages:
            seo = page.get("seo", {})
            ws.append(
                [
                    page.get("url"),
                    seo.get("title"),
                    seo.get("title_length"),
                    seo.get("meta_description"),
                    seo.get("meta_description_length"),
                    seo.get("keywords"),
                    len(seo.get("h1", [])),
                    ", ".join(seo.get("h1", [])),
                    len(seo.get("h2", [])),
                    ", ".join(seo.get("h2", [])),
                    seo.get("images_total"),
                    seo.get("images_missing_alt"),
                    ", ".join(seo.get("image_alts", [])),
                    seo.get("internal_links"),
                    seo.get("external_links"),
                    seo.get("og_title"),
                    seo.get("og_description"),
                    seo.get("twitter_title"),
                ]
            )

        buffer = BytesIO()
        wb.save(buffer)
        return base64.b64encode(buffer.getvalue()).decode("utf-8")

    def render_single_json(self, seo_data: Dict) -> str:
        output = {
            "url": seo_data.get("url"),
            "data": seo_data,
        }
        return json.dumps(output, indent=4, ensure_ascii=False)

    def render_single_markdown(self, seo_data: Dict) -> str:
        md = f"# SEO Report: {seo_data.get('title')}\n\n"
        md += f"**URL:** {seo_data.get('url')}\n"
        md += f"**Title Length:** {seo_data.get('title_length')}\n"
        md += f"**Meta Description:** {seo_data.get('meta_description')}\n"
        md += (
            f"**Meta Desc Length:** {seo_data.get('meta_description_length')}\n"
        )
        md += f"**Keywords:** {seo_data.get('keywords')}\n\n"

        md += "## Headers\n"
        h1s = seo_data.get("h1", [])
        md += f"- **H1 ({len(h1s)}):** {', '.join(h1s)}\n"
        h2s = seo_data.get("h2", [])
        md += f"- **H2 ({len(h2s)}):** {', '.join(h2s)}\n\n"

        md += "## Images\n"
        md += f"- Total: {seo_data.get('images_total')}\n"
        md += f"- Missing ALT: {seo_data.get('images_missing_alt')}\n"
        alts = seo_data.get("image_alts", [])
        suffix = "..." if len(alts) > 10 else ""
        md += f"- Image Alts: {', '.join(alts[:10])}{suffix}\n\n"

        md += "## Links\n"
        md += f"- Internal: {seo_data.get('internal_links')}\n"
        md += f"- External: {seo_data.get('external_links')}\n\n"

        md += "## Social\n"
        md += f"- OG Title: {seo_data.get('og_title')}\n"
        md += f"- OG Description: {seo_data.get('og_description')}\n"
        md += f"- Twitter Title: {seo_data.get('twitter_title')}\n"
        return md

    def render_single_excel_base64(self, seo_data: Dict) -> str:
        wb = Workbook()
        ws = wb.active
        ws.title = "SEO Data"
        ws.append(["Metric", "Value"])

        rows = [
            ("URL", seo_data.get("url")),
            ("Title", seo_data.get("title")),
            ("Title Length", seo_data.get("title_length")),
            ("Meta Description", seo_data.get("meta_description")),
            ("Meta Description Length", seo_data.get("meta_description_length")),
            ("Keywords", seo_data.get("keywords")),
            ("H1 Count", len(seo_data.get("h1", []))),
            ("H1 Content", ", ".join(seo_data.get("h1", []))),
            ("H2 Count", len(seo_data.get("h2", []))),
            ("H2 Content", ", ".join(seo_data.get("h2", []))),
            ("Images Total", seo_data.get("images_total")),
            ("Images Missing ALT", seo_data.get("images_missing_alt")),
            ("Image Alts", ", ".join(seo_data.get("image_alts", []))),
            ("Internal Links", seo_data.get("internal_links")),
            ("External Links", seo_data.get("external_links")),
            ("OG Title", seo_data.get("og_title")),
            ("OG Description", seo_data.get("og_description")),
            ("Twitter Title", seo_data.get("twitter_title")),
        ]
        for row in rows:
            ws.append(row)

        buffer = BytesIO()
        wb.save(buffer)
        return base64.b64encode(buffer.getvalue()).decode("utf-8")

    def save_json(self, domain: str, pages: List[Dict], links: List[str] = None) -> str:
        file_path = self.output_dir / "seo" / f"{domain}_seo.json"
        file_path.parent.mkdir(parents=True, exist_ok=True)
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(self.render_json(pages, links))
        return str(file_path)

    def save_markdown(
        self,
        domain: str,
        pages: List[Dict],
        links: List[str] = None,
    ) -> str:
        file_path = self.output_dir / "seo" / f"{domain}_seo.md"
        file_path.parent.mkdir(parents=True, exist_ok=True)
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(self.render_markdown(domain, pages, links))
        return str(file_path)

    def save_excel(self, domain: str, pages: List[Dict]) -> str:
        file_path = self.output_dir / "seo" / f"{domain}_seo.xlsx"
        file_path.parent.mkdir(parents=True, exist_ok=True)
        with open(file_path, "wb") as f:
            f.write(base64.b64decode(self.render_excel_base64(pages)))
        return str(file_path)

    def save_single_json(self, filename: str, seo_data: Dict) -> str:
        file_path = self.output_dir / "seo" / f"{filename}.json"
        file_path.parent.mkdir(parents=True, exist_ok=True)
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(self.render_single_json(seo_data))
        return str(file_path)

    def save_single_markdown(self, filename: str, seo_data: Dict) -> str:
        file_path = self.output_dir / "seo" / f"{filename}.md"
        file_path.parent.mkdir(parents=True, exist_ok=True)
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(self.render_single_markdown(seo_data))
        return str(file_path)

    def save_single_excel(self, filename: str, seo_data: Dict) -> str:
        file_path = self.output_dir / "seo" / f"{filename}.xlsx"
        file_path.parent.mkdir(parents=True, exist_ok=True)
        with open(file_path, "wb") as f:
            f.write(base64.b64decode(self.render_single_excel_base64(seo_data)))
        return str(file_path)
