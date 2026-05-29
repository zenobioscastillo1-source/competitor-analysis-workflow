"""Small shared helpers for the WAT tools."""
from __future__ import annotations

import re


def slugify(url: str) -> str:
    """Filesystem-safe slug derived from a URL (e.g. for screenshot filenames)."""
    s = re.sub(r"^https?://", "", url.strip().lower())
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s[:80] or "page"
