# Branded Competitor Analysis & Market-Monitoring Workflow

An agentic workflow that turns a business profile + a list of competitor URLs into
a **fully brand-styled PDF competitive analysis**, plus a **living Google Sheet
tracker** and a **weekly change-monitoring job** that flags when a competitor moves.

Built on a **WAT architecture (Workflows · Agents · Tools)**: plain-language SOPs
describe *what* to do, an agent orchestrates, and small deterministic Python tools
do the execution. Probabilistic reasoning stays in the agent; repeatable work stays
in tested scripts.

👉 **[See a sample report → `docs/sample-report.pdf`](docs/sample-report.pdf)** — six
competitors analyzed, brand-styled cover, per-competitor profiles, market themes, a
SWOT, and prioritized recommendations.

> The sample analyzes [Nerumi](https://nerumi.io) (an AI-integrations studio) against
> six real competitors, and demonstrates the branded-output pipeline end to end.

---

## What it produces

| Deliverable | Description |
|-------------|-------------|
| **Branded PDF** | A multi-section report rendered from an HTML/CSS template via headless Chromium, with brand colors, logo, and typography embedded. |
| **Google Sheet tracker** | One row per competitor (positioning, pricing, strengths, exposure) — the living record. |
| **Weekly market watch** | Re-scrapes the watchlist, diffs against stored baselines, and logs only *meaningful* changes (pricing/number shifts, title changes, substantial copy changes) to a `Changes` tab. |

## Architecture

```
Inputs                          Tools (deterministic Python)          Output
──────────────────────────────────────────────────────────────────────────────
business profile  ┐
competitor URLs   ├─► scrape_single_site.py ─► clean text + links
brand kit         ┘            │
                     summarize.py (Gemini) ─► per-competitor summary
                                   │
                  analyze_competitors.py (Gemini) ─► structured analysis.json
                              │                            │
              render_pdf_report.py ◄──────────────────────┤
              (Jinja2 + Chromium, fonts/logo embedded) ─► branded PDF
                                                           │
                  push_to_google_sheet.py ◄────────────────┘  ─► Sheet tracker
Weekly:  monitor_competitors.py ─► diff vs baselines ─► Sheet "Changes" tab
                                                    (+ optional Slack alert)
```

## Tools

| Tool | Purpose |
|------|---------|
| `tools/scrape_single_site.py` | Fetch a URL → clean text + links |
| `tools/summarize.py` | Per-competitor summary via Google Gemini (retry + model fallback) |
| `tools/analyze_competitors.py` | Profile + summaries → structured JSON (SWOT, opportunities, recommendations) |
| `tools/render_pdf_report.py` | Analysis + brand kit → self-contained branded PDF |
| `tools/push_to_google_sheet.py` | Create / append the Google Sheet tracker |
| `tools/monitor_competitors.py` | Re-scrape, diff vs baseline, log changes + optional Slack |
| `tools/notify_slack.py` | Post a Slack message |

## Quick start

```bash
python -m venv .venv && .venv/Scripts/activate      # Windows; use source on macOS/Linux
pip install -r requirements.txt
playwright install chromium                          # for PDF rendering
cp .env.example .env                                 # then add your GEMINI_API_KEY
```

Then run the pipeline (see [`workflows/branded_competitor_report.md`](workflows/branded_competitor_report.md)
for the full SOP):

```bash
# 1. scrape each competitor   2. summarize   3. assemble .tmp/competitors.json
python tools/scrape_single_site.py https://example.com --output example.json
python tools/summarize.py --input .tmp/example.json --output .tmp/example.summary.txt

# 4. analyze   5. render the branded PDF
python tools/analyze_competitors.py --profile inputs/business_profile.md \
    --competitors .tmp/competitors.json --output .tmp/analysis.json
python tools/render_pdf_report.py --analysis .tmp/analysis.json \
    --output reports/report.pdf
```

## Tech

Python · Google Gemini (`google-genai`) · Playwright/Chromium · Jinja2 ·
BeautifulSoup · Google Sheets API · Slack SDK.

## Notes

- **Brand kit** is data-driven: `brand/brand_kit.json` defines colors, fonts, and the
  logo; the renderer base64-embeds fonts + logo so the PDF is fully self-contained.
- **Resilience**: the Gemini tools retry transient errors and fall back across models.
- **Configuration**: API keys and OAuth live in `.env` / local credential files
  (gitignored) — see `.env.example`.

Fonts in `brand-assets/fonts/` are redistributed under their respective licenses
(General Sans — Indian Type Foundry Free Font License; Lora — SIL Open Font License).
