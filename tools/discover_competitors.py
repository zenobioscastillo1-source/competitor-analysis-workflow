"""Discover competitors from a business profile using Gemini + Google Search.

The optional front-end to the workflow: instead of supplying competitor URLs by
hand, describe your business and let a grounded Gemini search propose a ranked
candidate list with live URLs and a one-line rationale each. Review the list,
then feed the ones you want into the normal scrape -> summarize -> analyze pipeline.

Usage:
    python tools/discover_competitors.py --profile inputs/business_profile.md
    python tools/discover_competitors.py --profile inputs/business_profile.md \
        --count 10 --output .tmp/discovered.json

Reads GEMINI_API_KEY / GEMINI_MODEL from .env. Uses Google Search grounding so the
results are real, currently-operating companies rather than the model's guesses.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from config import get_env, tmp_path
from google import genai
from google.genai import errors as genai_errors
from google.genai import types

DEFAULT_MODEL = "gemini-2.5-flash"
FALLBACK_MODELS = ["gemini-flash-latest", "gemini-2.5-flash-lite"]
TRANSIENT_STATUS = {429, 500, 502, 503, 504}
MAX_ATTEMPTS = 3


def build_prompt(profile: str, count: int) -> str:
    return (
        "You are a competitive-research analyst. Using web search, find the "
        f"{count} most relevant DIRECT competitors for the business described "
        "below — real, currently-operating companies with valid homepage URLs. "
        "Prefer direct competitors (same offering, same buyer) over adjacent "
        "tools or platforms. Avoid duplicates and dead links.\n\n"
        "Return ONLY a JSON array, no prose and no code fences, shaped exactly:\n"
        '[{"name": "Company", "url": "https://...", "why": "one-sentence reason '
        'they compete"}]\n\n'
        f"=== BUSINESS PROFILE ===\n{profile}"
    )


def extract_json_array(raw: str) -> list[dict]:
    raw = (raw or "").strip()
    if raw.startswith("```"):
        raw = raw.split("```", 2)[1]
        if raw.lstrip().lower().startswith("json"):
            raw = raw.lstrip()[4:]
        raw = raw.rsplit("```", 1)[0]
    start, end = raw.find("["), raw.rfind("]")
    if start == -1 or end == -1:
        raise ValueError("No JSON array found in model response.")
    return json.loads(raw[start : end + 1])


def discover(profile: str, count: int) -> list[dict]:
    client = genai.Client(api_key=get_env("GEMINI_API_KEY", required=True))
    primary = get_env("GEMINI_MODEL") or DEFAULT_MODEL
    models = list(dict.fromkeys([primary, *FALLBACK_MODELS]))
    # Google Search grounding can't be combined with JSON response mode, so we
    # ask for JSON in the prompt and parse it leniently.
    config = types.GenerateContentConfig(
        tools=[types.Tool(google_search=types.GoogleSearch())],
        temperature=0.3,
    )
    prompt = build_prompt(profile, count)
    last_exc: Exception | None = None

    for model in models:
        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                resp = client.models.generate_content(model=model, contents=prompt, config=config)
                return normalize(extract_json_array(resp.text))
            except genai_errors.APIError as exc:
                last_exc = exc
                if getattr(exc, "code", None) not in TRANSIENT_STATUS:
                    raise
                wait = 2 ** attempt
                print(f"Transient {exc.code} on {model} (attempt {attempt}/{MAX_ATTEMPTS}); "
                      f"retrying in {wait}s...", file=sys.stderr)
                time.sleep(wait)
        print(f"{model} still unavailable; falling back to next model...", file=sys.stderr)

    raise last_exc  # type: ignore[misc]


def normalize(items: list) -> list[dict]:
    """Keep well-formed entries with an http(s) URL; dedupe by URL."""
    seen, out = set(), []
    for it in items:
        if not isinstance(it, dict):
            continue
        url = str(it.get("url", "")).strip()
        if not url.startswith("http") or url in seen:
            continue
        seen.add(url)
        out.append({
            "name": str(it.get("name", "")).strip() or url,
            "url": url,
            "why": str(it.get("why", "")).strip(),
        })
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="Discover competitors via Gemini + Google Search.")
    parser.add_argument("--profile", required=True, help="Path to the business profile (.md/.txt).")
    parser.add_argument("--count", type=int, default=8, help="How many competitors to find (default 8).")
    parser.add_argument("--output", default=str(tmp_path("discovered.json")), help="Where to write the JSON list.")
    args = parser.parse_args()

    profile = Path(args.profile).read_text(encoding="utf-8").strip()
    if not profile:
        print(f"ERROR: profile at {args.profile} is empty.", file=sys.stderr)
        return 1

    try:
        competitors = discover(profile, args.count)
    except ValueError as exc:
        print(f"ERROR: could not parse competitor list: {exc}", file=sys.stderr)
        return 1

    if not competitors:
        print("No competitors found. Try rephrasing the profile or raising --count.", file=sys.stderr)
        return 1

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(competitors, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"Found {len(competitors)} candidate competitors (review before researching):\n")
    for i, c in enumerate(competitors, 1):
        print(f"{i:>2}. {c['name']}  -  {c['url']}")
        if c["why"]:
            print(f"     {c['why']}")
    print(f"\nWrote {out}. Approve the ones you want, then scrape them with scrape_single_site.py.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
