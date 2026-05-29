"""Scrape a single web page and extract clean, readable text.

Usage:
    python tools/scrape_single_site.py https://example.com
    python tools/scrape_single_site.py https://example.com --output competitor.json

Without --output the result JSON is printed to stdout. With --output it is
saved under .tmp/. For JavaScript-heavy sites that return little text,
switch to Playwright (see requirements.txt).
"""
from __future__ import annotations

import argparse
import json
import sys

import requests
from bs4 import BeautifulSoup
from config import get_env, tmp_path

DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)


def scrape(url: str, timeout: int = 20) -> dict:
    headers = {"User-Agent": get_env("SCRAPER_USER_AGENT") or DEFAULT_UA}
    resp = requests.get(url, headers=headers, timeout=timeout)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "lxml")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()

    title = soup.title.string.strip() if soup.title and soup.title.string else ""
    text = "\n".join(
        line.strip() for line in soup.get_text("\n").splitlines() if line.strip()
    )
    links = sorted({a["href"] for a in soup.find_all("a", href=True)})

    return {
        "url": url,
        "status_code": resp.status_code,
        "title": title,
        "text": text,
        "links": links,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Scrape a single web page to clean text.")
    parser.add_argument("url")
    parser.add_argument("--output", help="Filename to save JSON under .tmp/ (optional).")
    args = parser.parse_args()

    try:
        result = scrape(args.url)
    except requests.RequestException as exc:
        print(f"ERROR: failed to fetch {args.url}: {exc}", file=sys.stderr)
        return 1

    if args.output:
        path = tmp_path(args.output)
        path.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"Saved {len(result['text'])} chars of text to {path}")
    else:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
