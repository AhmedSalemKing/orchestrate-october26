"""Identifier normalization utilities."""
from __future__ import annotations

import re
import unicodedata


def safe_unicode(value: str | None) -> str | None:
    """Return a cleaned Unicode string; repair mojibake only when it round-trips."""
    if value is None:
        return None
    if not isinstance(value, str):
        value = str(value)
    # NFC normalization
    value = unicodedata.normalize("NFC", value)
    # Try common mojibake repair via encode/decode round-trip
    try:
        repaired = value.encode("latin1").decode("utf-8")
        if repaired.encode("utf-8").decode("latin1") == value:
            value = repaired
    except (UnicodeEncodeError, UnicodeDecodeError):
        pass
    return value


def normalize_email(value: str | None) -> str | None:
    """Lowercase and strip surrounding whitespace from email."""
    if value is None:
        return None
    value = safe_unicode(value)
    value = value.strip().lower()
    return value if value else None


def normalize_phone(value: str | None) -> str | None:
    """Return digits-only phone; keep None if no digits."""
    if value is None:
        return None
    value = safe_unicode(value)
    digits = re.sub(r"\D", "", value)
    return digits if digits else None


def normalize_phone_raw(value: str | None) -> str | None:
    """Return phone after NFC normalization and basic whitespace collapse."""
    if value is None:
        return None
    value = safe_unicode(value)
    value = re.sub(r"\s+", " ", value.strip())
    return value if value else None


def normalize_name(value: str | None) -> str | None:
    """NFC, lowercase, collapse whitespace, remove leading/trailing."""
    if value is None:
        return None
    value = safe_unicode(value)
    value = value.lower()
    value = re.sub(r"\s+", " ", value.strip())
    return value if value else None


def normalize_hash(value: str | None) -> str | None:
    """Lowercase hex hash."""
    if value is None:
        return None
    value = safe_unicode(value)
    value = value.strip().lower()
    return value if value else None


def normalize_user_id(value: str | None) -> str | None:
    """Strip whitespace from user_id."""
    if value is None:
        return None
    value = safe_unicode(value)
    value = value.strip()
    return value if value else None
