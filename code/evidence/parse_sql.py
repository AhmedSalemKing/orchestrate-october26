"""Parse SQLite-compatible SQL snapshots into Facts without executing destructive statements."""
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

from evidence.facts import Fact
from dataload.normalization import normalize_email, normalize_phone, normalize_hash, normalize_name, normalize_user_id
from dataload.timeutil import parse_iso_utc


def _system_from_path(path: Path) -> str:
    name = path.stem.lower()
    if "failover" in name:
        return "failover_replica"
    if "regional" in name:
        return "regional_replica"
    if "reporting" in name:
        return "reporting_replica"
    if "inventory" in name:
        return "data_inventory"
    if "primary" in name or "search" in name:
        return "primary"
    return "sql_snapshot"


def _data_category_from_table(table: str) -> str:
    t = table.lower()
    if "profile" in t:
        return "USER_PROFILE"
    if "search" in t:
        return "SEARCH_INDEX_ENTRY"
    if "cache" in t:
        return "CACHE_ENTRY"
    if "support" in t:
        return "SUPPORT_MESSAGE"
    if "analytics" in t:
        return "ANALYTICS_PROFILE"
    if "export" in t:
        return "USER_EXPORT"
    if "marketing" in t:
        return "MARKETING_PROFILE"
    if "email" in t:
        return "EMAIL_DELIVERY_LOG"
    if "audit" in t or "security" in t:
        return "SECURITY_AUDIT_LOG"
    if "legal" in t:
        return "LEGAL_HOLD_RECORD"
    if "backup" in t:
        return "BACKUP_ARCHIVE"
    if "tombstone" in t or "deleted_customer" in t:
        return "ACCOUNT_TOMBSTONE"
    return "USER_PROFILE"


def _data_category_from_resource(resource_id: str | None) -> str | None:
    if not resource_id:
        return None
    rid = str(resource_id).lower()
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
    return None


def _tokenize_values(values_str: str) -> list[str]:
    """Tokenize a SQLite VALUES tuple string."""
    vals = []
    i = 0
    n = len(values_str)
    while i < n:
        if values_str[i].isspace() or values_str[i] == ',':
            i += 1
            continue
        if values_str[i] == "'":
            j = i + 1
            while j < n:
                if values_str[j] == "'" and (j + 1 >= n or values_str[j + 1] != "'"):
                    break
                if values_str[j] == "'" and j + 1 < n and values_str[j + 1] == "'":
                    j += 2
                else:
                    j += 1
            token = values_str[i + 1:j].replace("''", "'")
            vals.append(token)
            i = j + 1
        else:
            j = i
            while j < n and values_str[j] not in ",)":
                j += 1
            token = values_str[i:j].strip()
            if token.lower() == "null":
                vals.append(None)
            else:
                vals.append(token)
            i = j
    return vals


def _flatten_json(nested: dict | list, prefix: str = "") -> dict:
    """Flatten a nested JSON object into dot-separated keys."""
    flat = {}
    if isinstance(nested, dict):
        for k, v in nested.items():
            key = f"{prefix}.{k}" if prefix else k
            if isinstance(v, (dict, list)):
                flat.update(_flatten_json(v, key))
            else:
                flat[key] = v
    elif isinstance(nested, list):
        for idx, v in enumerate(nested):
            key = f"{prefix}[{idx}]"
            if isinstance(v, (dict, list)):
                flat.update(_flatten_json(v, key))
            else:
                flat[key] = v
    return flat


