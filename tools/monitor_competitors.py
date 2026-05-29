"""Weekly market watch: re-scrape a competitor watchlist and alert on change.

Re-scrapes each URL in the watchlist, compares it against a stored baseline in
monitor/state/ (durable — NOT .tmp/, which is disposable), and only reports
*meaningful* changes: a different page title, changed pricing/number tokens, or
a substantial shift in body text. Trivial whitespace edits are ignored to keep
alerts low-noise.

On a meaningful change it can append a dated row to the Google Sheet tracker and
post a Slack alert. The first run for any URL just seeds the baseline (no alert).

Usage:
    # Seed baselines on first run (no alerts expected):
    python tools/monitor_competitors.py --watchlist .tmp/competitors.json

    # Weekly run that records changes to the tracker Sheet and pings Slack:
    python tools/monitor_competitors.py --watchlist .tmp/competitors.json \
        --spreadsheet-id <ID> --sheet "Changes" --slack

--watchlist is a JSON list of objects with at least "url" (and ideally "name").
A competitors.json from the report workflow works directly.
"""
from __future__ import annotations

import argparse
import datetime as dt
import difflib
import json
import re
import sys
from pathlib import Path

import requests
from config import PROJECT_ROOT
from scrape_single_site import scrape

STATE_DIR = PROJECT_ROOT / "monitor" / "state"
PRICE_RE = re.compile(r"(?:[$£€]\s?\d[\d,]*(?:\.\d+)?|\b\d+(?:\.\d+)?\s?%)")
# Below this body-text similarity (0-1), a change is considered meaningful.
SIMILARITY_THRESHOLD = 0.97


def slugify(url: str) -> str:
    s = re.sub(r"^https?://", "", url.strip().lower())
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s[:80] or "page"


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def price_tokens(text: str) -> list[str]:
    return sorted(set(PRICE_RE.findall(text or "")))


def diff_against_baseline(old: dict, new: dict) -> list[str]:
    """Return a list of human-readable change descriptions (empty = no meaningful change)."""
    changes: list[str] = []

    if normalize(old.get("title", "")) != normalize(new.get("title", "")):
        changes.append(f"Title changed: \"{old.get('title','')}\" -> \"{new.get('title','')}\"")

    old_prices, new_prices = set(old.get("prices", [])), set(new.get("prices", []))
    if old_prices != new_prices:
        added = sorted(new_prices - old_prices)
        removed = sorted(old_prices - new_prices)
        parts = []
        if added:
            parts.append("added " + ", ".join(added))
        if removed:
            parts.append("removed " + ", ".join(removed))
        changes.append("Pricing/numbers changed: " + "; ".join(parts))

    ratio = difflib.SequenceMatcher(
        None, normalize(old.get("text", "")), normalize(new.get("text", ""))
    ).ratio()
    if ratio < SIMILARITY_THRESHOLD:
        changes.append(f"Body content changed (~{round((1 - ratio) * 100)}% different)")

    return changes


def load_state(slug: str) -> dict | None:
    path = STATE_DIR / f"{slug}.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return None


def save_state(slug: str, snapshot: dict) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    (STATE_DIR / f"{slug}.json").write_text(
        json.dumps(snapshot, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def snapshot_of(name: str, scraped: dict) -> dict:
    return {
        "name": name,
        "url": scraped["url"],
        "title": scraped.get("title", ""),
        "text": scraped.get("text", ""),
        "prices": price_tokens(scraped.get("text", "")),
        "fetched_at": dt.datetime.now().isoformat(timespec="seconds"),
    }


CHANGES_HEADER = ["Date", "Competitor", "URL", "Change detected"]


def ensure_sheet(service, spreadsheet_id: str, sheet: str, header: list[str]) -> None:
    """Create the target tab with a header row if it doesn't already exist."""
    meta = service.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
    titles = [s["properties"]["title"] for s in meta.get("sheets", [])]
    if sheet in titles:
        return
    service.spreadsheets().batchUpdate(
        spreadsheetId=spreadsheet_id,
        body={"requests": [{"addSheet": {"properties": {"title": sheet}}}]},
    ).execute()
    service.spreadsheets().values().update(
        spreadsheetId=spreadsheet_id,
        range=f"{sheet}!A1",
        valueInputOption="USER_ENTERED",
        body={"values": [header]},
    ).execute()


def push_rows_to_sheet(spreadsheet_id: str, sheet: str, rows: list[list[str]]) -> None:
    # Imported lazily so the tool runs for scrape-only/seed use without Google deps configured.
    from googleapiclient.discovery import build
    from push_to_google_sheet import append_rows, get_credentials

    service = build("sheets", "v4", credentials=get_credentials())
    ensure_sheet(service, spreadsheet_id, sheet, CHANGES_HEADER)
    append_rows(service, spreadsheet_id, f"{sheet}!A1", rows)


def send_slack(text: str, channel: str | None) -> None:
    from notify_slack import post_message

    post_message(text, channel)


def main() -> int:
    parser = argparse.ArgumentParser(description="Re-scrape a watchlist and alert on meaningful change.")
    parser.add_argument("--watchlist", required=True, help="JSON list of {name,url} to monitor.")
    parser.add_argument("--spreadsheet-id", help="Tracker Sheet to append change rows to.")
    parser.add_argument("--sheet", default="Changes", help="Tab name for change rows (default: Changes).")
    parser.add_argument("--slack", action="store_true", help="Post a Slack alert when changes are found.")
    parser.add_argument("--slack-channel", help="Override SLACK_DEFAULT_CHANNEL.")
    parser.add_argument("--seed", action="store_true", help="Force re-seed all baselines (no alerts).")
    args = parser.parse_args()

    watchlist = json.loads(Path(args.watchlist).read_text(encoding="utf-8"))
    if not isinstance(watchlist, list) or not watchlist:
        print(f"ERROR: {args.watchlist} must be a non-empty JSON list.", file=sys.stderr)
        return 1

    today = dt.date.today().isoformat()
    change_rows: list[list[str]] = []
    seeded, unchanged, failed = 0, 0, 0

    for entry in watchlist:
        url = entry.get("url")
        if not url:
            continue
        name = entry.get("name", url)
        slug = slugify(url)

        try:
            scraped = scrape(url)
        except requests.RequestException as exc:
            print(f"FAILED  {name}: {exc}", file=sys.stderr)
            failed += 1
            continue

        new_snap = snapshot_of(name, scraped)
        baseline = None if args.seed else load_state(slug)

        if baseline is None:
            save_state(slug, new_snap)
            print(f"SEEDED  {name}")
            seeded += 1
            continue

        changes = diff_against_baseline(baseline, new_snap)
        if changes:
            detail = " | ".join(changes)
            print(f"CHANGED {name}: {detail}")
            change_rows.append([today, name, url, detail])
            save_state(slug, new_snap)  # advance baseline so the same change isn't re-reported
        else:
            print(f"OK      {name}")
            unchanged += 1

    print(f"\nSummary: {len(change_rows)} changed, {unchanged} unchanged, {seeded} seeded, {failed} failed.")

    if change_rows and args.spreadsheet_id:
        push_rows_to_sheet(args.spreadsheet_id, args.sheet, change_rows)
        print(f"Appended {len(change_rows)} change row(s) to the tracker Sheet.")

    if change_rows and args.slack:
        lines = "\n".join(f"• {r[1]}: {r[3]}" for r in change_rows)
        send_slack(f"Nerumi competitor watch — {len(change_rows)} change(s) on {today}:\n{lines}", args.slack_channel)
        print("Posted Slack alert.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
