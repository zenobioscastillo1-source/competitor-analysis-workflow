"""Create a Google Sheet and/or append rows to one (Sheets API v4).

The first run opens a browser for OAuth consent and writes token.json;
later runs reuse it. Requires an OAuth "Desktop app" client saved as
credentials.json in the project root.

Usage:
    # Create a new spreadsheet and write rows into it
    python tools/push_to_google_sheet.py --create "Nerumi Competitor Research" \
        --values-file .tmp/rows.json

    # Append to an existing spreadsheet
    python tools/push_to_google_sheet.py --spreadsheet-id <ID> \
        --range "Sheet1!A1" --values-json "[[\"Competitor\",\"Summary\"]]"

On --create the new spreadsheet's ID and URL are printed to stdout.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from config import PROJECT_ROOT, get_env
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]


def get_credentials() -> Credentials:
    creds_file = PROJECT_ROOT / (get_env("GOOGLE_CREDENTIALS_FILE") or "credentials.json")
    token_file = PROJECT_ROOT / (get_env("GOOGLE_TOKEN_FILE") or "token.json")

    creds = None
    if token_file.exists():
        creds = Credentials.from_authorized_user_file(str(token_file), SCOPES)
    if creds and creds.valid:
        return creds

    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
    else:
        if not creds_file.exists():
            raise RuntimeError(
                f"Missing {creds_file}. Download an OAuth 'Desktop app' client "
                "from Google Cloud Console and save it there."
            )
        flow = InstalledAppFlow.from_client_secrets_file(str(creds_file), SCOPES)
        creds = flow.run_local_server(port=0)
    token_file.write_text(creds.to_json(), encoding="utf-8")
    return creds


def create_spreadsheet(service, title: str) -> tuple[str, str]:
    spreadsheet = (
        service.spreadsheets()
        .create(body={"properties": {"title": title}}, fields="spreadsheetId,spreadsheetUrl")
        .execute()
    )
    return spreadsheet["spreadsheetId"], spreadsheet["spreadsheetUrl"]


def append_rows(service, spreadsheet_id: str, cell_range: str, values: list[list]) -> dict:
    return (
        service.spreadsheets()
        .values()
        .append(
            spreadsheetId=spreadsheet_id,
            range=cell_range,
            valueInputOption="USER_ENTERED",
            insertDataOption="INSERT_ROWS",
            body={"values": values},
        )
        .execute()
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Create and/or append to a Google Sheet.")
    parser.add_argument("--create", metavar="TITLE", help="Create a new spreadsheet with this title.")
    parser.add_argument("--spreadsheet-id", help="Existing spreadsheet to append to.")
    parser.add_argument("--range", default="Sheet1!A1")
    parser.add_argument("--values-json", help='Inline JSON list of rows, e.g. [["a","b"]]')
    parser.add_argument("--values-file", help="Path to a JSON file containing a list of rows.")
    args = parser.parse_args()

    if not args.create and not args.spreadsheet_id:
        print("ERROR: provide --create <title> or --spreadsheet-id <id>.", file=sys.stderr)
        return 1

    values = None
    if args.values_json:
        values = json.loads(args.values_json)
    elif args.values_file:
        values = json.loads(Path(args.values_file).read_text(encoding="utf-8"))

    service = build("sheets", "v4", credentials=get_credentials())

    if args.create:
        spreadsheet_id, url = create_spreadsheet(service, args.create)
        print(f"Created spreadsheet '{args.create}'")
        print(f"  id:  {spreadsheet_id}")
        print(f"  url: {url}")
    else:
        spreadsheet_id = args.spreadsheet_id

    if values:
        result = append_rows(service, spreadsheet_id, args.range, values)
        updated = result.get("updates", {}).get("updatedCells", 0)
        print(f"Appended rows. Updated {updated} cells.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
