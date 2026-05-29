"""Turn the monitor's history logs into a trend view.

Reads the append-only weekly snapshots that monitor_competitors.py writes to
monitor/history/<slug>.jsonl and reports how each competitor has evolved over
time: how long it's been tracked, how many meaningful changes were detected,
how pricing moved, whether the title shifted, and the most recent change.

It prints a per-competitor summary, and (optionally) (re)writes a "History" tab
on the tracker Sheet with the full timeline so the living tracker shows trends,
not just the latest snapshot. Pure read of local history — never re-scrapes.

Usage:
    # Console summary only (offline):
    python tools/build_trends.py

    # Also (re)write the Sheet "History" tab with the full timeline:
    python tools/build_trends.py --spreadsheet-id <ID>

    # Also write a markdown digest:
    python tools/build_trends.py --output .tmp/trends.md
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from config import PROJECT_ROOT

HISTORY_DIR = PROJECT_ROOT / "monitor" / "history"
HISTORY_HEADER = ["Date", "Competitor", "URL", "Title", "Pricing", "Body length", "Status", "Detail"]


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def load_history(history_dir: Path = HISTORY_DIR) -> dict[str, list[dict]]:
    """Read every <slug>.jsonl into {slug: [entries...]} sorted by date."""
    history: dict[str, list[dict]] = {}
    if not history_dir.exists():
        return history
    for path in sorted(history_dir.glob("*.jsonl")):
        entries: list[dict] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue  # skip a corrupt line rather than aborting the whole report
        if entries:
            entries.sort(key=lambda e: e.get("date", ""))
            history[path.stem] = entries
    return history


def summarize_competitor(entries: list[dict]) -> dict:
    """Reduce one competitor's snapshot timeline to a trend summary (pure)."""
    first, last = entries[0], entries[-1]
    changes = [e for e in entries if e.get("status") == "changed"]
    first_prices = sorted(first.get("prices", []))
    last_prices = sorted(last.get("prices", []))
    return {
        "name": last.get("name") or first.get("name") or "",
        "url": last.get("url") or first.get("url") or "",
        "snapshots": len(entries),
        "first_date": first.get("date", ""),
        "last_date": last.get("date", ""),
        "changes": len(changes),
        "change_dates": [e.get("date", "") for e in changes],
        "last_change": (changes[-1].get("date", ""), changes[-1].get("detail", "")) if changes else None,
        "pricing_from": first_prices,
        "pricing_to": last_prices,
        "pricing_changed": first_prices != last_prices,
        "title_from": first.get("title", ""),
        "title_to": last.get("title", ""),
        "title_changed": _norm(first.get("title", "")) != _norm(last.get("title", "")),
    }


def _fmt_prices(prices: list[str]) -> str:
    return ", ".join(prices) if prices else "—"


def format_summary(summaries: list[dict]) -> str:
    if not summaries:
        return (
            "No history yet. Run the monitor at least once to seed it:\n"
            "    python tools/monitor_competitors.py --watchlist monitor/watchlist.json"
        )
    total_changes = sum(s["changes"] for s in summaries)
    lines = [
        f"Competitor trends — {len(summaries)} tracked, {total_changes} change(s) on record",
        "",
    ]
    for s in sorted(summaries, key=lambda x: x["name"].lower()):
        span = s["first_date"] if s["first_date"] == s["last_date"] else f"{s['first_date']} → {s['last_date']}"
        lines.append(f"{s['name']} — {s['snapshots']} snapshot(s), {span}")
        if s["changes"]:
            lines.append(f"    changes: {s['changes']} ({', '.join(s['change_dates'])})")
        else:
            lines.append("    changes: 0 (stable)")
        price_tag = "changed" if s["pricing_changed"] else "stable"
        lines.append(f"    pricing: {_fmt_prices(s['pricing_from'])} → {_fmt_prices(s['pricing_to'])}  [{price_tag}]")
        if s["title_changed"]:
            lines.append(f"    title:   \"{s['title_from']}\" → \"{s['title_to']}\"")
        if s["last_change"]:
            lines.append(f"    last change {s['last_change'][0]}: {s['last_change'][1]}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def history_rows(history: dict[str, list[dict]]) -> list[list[str]]:
    """Flatten all snapshots into Sheet rows, sorted by date then competitor."""
    rows: list[list[str]] = []
    for entries in history.values():
        for e in entries:
            rows.append([
                e.get("date", ""),
                e.get("name", ""),
                e.get("url", ""),
                e.get("title", ""),
                ", ".join(e.get("prices", [])),
                str(e.get("body_len", "")),
                e.get("status", ""),
                e.get("detail", ""),
            ])
    rows.sort(key=lambda r: (r[0], r[1].lower()))
    return rows


def write_history_sheet(spreadsheet_id: str, sheet: str, rows: list[list[str]]) -> int:
    """(Re)write the History tab from the full local timeline (idempotent)."""
    from googleapiclient.discovery import build
    from monitor_competitors import ensure_sheet
    from push_to_google_sheet import get_credentials

    service = build("sheets", "v4", credentials=get_credentials())
    ensure_sheet(service, spreadsheet_id, sheet, HISTORY_HEADER)
    service.spreadsheets().values().clear(
        spreadsheetId=spreadsheet_id, range=f"{sheet}!A:Z"
    ).execute()
    service.spreadsheets().values().update(
        spreadsheetId=spreadsheet_id,
        range=f"{sheet}!A1",
        valueInputOption="USER_ENTERED",
        body={"values": [HISTORY_HEADER] + rows},
    ).execute()
    return len(rows)


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # so → / — render on the Windows console

    parser = argparse.ArgumentParser(description="Summarize competitor history into a trend view.")
    parser.add_argument("--history-dir", help="Override the history directory (default monitor/history).")
    parser.add_argument("--spreadsheet-id", help="(Re)write a History tab on this tracker Sheet.")
    parser.add_argument("--sheet", default="History", help="Tab name for the timeline (default: History).")
    parser.add_argument("--output", help="Also write the console summary to this markdown file.")
    args = parser.parse_args()

    history_dir = Path(args.history_dir) if args.history_dir else HISTORY_DIR
    history = load_history(history_dir)
    summaries = [summarize_competitor(entries) for entries in history.values()]
    summary_text = format_summary(summaries)
    print(summary_text)

    if args.output:
        Path(args.output).write_text(summary_text, encoding="utf-8")
        print(f"Wrote trend summary -> {args.output}")

    if args.spreadsheet_id:
        if not history:
            print("No history to write to the Sheet yet.", file=sys.stderr)
            return 0
        n = write_history_sheet(args.spreadsheet_id, args.sheet, history_rows(history))
        print(f"Wrote {n} history row(s) to the '{args.sheet}' tab.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
