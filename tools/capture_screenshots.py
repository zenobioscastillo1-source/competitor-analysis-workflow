"""Capture homepage screenshots of competitors for the branded report.

For each competitor URL, loads the page in headless Chromium and saves a viewport
screenshot as <slug>.png in the output dir. render_pdf_report.py --shots-dir embeds
these as a thumbnail in each competitor card. Failures are per-site (one bad URL
won't abort the batch).

Usage:
    python tools/capture_screenshots.py --competitors .tmp/competitors.json \
        --output-dir .tmp/shots
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from config import tmp_path
from util import slugify


def capture_all(urls: list[str], out_dir: Path, width: int = 1280, height: int = 820) -> dict:
    from playwright.sync_api import sync_playwright

    out_dir.mkdir(parents=True, exist_ok=True)
    saved: dict[str, str] = {}
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for url in urls:
            path = out_dir / f"{slugify(url)}.png"
            page = browser.new_page(viewport={"width": width, "height": height})
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=25000)
                page.wait_for_timeout(2500)  # let above-the-fold content settle
                page.screenshot(path=str(path))
                saved[url] = str(path)
                print(f"shot {url} -> {path.name}")
            except Exception as exc:  # per-site resilience; never abort the batch
                print(f"WARNING: screenshot failed for {url}: {exc}", file=sys.stderr)
            finally:
                page.close()
        browser.close()
    return saved


def main() -> int:
    parser = argparse.ArgumentParser(description="Capture competitor homepage screenshots via Chromium.")
    parser.add_argument("--competitors", required=True, help="JSON list with a 'url' per competitor.")
    parser.add_argument("--output-dir", default=str(tmp_path("shots")), help="Where to save <slug>.png files.")
    args = parser.parse_args()

    items = json.loads(Path(args.competitors).read_text(encoding="utf-8"))
    urls = [c["url"] for c in items if isinstance(c, dict) and c.get("url")]
    if not urls:
        print("ERROR: no urls found in competitors file.", file=sys.stderr)
        return 1

    saved = capture_all(urls, Path(args.output_dir))
    print(f"\nCaptured {len(saved)}/{len(urls)} screenshots in {args.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
