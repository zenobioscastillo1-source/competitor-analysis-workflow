"""Scrape a page via the Firecrawl API — the escalation for sites that block the
plain requests+BeautifulSoup scraper or need full JS rendering / anti-bot handling.

Drop-in replacement for scrape_single_site.py: it writes the SAME JSON shape
({url, status_code, title, text, links}) so tools/summarize.py consumes it
unchanged. Use this only when scrape_single_site.py returns sparse text or gets
blocked (403/429/Cloudflare) — it calls a paid hosted API (free tier available).

Usage:
    python tools/firecrawl_scrape.py https://example.com
    python tools/firecrawl_scrape.py https://example.com --output competitor.json

Reads FIRECRAWL_API_KEY (and optional FIRECRAWL_API_URL) from .env. Get a key at
https://www.firecrawl.dev. Targets the v1 /scrape endpoint.
"""
from __future__ import annotations

import argparse
import json
import sys

import requests
from config import get_env, tmp_path

DEFAULT_API_URL = "https://api.firecrawl.dev"


def scrape(url: str, timeout: int = 60) -> dict:
    api_key = get_env("FIRECRAWL_API_KEY", required=True)
    base = (get_env("FIRECRAWL_API_URL") or DEFAULT_API_URL).rstrip("/")
    resp = requests.post(
        f"{base}/v1/scrape",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={"url": url, "formats": ["markdown", "links"]},
        timeout=timeout,
    )
    resp.raise_for_status()
    payload = resp.json()
    if payload.get("success") is False:
        raise RuntimeError(payload.get("error") or "Firecrawl returned success=false")

    # Defensive parse — tolerate minor response-shape differences across versions.
    data = payload.get("data", payload)
    metadata = data.get("metadata", {}) or {}
    return {
        "url": metadata.get("sourceURL") or url,
        "status_code": metadata.get("statusCode", resp.status_code),
        "title": metadata.get("title") or metadata.get("ogTitle") or "",
        "text": data.get("markdown") or data.get("content") or "",
        "links": data.get("links", []) or [],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Scrape a page via the Firecrawl API.")
    parser.add_argument("url")
    parser.add_argument("--output", help="Filename to save JSON under .tmp/ (optional).")
    args = parser.parse_args()

    try:
        result = scrape(args.url)
    except (requests.RequestException, RuntimeError) as exc:
        print(f"ERROR: Firecrawl failed to fetch {args.url}: {exc}", file=sys.stderr)
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
