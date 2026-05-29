# Workflow: Competitor / Market Research

## Objective
Given a set of competitor URLs, scrape each site, summarize the findings into
structured insights for the Kaimito brand overhaul, and deliver them to a
Google Sheet. Optionally notify the team in Slack when the run completes.

## Required Inputs
- **Competitor URLs**: one or more pages to research (homepage, pricing, about).
- **Destination Sheet**: by default the workflow **creates a new spreadsheet**
  via `--create "<title>"` and reports the URL. Pass `--spreadsheet-id` instead
  to append to an existing one.
- **Research focus** (optional): any specific angle (positioning, pricing,
  messaging). Defaults to a general competitor summary.

## Tools
| Step | Tool | Purpose |
|------|------|---------|
| 1 | `tools/scrape_single_site.py` | Fetch one URL, return clean text + links |
| 2 | `tools/summarize.py` | Summarize scraped text via Gemini |
| 3 | `tools/push_to_google_sheet.py` | Create the Sheet and append a row per competitor |
| 4 | `tools/notify_slack.py` | (Optional) post a completion message |

## Procedure
1. **Confirm inputs** — gather the URL list and the target Sheet ID. If the
   focus matters, capture it to pass as `--instructions` in step 2.
2. **Scrape each URL** into `.tmp/`:
   `python tools/scrape_single_site.py <url> --output <slug>.json`
   - If a page returns very little text, it is likely JavaScript-rendered.
     Note it and consider enabling Playwright (see requirements.txt). Do not
     silently skip it.
3. **Summarize each scrape**:
   `python tools/summarize.py --input .tmp/<slug>.json`
   - Capture the summary text for the Sheet row.
4. **Create the Sheet and push rows** — one row per competitor. Suggested
   columns: `[date, competitor_url, title, summary]` (write a header row first).
   `python tools/push_to_google_sheet.py --create "Nerumi Competitor Research" --values-file .tmp/rows.json`
   - First run triggers Google OAuth in the browser and creates `token.json`.
   - The command prints the new spreadsheet URL — pass it along in step 5.
   - To add to an existing sheet later, use `--spreadsheet-id <ID>` instead.
5. **Notify (optional)**:
   `python tools/notify_slack.py --text "Competitor research complete: N sites → <sheet link>"`

## Expected Output
- A Google Sheet with one summarized row per competitor (the deliverable).
- Intermediate scrape JSON in `.tmp/` (disposable, regenerable).

## Edge Cases & Notes
- **Fetch failures / non-200**: the scraper exits non-zero and prints the error.
  Record which URLs failed; continue with the rest rather than aborting the run.
- **JS-heavy sites**: requests + BeautifulSoup only see server-rendered HTML.
  Sparse text is the tell — escalate to Playwright before assuming a site is empty.
- **Rate limiting / blocks (403/429)**: back off and retry; a custom
  `SCRAPER_USER_AGENT` in `.env` sometimes helps. Document recurring blockers here.
- **Long pages**: `summarize.py` truncates input at 100k characters. For very
  long pages, scrape the most relevant subpage instead of the whole site.
- **Cost**: summarization uses the Gemini API, which has a free tier. Watch the
  free-tier rate limits on large batches and space out calls if you hit them.

<!-- Keep this workflow current: when you discover a better method, a new
constraint, or a recurring failure, update the relevant section above. -->
