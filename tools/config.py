"""Shared configuration helpers for WAT tools.

Loads environment variables from the project .env file and provides accessors
with clear errors when a required value is missing. Import this from any tool:

    from config import get_env, tmp_path, PROJECT_ROOT
"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
TMP_DIR = PROJECT_ROOT / ".tmp"

load_dotenv(PROJECT_ROOT / ".env")


def get_env(name: str, default: str | None = None, *, required: bool = False) -> str | None:
    value = os.getenv(name, default)
    if required and not value:
        raise RuntimeError(
            f"Missing required environment variable '{name}'. "
            f"Add it to {PROJECT_ROOT / '.env'} (see .env.example)."
        )
    return value


def tmp_path(filename: str) -> Path:
    """Return a path under .tmp/, creating the directory if needed."""
    TMP_DIR.mkdir(exist_ok=True)
    return TMP_DIR / filename
