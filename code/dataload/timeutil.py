"""Timezone-aware UTC time utilities."""
from __future__ import annotations

from datetime import datetime, timezone


def parse_iso_utc(value: str | None) -> datetime | None:
    """Parse an ISO-8601 UTC string into a timezone-aware UTC datetime."""
    if value is None or value == "":
        return None
    value = value.strip()
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt


def is_before_or_equal(t: datetime | None, cutoff: datetime | None) -> bool:
    """Return True if t is None, cutoff is None, or t <= cutoff."""
    if t is None or cutoff is None:
        return True
    return t <= cutoff


def format_utc(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
