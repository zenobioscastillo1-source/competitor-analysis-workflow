"""Render a branded PDF competitor report from analysis JSON + the brand kit.

Builds a self-contained HTML document (fonts and logo base64-embedded, so there
are no external file dependencies) from templates/report_template.html, then
prints it to PDF with headless Chromium via Playwright. Chromium gives full
fidelity for custom fonts, exact brand colors, and A4 paged media.

Usage:
    python tools/render_pdf_report.py \
        --analysis .tmp/analysis.json \
        --brand brand/brand_kit.json \
        --output "reports/Nerumi_Competitive_Landscape_2026-05-28.pdf"

One-time setup (already in requirements.txt): `playwright install chromium`.
"""
from __future__ import annotations

import argparse
import base64
import json
import re
import sys
from pathlib import Path

from config import PROJECT_ROOT
from jinja2 import Environment, FileSystemLoader, select_autoescape
from markupsafe import Markup, escape
from util import slugify

TEMPLATES_DIR = PROJECT_ROOT / "templates"
TEMPLATE_NAME = "report_template.html"


def _resolve(path_str: str) -> Path:
    p = Path(path_str)
    return p if p.is_absolute() else (PROJECT_ROOT / p)


def build_font_face_css(fonts: dict) -> str:
    rules = []
    for group in fonts.values():
        family = group["family"]
        for face in group.get("faces", []):
            font_file = _resolve(face["file"])
            if not font_file.exists():
                print(f"WARNING: font file not found, skipping: {font_file}", file=sys.stderr)
                continue
            b64 = base64.b64encode(font_file.read_bytes()).decode("ascii")
            rules.append(
                "@font-face{font-family:'%s';font-style:%s;font-weight:%s;"
                "font-display:swap;src:url(data:font/woff2;base64,%s) format('woff2');}"
                % (family, face.get("style", "normal"), face.get("weight", 400), b64)
            )
    return "<style>\n" + "\n".join(rules) + "\n</style>"


def build_css_vars(brand: dict) -> str:
    colors = brand["colors"]
    radius = brand.get("radius", {})
    lines = [f"  --{k.replace('_', '-')}: {v};" for k, v in colors.items()]
    lines += [f"  --radius-{k}: {v};" for k, v in radius.items()]
    lines.append(f"  --font-sans: {brand['fonts']['sans']['stack']};")
    lines.append(f"  --font-serif: {brand['fonts']['serif']['stack']};")
    return ":root{\n" + "\n".join(lines) + "\n}"


def build_logo_svg(brand: dict) -> str:
    logo = brand.get("logo", {})
    mark_path = logo.get("mark")
    if not mark_path:
        return ""
    svg_file = _resolve(mark_path)
    if not svg_file.exists():
        print(f"WARNING: logo mark not found: {svg_file}", file=sys.stderr)
        return ""
    svg = svg_file.read_text(encoding="utf-8")
    recolor_from = logo.get("mark_recolor_from")
    if recolor_from:
        ink = brand["colors"].get("ink", "#0D0D0D")
        svg = svg.replace(recolor_from, ink).replace(recolor_from.upper(), ink)
    return svg


def attach_screenshots(analysis: dict, shots_dir: str) -> int:
    """Embed a homepage screenshot (base64 data URI) into each competitor that has
    a matching <slug>.png in shots_dir. Returns how many were attached."""
    directory = _resolve(shots_dir)
    attached = 0
    for competitor in analysis.get("competitors", []):
        url = competitor.get("url", "")
        if not url:
            continue
        shot = directory / f"{slugify(url)}.png"
        if shot.exists():
            b64 = base64.b64encode(shot.read_bytes()).decode("ascii")
            competitor["screenshot"] = f"data:image/png;base64,{b64}"
            attached += 1
    return attached


def md_inline(value) -> Markup:
    """Escape HTML, then render simple inline markdown the model sometimes emits
    (**bold**, *italic*) so it doesn't show up as literal asterisks in the PDF."""
    text = str(escape(value if value is not None else ""))
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)", r"<em>\1</em>", text)
    return Markup(text)


def render_html(analysis: dict, brand: dict) -> str:
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        autoescape=select_autoescape(["html", "xml"]),
    )
    env.filters["md_inline"] = md_inline
    template = env.get_template(TEMPLATE_NAME)
    return template.render(
        data=analysis,
        business_name=analysis.get("business", {}).get("name") or brand.get("name", "Our Business"),
        tagline=brand.get("tagline", ""),
        font_face_css=build_font_face_css(brand["fonts"]),
        css_vars=build_css_vars(brand),
        logo_svg=build_logo_svg(brand),
    )


def html_to_pdf(html: str, output: Path) -> None:
    from playwright.sync_api import sync_playwright

    output.parent.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.set_content(html, wait_until="networkidle")
        page.pdf(
            path=str(output),
            prefer_css_page_size=True,  # honor @page (size + full-bleed cover)
            print_background=True,
        )
        browser.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Render a branded PDF competitor report.")
    parser.add_argument("--analysis", required=True, help="Path to analysis JSON (analyze_competitors.py output).")
    parser.add_argument("--brand", default="brand/brand_kit.json", help="Path to brand kit JSON.")
    parser.add_argument("--output", required=True, help="Output PDF path (e.g. reports/report.pdf).")
    parser.add_argument("--shots-dir", help="Dir of <slug>.png homepage screenshots to embed per competitor.")
    parser.add_argument("--keep-html", action="store_true", help="Also write the rendered HTML next to the PDF.")
    args = parser.parse_args()

    analysis = json.loads(_resolve(args.analysis).read_text(encoding="utf-8"))
    brand = json.loads(_resolve(args.brand).read_text(encoding="utf-8"))

    if args.shots_dir:
        n = attach_screenshots(analysis, args.shots_dir)
        print(f"Embedded {n} competitor screenshot(s).")

    html = render_html(analysis, brand)
    output = _resolve(args.output)

    if args.keep_html:
        html_path = output.with_suffix(".html")
        html_path.parent.mkdir(parents=True, exist_ok=True)
        html_path.write_text(html, encoding="utf-8")
        print(f"Wrote HTML to {html_path}")

    html_to_pdf(html, output)
    print(f"Rendered branded PDF to {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
