# Workflow: Branded Competitor Analysis & Market Monitoring

## Objective
Given a business profile and a list of competitor URLs, research each competitor,
synthesize what's working for them and where **Nerumi** can improve, and deliver a
**branded PDF report** (Nerumi logo, colors, General Sans + Lora typography). Then
maintain a **Google Sheet tracker** and a **weekly market watch** that alerts only
when a competitor meaningfully changes.

This is the full-featured successor to `competitor_research.md` (which is the
simpler scrape→summarize→Sheet subset). Use this one when the deliverable is the
branded PDF + ongoing monitoring.

## Required Inputs
- **Business profile** — `inputs/business_profile.md` (fill it in, or draft it from
  what the user tells you). Drives the "where we can improve" analysis.
- **Competitor URLs** — provided by the user, or auto-discovered from the profile
  with `tools/discover_competitors.py` (step 0). Homepage / pricing / about pages work best.
- **Brand kit** — `brand/brand_kit.json` (already configured for Nerumi: colors from
  the v4 design system, General Sans = Voice A, Lora = Voice B, mark = Nerumi_Logo.svg).
- **Gemini API key** — `GEMINI_API_KEY` in `.env` (free tier; summarize + analyze).
- **Google OAuth** — `credentials.json` for the Sheet tracker (first run opens a browser).
- **Slack** *(optional)* — `SLACK_BOT_TOKEN` for change alerts.

## Tools
| Step | Tool | Purpose |
|------|------|---------|
| 0 | `tools/discover_competitors.py` | *(optional)* discover competitors from the profile via Gemini + Google Search |
| 1 | `tools/scrape_single_site.py` | Fetch each competitor URL → clean text + links |
| 1a | `tools/scrape_site_pages.py` | *(optional)* deeper scrape: homepage + key sub-pages (pricing/about/…) into one doc |
| 1b | `tools/firecrawl_scrape.py` | *(optional)* escalation scraper for blocked / JS-heavy sites — same output shape |
| 2 | `tools/summarize.py` | Per-competitor bullet summary via Gemini |
| 3 | `tools/analyze_competitors.py` | Profile + summaries → structured `analysis.json` |
| 4 | `tools/render_pdf_report.py` | `analysis.json` + brand kit → branded PDF |
| 4a | `tools/capture_screenshots.py` | *(optional)* capture competitor homepage screenshots to embed in the PDF |
| 5 | `tools/push_to_google_sheet.py` | Create / append the living tracker Sheet |
| 6 | `tools/monitor_competitors.py` | Weekly re-scrape, diff vs baseline, alert on change, record a dated history snapshot |
| 6a | `tools/build_trends.py` | Summarize the history log into trends + (re)write the Sheet "History" tab |
| 7 | `tools/notify_slack.py` | (Optional) completion / change notifications |

## Procedure — One-time report
0. **(Optional) Discover competitors** instead of supplying URLs by hand:
   `python tools/discover_competitors.py --profile inputs/business_profile.md --count 8`
   Review the printed candidates (also written to `.tmp/discovered.json`) and keep the
   ones worth researching; their URLs feed step 2.
1. **Confirm inputs.** Ensure `inputs/business_profile.md` is filled and gather the
   competitor URL list.
2. **Scrape each URL** into `.tmp/`:
   `python tools/scrape_single_site.py <url> --output <slug>.json`
   - Sparse text usually means a JS-rendered site. The render dependency (Playwright
     + Chromium) is already installed — escalate to a headless-browser fetch rather
     than silently skipping. Don't drop a competitor without noting it.
   - Still blocked (Cloudflare/anti-bot, 403/429)? Escalate to Firecrawl:
     `python tools/firecrawl_scrape.py <url> --output <slug>.json` (needs
     `FIRECRAWL_API_KEY` in `.env`). Same output shape, so the rest of the pipeline
     is unchanged.
   - For deeper input, `python tools/scrape_site_pages.py <url> --output <slug>.json`
     pulls the homepage + key sub-pages (pricing/about/…) into one document.
