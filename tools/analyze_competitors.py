"""Turn competitor summaries + your business profile into a structured analysis.

This is the analytical core of the branded competitor workflow. It takes the
per-competitor summaries (produced by summarize.py) plus your business profile
and asks Gemini to return a single structured JSON document covering what each
competitor does well, market themes, where YOU can improve, a SWOT, and
prioritized recommendations. That JSON drives both the branded PDF and the
Google Sheet tracker.

Usage:
    python tools/analyze_competitors.py \
        --profile inputs/business_profile.md \
        --competitors .tmp/competitors.json \
        --output .tmp/analysis.json

--competitors is a JSON file: a list of objects, each with at least
"name", "url", and "summary" (the summary text from summarize.py). Example:
    [
      {"name": "Acme", "url": "https://acme.com", "summary": "- Positioned as..."},
      {"name": "Globex", "url": "https://globex.io", "summary": "- Targets..."}
    ]

Reads GEMINI_API_KEY and GEMINI_MODEL from .env (free key:
https://aistudio.google.com/apikey). Uses the brand name from brand/brand_kit.json
unless --business-name is given.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import time
from pathlib import Path

from config import PROJECT_ROOT, get_env, tmp_path
from google import genai
from google.genai import errors as genai_errors
from google.genai import types

DEFAULT_MODEL = "gemini-2.5-flash"
# Tried in order if the configured model is rate-limited / overloaded. All three
# confirmed available on the free tier; the 2.0 family currently is not.
FALLBACK_MODELS = ["gemini-flash-latest", "gemini-2.5-flash-lite"]
TRANSIENT_STATUS = {429, 500, 502, 503, 504}
MAX_ATTEMPTS = 3
MAX_SUMMARY_CHARS = 12_000  # per competitor, keeps the prompt within free-tier limits

SCHEMA_DESCRIPTION = """Return ONLY a JSON object with exactly this shape:
{
  "business": {"name": string, "summary": string},
  "executive_summary": string,            // 2-4 sentences for the report opener
  "competitors": [
    {
      "name": string,
      "url": string,
      "positioning": string,              // how they present themselves
      "whats_working": [string],          // concrete things succeeding for them
      "weaknesses": [string],             // gaps / where they are exposed
      "pricing": string,                  // pricing signal, or "Not disclosed"
      "key_pages": [string]               // notable pages/sections worth watching
    }
  ],
  "market_themes": [string],              // patterns common across competitors
  "opportunities": [string],              // where OUR business can improve / win
  "swot": {
    "strengths": [string],
    "weaknesses": [string],
    "opportunities": [string],
    "threats": [string]
  },
  "recommendations": [
    {"title": string, "detail": string, "priority": "high"|"medium"|"low"}
  ]
}
All SWOT/opportunity/recommendation content must be about OUR business
(the one in the profile), informed by the competitor evidence. Be specific and
concrete; avoid generic filler. No markdown, no code fences — raw JSON only."""


def load_profile(path: str) -> str:
    text = Path(path).read_text(encoding="utf-8").strip()
    if not text:
        raise SystemExit(f"ERROR: business profile at {path} is empty.")
    return text


def load_competitors(path: str) -> list[dict]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, list) or not data:
        raise SystemExit(f"ERROR: {path} must be a non-empty JSON list of competitors.")
    return data


def brand_name(default: str = "Our Business") -> str:
    kit = PROJECT_ROOT / "brand" / "brand_kit.json"
    if kit.exists():
        try:
            return json.loads(kit.read_text(encoding="utf-8")).get("name", default)
        except (json.JSONDecodeError, OSError):
            pass
    return default


def build_prompt(profile: str, competitors: list[dict], business: str) -> str:
    blocks = []
    for c in competitors:
        summary = str(c.get("summary", "")).strip()[:MAX_SUMMARY_CHARS]
        blocks.append(
            f"### Competitor: {c.get('name', 'Unknown')}\n"
            f"URL: {c.get('url', 'n/a')}\n\n{summary}"
        )
    competitor_text = "\n\n---\n\n".join(blocks)
    return (
        f"You are a competitive-strategy analyst preparing a research report for "
        f"the business '{business}'.\n\n"
        f"=== OUR BUSINESS PROFILE ===\n{profile}\n\n"
        f"=== COMPETITOR RESEARCH ({len(competitors)} competitors) ===\n"
        f"{competitor_text}\n\n"
        f"=== TASK ===\n{SCHEMA_DESCRIPTION}"
    )


def extract_json(raw: str) -> dict:
    raw = raw.strip()
    if raw.startswith("```"):
        # strip ```json ... ``` fences
        raw = raw.split("```", 2)[1]
        if raw.lstrip().lower().startswith("json"):
            raw = raw.lstrip()[4:]
        raw = raw.rsplit("```", 1)[0]
    start, end = raw.find("{"), raw.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("No JSON object found in model response.")
    return json.loads(raw[start : end + 1])


def generate_with_fallback(client, prompt: str):
    """Generate content, retrying transient errors and falling back across models."""
    primary = get_env("GEMINI_MODEL") or DEFAULT_MODEL
    models = list(dict.fromkeys([primary, *FALLBACK_MODELS]))
    config = types.GenerateContentConfig(response_mime_type="application/json", temperature=0.4)
    last_exc: Exception | None = None

    for model in models:
        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                return client.models.generate_content(model=model, contents=prompt, config=config)
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


def analyze(profile: str, competitors: list[dict], business: str) -> dict:
    client = genai.Client(api_key=get_env("GEMINI_API_KEY", required=True))
    response = generate_with_fallback(client, build_prompt(profile, competitors, business))
    result = extract_json(response.text)

    # Fill fields the model may omit so downstream rendering never breaks.
    result.setdefault("business", {})
    result["business"].setdefault("name", business)
    result["generated_date"] = dt.date.today().isoformat()
    result.setdefault("competitors", [])
    result.setdefault("market_themes", [])
    result.setdefault("opportunities", [])
    result.setdefault("swot", {"strengths": [], "weaknesses": [], "opportunities": [], "threats": []})
    result.setdefault("recommendations", [])
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Structured competitor analysis via Gemini.")
    parser.add_argument("--profile", required=True, help="Path to business profile (.md/.txt).")
    parser.add_argument("--competitors", required=True, help="JSON file: list of {name,url,summary}.")
    parser.add_argument("--business-name", help="Override the business name (else brand_kit.json).")
    parser.add_argument("--output", default=str(tmp_path("analysis.json")), help="Where to write analysis JSON.")
    args = parser.parse_args()

    business = args.business_name or brand_name()
    profile = load_profile(args.profile)
    competitors = load_competitors(args.competitors)

    try:
        analysis = analyze(profile, competitors, business)
    except ValueError as exc:
        print(f"ERROR: could not parse model output as JSON: {exc}", file=sys.stderr)
        return 1

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(analysis, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Wrote analysis for {len(analysis['competitors'])} competitors to {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
