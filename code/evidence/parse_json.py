"""Parse JSON evidence files into Facts."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from evidence.facts import Fact
from dataload.normalization import normalize_email, normalize_phone, normalize_hash, normalize_name, normalize_user_id
from dataload.timeutil import parse_iso_utc


# Known field name aliases
_EMAIL_ALIASES = ("email", "requester_email", "customer_email", "contact_email", "owner_email")
_PHONE_ALIASES = ("phone", "requester_phone", "customer_phone", "contact_phone")
_NAME_ALIASES = ("name", "full_name", "requester_name", "customer_name", "subject_name")
_HASH_ALIASES = ("email_hash", "hash", "customer_reference")
_USER_ALIASES = ("user_id", "subject_reference", "customer_reference")
_RESOURCE_ALIASES = ("resource_id", "id", "account_id", "profile_id", "record_id")
_TIME_ALIASES = ("observed_at", "captured_at", "updated_at", "created_at", "recorded_at", "event_time")
_STATUS_ALIASES = ("account_status", "status", "state")


def _find_value(obj: dict, aliases: tuple[str, ...]) -> Any:
    for a in aliases:
        if a in obj and obj[a] not in (None, ""):
            return obj[a]
    return None


def _data_category_from_record(record: dict, default_store: str | None, collection: str | None = None) -> str:
    store = (default_store or "").lower()
    coll = (collection or "").lower()
    if "export" in coll or "export" in store:
        return "USER_EXPORT"
    if "account" in store or "profile" in store:
        return "USER_PROFILE"
    if "identity" in store or "tombstone" in store or "deleted_customer" in store:
        return "ACCOUNT_TOMBSTONE"
    if "search" in store:
        return "SEARCH_INDEX_ENTRY"
    if "analytics" in store:
        return "ANALYTICS_PROFILE"
    if "support" in store:
        return "SUPPORT_MESSAGE"
    if "security" in store:
        return "SECURITY_AUDIT_LOG"
    if "marketing" in store:
        return "MARKETING_PROFILE"
    if "cache" in store:
        return "CACHE_ENTRY"
    return "USER_PROFILE"


def _extract_fact_from_record(record: dict, file_id: str, path: str, locator: str, captured_at: datetime | None, default_store: str | None = None, collection: str | None = None) -> Fact | None:
    email = _find_value(record, _EMAIL_ALIASES)
    phone = _find_value(record, _PHONE_ALIASES)
    name = _find_value(record, _NAME_ALIASES)
    email_hash = _find_value(record, _HASH_ALIASES)
    user_id = _find_value(record, _USER_ALIASES)
    resource_id = _find_value(record, _RESOURCE_ALIASES)
    record_time = parse_iso_utc(_find_value(record, _TIME_ALIASES))
    status = _find_value(record, _STATUS_ALIASES)

    identifiers = []
    if email:
        identifiers.append({"kind": "email", "value": email, "normalized": normalize_email(email)})
    if phone:
        identifiers.append({"kind": "phone", "value": phone, "normalized": normalize_phone(phone)})
    if email_hash and isinstance(email_hash, str):
        identifiers.append({"kind": "hash", "value": email_hash, "normalized": normalize_hash(email_hash)})
    if user_id:
        identifiers.append({"kind": "user_id", "value": user_id, "normalized": normalize_user_id(user_id)})
    if name:
        identifiers.append({"kind": "name", "value": name, "normalized": normalize_name(name)})

    if not identifiers:
        return None

    # Determine system id
    store = default_store or _find_value(record, ("data_store", "service", "source_system", "system"))
    system_id = store if isinstance(store, str) else None

    category = _data_category_from_record(record, system_id, collection)
    if "tombstone" in str(resource_id).lower() or "deleted_customer" in (system_id or ""):
        category = "ACCOUNT_TOMBSTONE"
    if "analytics" in (system_id or "") or (isinstance(resource_id, str) and resource_id.startswith("analytics_")):
        category = "ANALYTICS_PROFILE"
    if isinstance(resource_id, str):
        if resource_id.startswith("search_"):
            category = "SEARCH_INDEX_ENTRY"
        elif resource_id.startswith("support_"):
            category = "SUPPORT_MESSAGE"
        elif resource_id.startswith("export_"):
            category = "USER_EXPORT"
        elif resource_id.startswith("audit_record_"):
            category = "SECURITY_AUDIT_LOG"
        elif resource_id.startswith("backup_"):
            category = "BACKUP_ARCHIVE"
        elif resource_id.startswith("data_flow_"):
            category = "DATA_FLOW"
        elif resource_id.startswith("cache_"):
            category = "CACHE_ENTRY"
        elif resource_id.startswith("email_delivery_"):
            category = "EMAIL_DELIVERY_LOG"

    fields_present = [k for k in ["email", "phone", "email_hash", "name", "user_id"] if record.get(k) not in (None, "")]

    return Fact(
        source_kind="file",
        source_id=file_id,
        source_path=path,
        locator=locator,
        system_id=system_id,
        resource_id=resource_id,
        data_category=category,
        fields_present=fields_present,
        identifiers=identifiers,
        record_time=record_time,
        capture_time=captured_at,
        raw_excerpt=json.dumps(record, ensure_ascii=False)[:500],
        extractor="json-loader",
        confidence=1.0,
    )


def _walk(obj: Any, callback, path: str = "") -> None:
    if isinstance(obj, dict):
        callback(obj, path)
        for k, v in obj.items():
            _walk(v, callback, f"{path}.{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            _walk(v, callback, f"{path}[{i}]")


def parse_json(path: Path, file_id: str, captured_at: datetime | None) -> list[Fact]:
    facts = []
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        return []

    # Track current store/collection context from snapshot structure
    current_store = None
    current_collection = None

    def callback(obj: dict, loc: str):
        nonlocal current_store, current_collection
        if "data_store" in obj or "source" in obj:
            current_store = obj.get("data_store") or obj.get("source")
        if "collection" in obj:
            current_collection = obj["collection"]
        if "service_exports" in obj or "snapshots" in obj:
            return
        # Emit facts for objects with resource_id and explicit state fields
        if "resource_id" in obj:
            fact = _extract_fact_from_record(obj, file_id, str(path), loc or "root", captured_at, current_store, current_collection)
            if fact:
                # Annotate state from explicit fields
                sc = obj.get("status_code")
                if sc == 404 or (isinstance(sc, str) and sc.startswith("404")):
                    fact.fields_present.append("state:ABSENT")
                elif sc == 200:
                    fact.fields_present.append("state:PRESENT")

                ra = obj.get("restore_allowed")
                if ra is False or (isinstance(ra, str) and ra.lower() == "false"):
                    fact.fields_present.append("state:BLOCKED")
                elif ra is True or (isinstance(ra, str) and ra.lower() == "true"):
                    fact.fields_present.append("state:ACTIVE")

                enabled = obj.get("enabled")
                if enabled is False or (isinstance(enabled, str) and enabled.lower() == "false"):
                    fact.fields_present.append("state:DISABLED")
                elif enabled is True or (isinstance(enabled, str) and enabled.lower() == "true"):
                    fact.fields_present.append("state:ACTIVE")

                facts.append(fact)
            return

        if not any(k in obj for k in _RESOURCE_ALIASES + _EMAIL_ALIASES + _USER_ALIASES):
            return
        # Skip wrapper objects that contain arrays of records
        if any(isinstance(v, (list, dict)) for v in obj.values()):
            # still may be a record if it has direct identifiers
            if not any(_find_value(obj, aliases) for aliases in [_EMAIL_ALIASES, _PHONE_ALIASES, _USER_ALIASES, _NAME_ALIASES, _HASH_ALIASES]):
                return
        fact = _extract_fact_from_record(obj, file_id, str(path), loc or "root", captured_at, current_store, current_collection)
        if fact:
            facts.append(fact)

    _walk(data, callback)
    return facts
