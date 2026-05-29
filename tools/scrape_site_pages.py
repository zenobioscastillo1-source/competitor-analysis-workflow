"""Scrape a competitor's homepage PLUS its key sub-pages (pricing, about, product…)
and combine them into one document, for a richer per-competitor summary.

A deeper alternative to scrape_single_site.py: it follows same-domain links whose
path looks important (pricing/about/features/…), scrapes up to --max-pages of them,
and concatenates everything under section headers. Output is the SAME JSON shape
(url/title/text/links), so summarize.py consumes it unchanged.

Usage:
    python tools/scrape_site_pages.py https://example.com --output example.json
    python tools/scrape_site_pages.py https://example.com --max-pages 5
"""
from __future__ import annotations

import argparse
import json
import sys
from urllib.parse import urljoin, urlparse

import requests
from config import tmp_path
from scrape_single_site import scrape

KEY_KEYWORDS = (
    "pricing", "price", "plans", "about", "product", "features",
    "solutions", "services", "how-it-works", "platform", "use-cases",
)


def select_key_pages(base_url: str, links: list[str], max_pages: int = 4) -> list[str]:
    """Pick same-domain sub-page URLs whose path looks 'key' (pricing/about/...)."""
    base_host = urlparse(base_url).netloc.lower()
    base_norm = base_url.rstrip("/")
    seen: set[str] = set()
    picked: list[str] = []
    for href in links:
        if not href or href.startswith(("mailto:", "tel:", "javascript:", "#")):
            continue
        absu = urljoin(base_url, href.split("#")[0])
        pu = urlparse(absu)
        if pu.scheme not in ("http", "https") or pu.netloc.lower() != base_host:
            continue
        path = pu.path.rstrip("/").lower()
        if not path or absu.rstrip("/") == base_norm:
            continue  # skip the homepage itself
        if any(k in path for k in KEY_KEYWORDS) and absu not in seen:
            seen.add(absu)
            picked.append(absu)
        if len(picked) >= max_pages:
            break
    return picked


def scrape_pages(base_url: str, max_pages: int = 4) -> dict:
    home = scrape(base_url)
    sections = [f"## {base_url}\n{home.get('text', '')}"]
    pages = [base_url]
    for url in select_key_pages(base_url, home.get("links", []), max_pages):
        try:
            sub = scrape(url)
        except requests.RequestException as exc:
            print(f"WARNING: skipping {url}: {exc}", file=sys.stderr)
            continue
        sections.append(f"## {url}\n{sub.get('text', '')}")
        pages.append(url)
    return {
        "url": base_url,
        "status_code": home.get("status_code", 200),
        "title": home.get("title", ""),
        "text": "\n\n".join(sections),
        "links": home.get("links", []),
        "pages_scraped": pages,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Scrape a homepage + its key sub-pages into one document.")
    parser.add_argument("url")
    parser.add_argument("--max-pages", type=int, default=4, help="Max sub-pages beyond the homepage (default 4).")
    parser.add_argument("--output", help="Filename to save JSON under .tmp/ (optional).")
    args = parser.parse_args()

    try:
        result = scrape_pages(args.url, args.max_pages)
    except requests.RequestException as exc:
        print(f"ERROR: failed to fetch {args.url}: {exc}", file=sys.stderr)
        return 1

    if args.output:
        path = tmp_path(args.output)
        path.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"Scraped {len(result['pages_scraped'])} pages ({len(result['text'])} chars) -> {path}")
    else:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
