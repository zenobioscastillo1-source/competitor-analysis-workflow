"""Post a message to Slack.

Usage:
    python tools/notify_slack.py --text "Competitor research complete."
    python tools/notify_slack.py --channel "#brand" --text "Done"

Reads SLACK_BOT_TOKEN and SLACK_DEFAULT_CHANNEL from .env. The bot must be
invited to the target channel.
"""
from __future__ import annotations

import argparse
import sys

from config import get_env
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError


def post_message(text: str, channel: str | None = None) -> None:
    client = WebClient(token=get_env("SLACK_BOT_TOKEN", required=True))
    target = channel or get_env("SLACK_DEFAULT_CHANNEL", required=True)
    client.chat_postMessage(channel=target, text=text)


def main() -> int:
    parser = argparse.ArgumentParser(description="Send a Slack message.")
    parser.add_argument("--text", required=True)
    parser.add_argument("--channel", help="Override SLACK_DEFAULT_CHANNEL.")
    args = parser.parse_args()

    try:
        post_message(args.text, args.channel)
    except SlackApiError as exc:
        print(f"ERROR: Slack API error: {exc.response['error']}", file=sys.stderr)
        return 1
    print("Message sent.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