3. **Summarize each scrape:**
   `python tools/summarize.py --input .tmp/<slug>.json --output .tmp/<slug>.summary.txt`
4. **Assemble `.tmp/competitors.json`** — a JSON list, one object per competitor:
   `[{"name": "...", "url": "...", "summary": "<summary text>"}, ...]`
   This single file feeds both the analysis and the monitor watchlist.
5. **Analyze:**
   `python tools/analyze_competitors.py --profile inputs/business_profile.md --competitors .tmp/competitors.json --output .tmp/analysis.json`
   - Produces the structured analysis (per-competitor strengths/weaknesses, market
     themes, opportunities for Nerumi, SWOT, prioritized recommendations).
6. **Render the branded PDF:**
   `python tools/render_pdf_report.py --analysis .tmp/analysis.json --output "reports/Nerumi_Competitive_Landscape_<date>.pdf"`
   - Fonts and the logo mark are base64-embedded, so the PDF is self-contained.
   - Add `--keep-html` to also write the rendered HTML for inspection/tweaks.
   - To embed competitor homepage thumbnails, first capture them:
     `python tools/capture_screenshots.py --competitors .tmp/competitors.json --output-dir .tmp/shots`,
     then add `--shots-dir .tmp/shots` to the render command.
7. **Create the tracker Sheet** (first time) and write one row per competitor:
   `python tools/push_to_google_sheet.py --create "Nerumi Competitor Tracker" --values-file .tmp/rows.json`
   - Suggested columns: `[date, competitor, url, positioning, pricing, whats_working, weaknesses]`
     (write a header row first). Save the printed spreadsheet **ID** for monitoring.
8. **Notify (optional):**
   `python tools/notify_slack.py --text "Nerumi competitor report ready: <sheet link> + PDF in reports/"`

## Procedure — Ongoing monitoring (weekly)
1. **Seed baselines** once (no alerts on first run):
   `python tools/monitor_competitors.py --watchlist .tmp/competitors.json`
2. **Weekly run** — diff each page vs its baseline; record + alert only on meaningful
   change (title, pricing/number tokens, or a substantial body-text shift):
   `python tools/monitor_competitors.py --watchlist .tmp/competitors.json --spreadsheet-id <TRACKER_ID> --sheet "Changes" --slack`
3. **Build the trend view.** Every monitor run also appends a dated snapshot to
   `monitor/history/<slug>.jsonl` (append-only, durable — title, pricing, body
   size/hash, and whether it was a meaningful change). Turn that log into trends:
   `python tools/build_trends.py --spreadsheet-id <TRACKER_ID> --sheet "History"`
   - Prints a per-competitor summary (snapshots tracked, # of changes, pricing
     evolution, title shifts, last change) and (re)writes the Sheet `History` tab
     with the full timeline. Add `--output .tmp/trends.md` for a markdown digest.
   - Read-only over local history — it never re-scrapes. Run it after the monitor.
   - **Baseline vs history:** `monitor/state/` is the *single rolling baseline*
     (overwritten on change — "did anything change since last week"); `monitor/history/`
     is the *append-only timeline* ("how has this evolved"). The `Changes` tab is the
     alert log; the `History` tab is the trend log.
4. **Schedule it.** Monitoring depends on *local* state (`monitor/state/` baselines,
   `monitor/history/` timeline, `token.json`, `.venv`), so a cloud cron can't run it —
   use a local OS scheduler. On Windows, a scheduled task runs `monitor/run_weekly.cmd`
   (monitor *then* `build_trends`). State persists in `monitor/` (durable — not `.tmp/`).