def _extract_from_record(record: dict) -> tuple[list[dict], list[str], str | None]:
    """Extract identifiers and state hints from a record dict."""
    identifiers = []
    fields_present = []
    system_id = None

    def add(kind, val):
        if val is None or val == "":
            return
        val = str(val)
        if kind == "email":
            norm = normalize_email(val)
            if norm:
                identifiers.append({"kind": "email", "value": val, "normalized": norm})
        elif kind == "phone":
            norm = normalize_phone(val)
            if norm:
                identifiers.append({"kind": "phone", "value": val, "normalized": norm})
        elif kind == "hash":
            norm = normalize_hash(val)
            if norm:
                identifiers.append({"kind": "hash", "value": val, "normalized": norm})
        elif kind == "user_id":
            norm = normalize_user_id(val)
            if norm:
                identifiers.append({"kind": "user_id", "value": val, "normalized": norm})
        elif kind == "name":
            norm = normalize_name(val)
            if norm:
                identifiers.append({"kind": "name", "value": val, "normalized": norm})

    # Direct fields, including flattened nested keys
    lower_record = {k.lower(): v for k, v in record.items()}

    def find(keys):
        for k in keys:
            if k in lower_record:
                return lower_record[k]
            # Also match keys ending with the alias (e.g., document.email)
            for full_k, full_v in lower_record.items():
                if full_k.endswith(f".{k}") or full_k.endswith(f"_{k}"):
                    return full_v
        return None

    add("email", find(("email", "customer_email", "owner_email", "requester_email")))
    add("phone", find(("phone", "customer_phone", "owner_phone", "requester_phone")))
    add("hash", find(("email_hash", "hash")))
    add("user_id", find(("user_id", "customer_reference", "subject_reference")))
    add("name", find(("full_name", "name", "display_name", "requester_name", "customer_name")))

    # State hints
    status = record.get("account_status") or record.get("status")
    if status:
        fields_present.append(f"status:{str(status).lower()}")
    enabled = record.get("enabled")
    if enabled is False or (isinstance(enabled, str) and enabled.lower() == "false"):
        fields_present.append("state:DISABLED")
    elif enabled is True or (isinstance(enabled, str) and enabled.lower() == "true"):
        fields_present.append("state:ACTIVE")
    restore = record.get("restore_allowed")
    if restore is False or (isinstance(restore, str) and restore.lower() == "false"):
        fields_present.append("state:BLOCKED")
    elif restore is True or (isinstance(restore, str) and restore.lower() == "true"):
        fields_present.append("state:ACTIVE")

    # Origin system from record
    for key in ("origin_system", "source_system", "data_store", "source"):
        if record.get(key):
            system_id = str(record.get(key))
            break

    return identifiers, fields_present, system_id


def parse_sql(path: Path, file_id: str, captured_at: datetime | None) -> list[Fact]:
    facts = []
    text = path.read_text(encoding="utf-8-sig", errors="replace")

    # Parse CREATE TABLE to get columns
    table_cols: dict[str, list[str]] = {}
    for match in re.finditer(r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?['\"`]*(\w+)['\"`]*\s*\((.+?)\);", text, re.IGNORECASE | re.DOTALL):
        table_name = match.group(1)
        body = match.group(2)
        cols = []
        for part in re.split(r",(?![^()]*\))", body):
            part = part.strip()
            if not part:
                continue
            m = re.match(r"['\"`]*(\w+)['\"`]*\s+", part)
            if m:
                cols.append(m.group(1))
        table_cols[table_name] = cols

    default_system_id = _system_from_path(path)

    # Parse INSERT statements
    for match in re.finditer(r"INSERT\s+INTO\s+['\"`]*(\w+)['\"`]*\s+VALUES\s*\((.+?)\);", text, re.IGNORECASE | re.DOTALL):
        table = match.group(1)
        values_str = match.group(2)
        cols = table_cols.get(table, [])
        vals = _tokenize_values(values_str)
        if not cols or len(cols) != len(vals):
            cols = [f"col{i}" for i in range(len(vals))]
        record = dict(zip(cols, vals))

        category = _data_category_from_table(table)
        resource_id = record.get("resource_id") or record.get("id") or record.get("account_id") or record.get("profile_id") or record.get("record_id")

        # If there is a record_json column, merge its contents
        record_json = record.get("record_json")
        if record_json and isinstance(record_json, str):
            try:
                nested = json.loads(record_json)
                if isinstance(nested, dict):
                    flat = _flatten_json(nested)
                    # Overlay flattened values (don't overwrite top-level explicit None with nested values)
                    for k, v in flat.items():
                        if k not in record or record[k] is None:
                            record[k] = v
            except Exception:
                pass

        identifiers, extra_fields, origin_system = _extract_from_record(record)
        if not identifiers:
            continue

        fields_present = [c for c in ["email", "phone", "email_hash", "user_id", "name"] if record.get(c)]
        fields_present.extend(extra_fields)

        # Determine system id: prefer explicit origin, then path-derived
        system_id = origin_system or default_system_id

        # Refine category from resource_id if available
        cat_from_res = _data_category_from_resource(resource_id)
        if cat_from_res:
            category = cat_from_res

        # Time
        time_col = None
        for alt in ("updated_at", "observed_at", "captured_at", "created_at", "event_time", "record_time"):
            if alt in record:
                time_col = alt
                break
        record_time = parse_iso_utc(record.get(time_col)) if time_col else None

        facts.append(Fact(
            source_kind="file",
            source_id=file_id,
            source_path=str(path),
            locator=f"{table}:row{len(facts)}",
            system_id=system_id,
            resource_id=resource_id,
            data_category=category,
            fields_present=fields_present,
            identifiers=identifiers,
            record_time=record_time,
            capture_time=captured_at,
            raw_excerpt=str(record)[:500],
            extractor="sql-parser",
            confidence=1.0,
        ))

    return facts
