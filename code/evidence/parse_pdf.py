"""Parse PDF evidence files into Facts."""
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from evidence.facts import Fact
from dataload.normalization import normalize_email, normalize_phone, normalize_hash, normalize_name, normalize_user_id
from dataload.timeutil import parse_iso_utc


def _extract_text(path: Path) -> str | None:
    try:
        from pypdf import PdfReader
        reader = PdfReader(str(path))
        pages = []
        for page in reader.pages:
            try:
                pages.append(page.extract_text() or "")
            except Exception:
                pass
        return pages
    except Exception:
        return None


def _data_category_from_resource(resource_id: str | None) -> str:
    if not resource_id:
        return "SECURITY_AUDIT_LOG"
    rid = str(resource_id).lower()
    if rid.startswith("tombstone_"):
        return "ACCOUNT_TOMBSTONE"
    if rid.startswith("backup_"):
        return "BACKUP_ARCHIVE"
    if rid.startswith("legal_"):
        return "LEGAL_HOLD_RECORD"
    if rid.startswith("support_"):
        return "SUPPORT_MESSAGE"
    if rid.startswith("account_"):
        return "USER_PROFILE"
    if rid.startswith("search_"):
        return "SEARCH_INDEX_ENTRY"
    if rid.startswith("analytics_"):
        return "ANALYTICS_PROFILE"
    if rid.startswith("export_"):
        return "USER_EXPORT"
    if rid.startswith("audit_record_"):
        return "SECURITY_AUDIT_LOG"
    return "SECURITY_AUDIT_LOG"


def parse_pdf(path: Path, file_id: str, captured_at: datetime | None) -> list[Fact]:
    facts = []
    pages = _extract_text(path)
    filename_lower = path.name.lower()
    is_attachment_pdf = "attachment" in filename_lower
    if pages is None:
        return []

    for page_idx, page_text in enumerate(pages, 1):
        if not page_text.strip():
            continue

        # Extract identifiers and resources from the whole page
        emails = re.findall(r"[\w.\-+]+@[\w.\-]+\.[a-zA-Z]{2,}", page_text)
        phones = re.findall(r"\+?[\d\s\-()]{7,}", page_text)
        user_ids = re.findall(r"\b(user_\d+)\b", page_text)
        resources = re.findall(r"\b(account_\d+|search_\d+|analytics_\d+|support_\d+|export_\d+|backup_\d+|data_flow_\d+|cache_\d+|email_delivery_\d+|audit_record_\d+|tombstone_\d+)\b", page_text)

        identifiers = []
        for e in emails:
            identifiers.append({"kind": "email", "value": e, "normalized": normalize_email(e)})
        for p in phones:
            np = normalize_phone(p)
            if np:
                identifiers.append({"kind": "phone", "value": p, "normalized": np})
        for uid in user_ids:
            identifiers.append({"kind": "user_id", "value": uid, "normalized": uid})

        # Deduplicate identifiers
        seen = set()
        unique_idents = []
        for ident in identifiers:
            key = (ident["kind"], ident["normalized"])
            if key not in seen and key[1]:
                seen.add(key)
                unique_idents.append(ident)
        identifiers = unique_idents

        if not identifiers and not resources:
            continue

        ts_match = re.search(r"(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z?)", page_text)
        record_time = parse_iso_utc(ts_match.group(1)) if ts_match else None

        # Emit one fact per resource found on the page, sharing page identifiers
        emitted_resources = set()
        for rid in resources:
            if rid in emitted_resources:
                continue
            emitted_resources.add(rid)
            category = _data_category_from_resource(rid)
            if is_attachment_pdf and rid.lower().startswith("support_"):
                category = "SUPPORT_ATTACHMENT"
            facts.append(Fact(
                source_kind="file",
                source_id=file_id,
                source_path=str(path),
                locator=f"page:{page_idx} resource:{rid}",
                system_id=None,
                resource_id=rid,
                data_category=category,
                fields_present=["text"],
                identifiers=list(identifiers),
                record_time=record_time,
                capture_time=captured_at,
                raw_excerpt=page_text[:500],
                extractor="pdf-text",
                confidence=0.8,
            ))

        # If no resource but identifiers present, emit a generic fact
        if not resources and identifiers:
            facts.append(Fact(
                source_kind="file",
                source_id=file_id,
                source_path=str(path),
                locator=f"page:{page_idx}",
                system_id=None,
                resource_id=None,
                data_category="SECURITY_AUDIT_LOG",
                fields_present=["text"],
                identifiers=list(identifiers),
                record_time=record_time,
                capture_time=captured_at,
                raw_excerpt=page_text[:500],
                extractor="pdf-text",
                confidence=0.8,
            ))

    return facts