### Example deployment
- **Watchlist:** `monitor/watchlist.json` — the competitor URLs to track (name + url).
- **Tracker Sheet:** create once with `push_to_google_sheet.py --create`; note the
  printed spreadsheet id and set it in `monitor/run_weekly.cmd`. The `Competitors`
  tab holds the snapshot; the `Changes` tab is the change log the weekly watch
  appends to (auto-created with a header on first change); the `History` tab is the
  full dated timeline `build_trends.py` (re)writes each run.
- **Runner:** `monitor/run_weekly.cmd` runs the monitor then `build_trends` against the
  Sheet and logs both to `monitor/monitor.log`. Double-click to run on demand.
- **Schedule (Windows):** register a weekly Task Scheduler job pointing at the runner:
  `Register-ScheduledTask -TaskName "CompetitorWatch" -Trigger (New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday -At 9:07AM) -Action (New-ScheduledTaskAction -Execute "<repo>\monitor\run_weekly.cmd")`
  Monitoring depends on *local* state (`monitor/state/`, `token.json`, `.venv`), so it
  runs locally, not in a cloud cron.
- **Alerts:** changes land in the Sheet `Changes` tab. Set `SLACK_BOT_TOKEN` and pass
  `--slack` in the runner to enable Slack pings.

## Expected Output
- **Branded PDF** in `reports/` (the deep-dive deliverable).
- **Google Sheet tracker** — one row per competitor, plus a `Changes` tab the weekly
  watch appends to (the living record).
- Intermediate scrapes/summaries/`analysis.json` in `.tmp/` (disposable).

## Edge Cases & Notes
- **JS-heavy / blocked sites:** requests + BeautifulSoup only see server-rendered
  HTML. Sparse text or a 403/429 is the tell. First escalate to a Chromium fetch
  (Playwright is installed); if a site is *still* blocked (Cloudflare/anti-bot), use
  `tools/firecrawl_scrape.py` (hosted Firecrawl API; set `FIRECRAWL_API_KEY` in
  `.env`). It returns the same JSON shape, so `summarize.py` consumes it unchanged.
  Firecrawl is a paid API with a free tier — only reach for it when the free local
  path fails.
- **Gemini JSON:** `analyze_competitors.py` requests strict JSON and strips code
  fences; if a model response ever fails to parse, re-run (temperature is low) or
  shorten the per-competitor summaries (`MAX_SUMMARY_CHARS`).
- **Fonts:** the report uses General Sans (Voice A) + Lora (Voice B) — the confirmed
  substitutes for the design system's named Neue Montreal + ZT Bros Oskon, which were
  not provided. Don't switch back. Brand source of truth: `brand-assets/nerumi-design-system-v4.html`.
- **Logo:** embed the mark from `Nerumi_Logo.svg` (vector) and typeset the wordmark in
  CSS — the lockup SVGs contain live text in unshipped fonts and will render with the
  wrong typeface.
- **Monitoring noise:** the body-text threshold is `SIMILARITY_THRESHOLD = 0.97` in
  `monitor_competitors.py`. Raise it to catch smaller edits, lower it to reduce noise.
  A detected change advances the baseline so it isn't re-reported next week.
- **Gemini model availability (learned 2026-05-28):** `gemini-2.0-flash` returns
  HTTP 429 with `limit: 0` on this project's free tier — i.e. it is *not* available.
  Use **`gemini-2.5-flash`** (set in `.env` and as the tool default). `gemini-1.5-flash`
  is retired (404). `gemini-flash-latest` and `gemini-2.5-flash-lite` also work.
- **Transient 503s:** `gemini-2.5-flash` can return `503 UNAVAILABLE` ("high demand")
  on heavier prompts. `analyze_competitors.py` now retries with backoff and falls back
  across models automatically, so a single 503 is not fatal — just re-run if a whole
  run fails.
- **Cost:** summarize + analyze use the Gemini free tier — space out large batches if
  you hit rate limits. Scraping and PDF rendering are local/free.

<!-- Keep this workflow current: when you discover a better method, a new constraint,
or a recurring failure, update the relevant section above. -->
