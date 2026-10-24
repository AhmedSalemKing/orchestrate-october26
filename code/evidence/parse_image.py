"""Parse image evidence files into Facts via OCR."""
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from evidence.facts import Fact
from dataload.normalization import normalize_email, normalize_phone, normalize_hash, normalize_user_id
from dataload.timeutil import parse_iso_utc


def _try_ocr(path: Path) -> str | None:
    try:
        import pytesseract
        from PIL import Image
        # If tesseract binary is not on PATH, pytesseract will raise
        return pytesseract.image_to_string(Image.open(path))
    except Exception:
        return None


def parse_image(path: Path, file_id: str, captured_at: datetime | None) -> list[Fact]:
    facts = []
    text = _try_ocr(path)
    if text is None or not text.strip():
        # No OCR available: return empty and let the index record an error
        return []

    for idx, raw_line in enumerate(text.splitlines(), 1):
        line = raw_line.strip()
        if not line:
            continue

        emails = re.findall(r"[\w.\-+]+@[\w.\-]+\.[a-zA-Z]{2,}", line)
        phones = re.findall(r"\+?[\d\s\-()]{7,}", line)
        user_ids = re.findall(r"\b(user_\d+)\b", line)
        resources = re.findall(r"\b(account_\d+|search_\d+|analytics_\d+|support_\d+|export_\d+|backup_\d+|data_flow_\d+|cache_\d+|email_delivery_\d+|audit_record_\d+|tombstone_\d+)\b", line)

        identifiers = []
        for e in emails:
            identifiers.append({"kind": "email", "value": e, "normalized": normalize_email(e)})
        for p in phones:
            np = normalize_phone(p)
            if np:
                identifiers.append({"kind": "phone", "value": p, "normalized": np})
        for uid in user_ids:
            identifiers.append({"kind": "user_id", "value": uid, "normalized": uid})

        if not identifiers:
            continue

        resource_id = resources[0] if resources else None
        category = "USER_PROFILE"
        if resource_id:
            rid = resource_id.lower()
            if rid.startswith("search_"):
                category = "SEARCH_INDEX_ENTRY"
            elif rid.startswith("analytics_"):
                category = "ANALYTICS_PROFILE"
            elif rid.startswith("support_"):
                category = "SUPPORT_MESSAGE"
            elif rid.startswith("export_"):
                category = "USER_EXPORT"
            elif rid.startswith("backup_"):
                category = "BACKUP_ARCHIVE"
            elif rid.startswith("data_flow_"):
                category = "DATA_FLOW"
            elif rid.startswith("cache_"):
                category = "CACHE_ENTRY"
            elif rid.startswith("email_delivery_"):
                category = "EMAIL_DELIVERY_LOG"
            elif rid.startswith("audit_record_"):
                category = "SECURITY_AUDIT_LOG"
            elif rid.startswith("tombstone_"):
                category = "ACCOUNT_TOMBSTONE"

        ts_match = re.search(r"(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z?)", line)
        record_time = parse_iso_utc(ts_match.group(1)) if ts_match else None

        facts.append(Fact(
            source_kind="file",
            source_id=file_id,
            source_path=str(path),
            locator=f"ocr-line:{idx}",
            system_id=None,
            resource_id=resource_id,
            data_category=category,
            fields_present=["ocr_text"],
            identifiers=identifiers,
            record_time=record_time,
            capture_time=captured_at,
            raw_excerpt=raw_line[:500],
            extractor="ocr-tesseract",
            confidence=0.7,
        ))

    return facts
