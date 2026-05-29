"""Summarize text using the Google Gemini API.

Usage:
    python tools/summarize.py --input .tmp/competitor.json
    python tools/summarize.py --input notes.txt --instructions "Pull out pricing only"

If --input is a JSON file with a "text" field (e.g. scrape_single_site.py
output), that field is summarized. Reads GEMINI_API_KEY and GEMINI_MODEL from
.env. Get a free key at https://aistudio.google.com/apikey
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from google import genai
from google.genai import errors as genai_errors

from config import get_env

DEFAULT_MODEL = "gemini-2.5-flash"
# Tried in order if the configured model is rate-limited / overloaded.
FALLBACK_MODELS = ["gemini-flash-latest", "gemini-2.5-flash-lite"]
TRANSIENT_STATUS = {429, 500, 502, 503, 504}
MAX_ATTEMPTS = 3
DEFAULT_INSTRUCTIONS = (
    "Summarize the following competitor web content for a brand-overhaul "
    "research report. Capture positioning, key messaging, products/services, "
    "pricing signals, and notable differentiators. Use concise bullet points."
)
MAX_INPUT_CHARS = 100_000


def load_text(input_path: str | None) -> str:
    if not input_path:
        return sys.stdin.read()
    raw = Path(input_path).read_text(encoding="utf-8")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return raw
    if isinstance(data, dict) and isinstance(data.get("text"), str):
        return data["text"]
    return raw


def summarize(text: str, instructions: str) -> str:
    client = genai.Client(api_key=get_env("GEMINI_API_KEY", required=True))
    prompt = f"{instructions}\n\n---\n\n{text[:MAX_INPUT_CHARS]}"
    primary = get_env("GEMINI_MODEL") or DEFAULT_MODEL
    models = list(dict.fromkeys([primary, *FALLBACK_MODELS]))
    last_exc: Exception | None = None

    for model in models:
        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                return client.models.generate_content(model=model, contents=prompt).text
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


def main() -> int:
    parser = argparse.ArgumentParser(description="Summarize text with Gemini.")
    parser.add_argument("--input", help="Path to a .txt or .json file (uses 'text' field if JSON).")
    parser.add_argument("--instructions", default=DEFAULT_INSTRUCTIONS)
    parser.add_argument("--output", help="Optional path to save the summary.")
    args = parser.parse_args()

    text = load_text(args.input)
    if not text.strip():
        print("ERROR: no input text provided.", file=sys.stderr)
        return 1

    summary = summarize(text, args.instructions)
    if args.output:
        Path(args.output).write_text(summary, encoding="utf-8")
        print(f"Saved summary to {args.output}")
    else:
        print(summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
