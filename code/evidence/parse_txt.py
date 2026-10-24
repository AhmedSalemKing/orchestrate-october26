"""Parse plain-text evidence files into Facts."""
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from evidence.facts import Fact
from dataload.normalization import normalize_email, normalize_phone, normalize_hash, normalize_name, normalize_user_id
from dataload.timeutil import parse_iso_utc


_RESOURCE_PATTERN = re.compile(
    r"\b(account_\d+|search_\d+|analytics_\d+|support_\d+|export_\d+|backup_\d+|data_flow_\d+|cache_\d+|email_delivery_\d+|audit_record_\d+|tombstone_\d+|legal_\d+)\b"
)

_ABSENCE_KEYWORDS = (
    "not_found", "not found", "deleted", "absent", "removed", "null",
    "missing", "gone", "purged", "erased",
)


def _is_absence_signal(line: str) -> bool:
    t = line.lower()
    return any(kw in t for kw in _ABSENCE_KEYWORDS)


def _data_category_from_resource(resource_id: str) -> str:
    rid = resource_id.lower()
    if rid.startswith("account_"):
        return "USER_PROFILE"
    if rid.startswith("search_"):
        return "SEARCH_INDEX_ENTRY"
    if rid.startswith("analytics_"):
        return "ANALYTICS_PROFILE"
    if rid.startswith("support_"):
        return "SUPPORT_MESSAGE"
    if rid.startswith("export_"):
        return "USER_EXPORT"
    if rid.startswith("backup_"):
        return "BACKUP_ARCHIVE"
    if rid.startswith("data_flow_"):
        return "DATA_FLOW"
    if rid.startswith("cache_"):
        return "CACHE_ENTRY"
    if rid.startswith("email_delivery_"):
        return "EMAIL_DELIVERY_LOG"
    if rid.startswith("audit_record_"):
        return "SECURITY_AUDIT_LOG"
    if rid.startswith("tombstone_"):
        return "ACCOUNT_TOMBSTONE"
    if rid.startswith("legal_"):
        return "LEGAL_HOLD_RECORD"
    return "USER_PROFILE"


def parse_txt(path: Path, file_id: str, captured_at: datetime | None) -> list[Fact]:
    facts = []
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    for idx, raw_line in enumerate(text.splitlines(), 1):
        line = raw_line.strip()
        if not line:
            continue

        emails = re.findall(r"[\w.\-+]+@[\w.\-]+\.[a-zA-Z]{2,}", line)
        phones = re.findall(r"\+?[\d\s\-()]{7,}", line)
        user_ids = re.findall(r"\b(user_\d+)\b", line)
        resources = _RESOURCE_PATTERN.findall(line)

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
            category = _data_category_from_resource(resource_id)

        ts_match = re.search(r"(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z?)", line)
        record_time = parse_iso_utc(ts_match.group(1)) if ts_match else None

        fields_present = ["text"]
        if _is_absence_signal(line):
            fields_present.append("state:ABSENT")

        facts.append(Fact(
            source_kind="file",
            source_id=file_id,
            source_path=str(path),
            locator=f"line:{idx}",
            system_id=None,
            resource_id=resource_id,
            data_category=category,
            fields_present=fields_present,
            identifiers=identifiers,
            record_time=record_time,
            capture_time=captured_at,
            raw_excerpt=raw_line[:500],
            extractor="txt-heur",
            confidence=0.8,
        ))

    return facts
