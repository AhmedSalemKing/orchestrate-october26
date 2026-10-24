"""Parse line-oriented log files into Facts, grouping by trace_id when available."""
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

from evidence.facts import Fact
from dataload.normalization import normalize_email, normalize_phone, normalize_hash, normalize_name, normalize_user_id
from dataload.timeutil import parse_iso_utc


def _extract_kv_pairs(text: str) -> dict[str, str]:
    pairs = {}
    for m in re.finditer(r"(\w+)=(?:'((?:[^'\\]|\\.)*)'|\"((?:[^\"\\]|\\.)*)\"|([^\s,]*))", text):
        key = m.group(1)
        value = m.group(2) if m.group(2) is not None else (m.group(3) if m.group(3) is not None else m.group(4))
        value = value.replace('\\"', '"').replace("\\'", "'")
        value = value.strip("'\"")
        pairs[key] = value
    return pairs


def _try_json(line: str) -> dict | None:
    try:
        return json.loads(line)
    except Exception:
        return None


def _resource_from_event(text: str | dict) -> str | None:
    if isinstance(text, dict):
        return text.get("resource_id")
    m = re.search(r"resource_id=(\S+)", text)
    if m:
        return m.group(1).strip("'\"")
    return None


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
    return None


def _parse_line(line: str) -> tuple[str | None, dict | None, str]:
    """Return (timestamp, json_or_kv_dict, rest_text)."""
    ts_match = re.match(r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z?)\s+(.*)$", line)
    if ts_match:
        ts_str, rest = ts_match.groups()
    else:
        ts_str, rest = None, line

    data = _try_json(rest)
    if data is not None:
        return ts_str, data, rest

    kvs = _extract_kv_pairs(rest)
    if kvs:
        return ts_str, kvs, rest
    return ts_str, None, rest


def _collect_identifiers(data: dict | None, text: str) -> list[dict]:
    identifiers = []
    def add(kind, val):
        if val and val != "null":
            if kind == "email":
                identifiers.append({"kind": "email", "value": val, "normalized": normalize_email(val)})
            elif kind == "phone":
                identifiers.append({"kind": "phone", "value": val, "normalized": normalize_phone(val)})
            elif kind == "hash":
                identifiers.append({"kind": "hash", "value": val, "normalized": normalize_hash(val)})
            elif kind == "user_id":
                identifiers.append({"kind": "user_id", "value": val, "normalized": normalize_user_id(val)})
            elif kind == "name":
                identifiers.append({"kind": "name", "value": val, "normalized": normalize_name(val)})

    d = data or {}
    for key in ("email", "customer_email", "requester_email"):
        add("email", d.get(key))
    for key in ("phone", "customer_phone", "requester_phone"):
        add("phone", d.get(key))
    for key in ("email_hash", "hash"):
        add("hash", d.get(key))
    for key in ("customer_reference", "subject_reference", "user_id"):
        add("user_id", d.get(key))
    for key in ("requester_name", "customer_name", "full_name", "name"):
        add("name", d.get(key))

    # Also parse from raw text as fallback
    emails = re.findall(r"[\w.\-+]+@[\w.\-]+\.[a-zA-Z]{2,}", text)
    for e in emails:
        add("email", e)
    for uid in re.findall(r"\b(user_\d+)\b", text):
        add("user_id", uid)

    return identifiers


def _is_absence_signal(data: dict | None, text: str) -> bool:
    t = text.lower()
    if data:
        rows = str(data.get("rows", "")).lower()
        http = str(data.get("http_status", "")).lower()
        result = str(data.get("result", "")).lower()
        enabled = str(data.get("enabled", "")).lower()
        restore = str(data.get("restore_allowed", "")).lower()
        if rows == "0" or http == "404" or result in ("miss", "none"):
            return True
        if enabled == "false":
            return True
        if restore == "false":
            return True
    if "rows=0" in t or "http_status=404" in t or "result=miss" in t or "enabled=false" in t or "restore_allowed=false" in t:
        return True
    return False


def _is_presence_signal(data: dict | None, text: str) -> bool:
    t = text.lower()
    if data:
        rows = str(data.get("rows", "")).lower()
        http = str(data.get("http_status", "")).lower()
        result = str(data.get("result", "")).lower()
        if rows and rows != "0":
            return True
        if http == "200":
            return True
        if result in ("hit", "present"):
            return True
    if "rows=1" in t or "http_status=200" in t or "result=hit" in t or "total_hits=1" in t:
        return True
    return False


def parse_log(path: Path, file_id: str, captured_at: datetime | None) -> list[Fact]:
    facts = []
    text = path.read_text(encoding="utf-8-sig", errors="replace")

    # First pass: collect per-trace context
    traces: dict[str, list[tuple[int, str | None, dict | None, str]]] = {}
    lines_parsed = []
    for idx, raw_line in enumerate(text.splitlines(), 1):
        line = raw_line.strip()
        if not line:
            continue
        ts_str, data, rest = _parse_line(line)
        lines_parsed.append((idx, ts_str, data, rest, raw_line))
        trace_id = (data or {}).get("trace_id") if isinstance(data, dict) else None
        if trace_id:
            traces.setdefault(trace_id, []).append((idx, ts_str, data, rest))

    # Build merged trace records
    trace_merged: dict[str, dict] = {}
    for trace_id, entries in traces.items():
        merged = {
            "trace_id": trace_id,
            "line_indices": [],
            "identifiers": [],
            "resource_id": None,
            "service": None,
            "record_time": None,
            "absence": False,
            "presence": False,
            "event": None,
        }
        for idx, ts_str, data, rest in entries:
            merged["line_indices"].append(idx)
            if ts_str and merged["record_time"] is None:
                merged["record_time"] = parse_iso_utc(ts_str)
            if data:
                merged["service"] = data.get("service") or data.get("logger") or merged["service"]
                rid = _resource_from_event(data)
                if rid:
                    merged["resource_id"] = rid
                for key_field in ("lookup_key", "correlation_key"):
                    key_val = data.get(key_field)
                    if key_val and key_val != "null":
                        # Treat long hex-looking strings as hashes
                        if isinstance(key_val, str) and re.fullmatch(r"[0-9a-fA-F]{32,}", key_val):
                            merged["identifiers"].append({"kind": "hash", "value": key_val, "normalized": normalize_hash(key_val)})
                        else:
                            merged["identifiers"].extend(_collect_identifiers(None, key_val))
                merged["identifiers"].extend(_collect_identifiers(data, rest))
                ev = data.get("event") or ""
                if "completed" in ev or "lookup" in ev:
                    merged["event"] = ev
                if _is_absence_signal(data, rest):
                    merged["absence"] = True
                if _is_presence_signal(data, rest):
                    merged["presence"] = True
        # Deduplicate identifiers
        seen = set()
        unique = []
        for ident in merged["identifiers"]:
            key = (ident["kind"], ident["normalized"])
            if key not in seen and key[1]:
                seen.add(key)
                unique.append(ident)
        merged["identifiers"] = unique
        trace_merged[trace_id] = merged

    # Emit facts from merged traces
    emitted_trace_keys = set()
    for trace_id, merged in trace_merged.items():
        if not merged["resource_id"] and not merged["identifiers"]:
            continue
        if not merged["resource_id"]:
            continue

        category = _data_category_from_resource(merged["resource_id"]) or "USER_PROFILE"
        system_id = merged["service"]

        state = None
        if merged["absence"]:
            state = "ABSENT"
        elif merged["presence"]:
            state = "PRESENT"

        fact = Fact(
            source_kind="file",
            source_id=file_id,
            source_path=str(path),
            locator=f"trace:{trace_id}",
            system_id=system_id,
            resource_id=merged["resource_id"],
            data_category=category,
            fields_present=["trace"],
            identifiers=merged["identifiers"],
            record_time=merged["record_time"],
            capture_time=captured_at,
            raw_excerpt=f"trace {trace_id} resource={merged['resource_id']} state={state}",
            extractor="log-trace",
            confidence=1.0,
        )
        if state:
            fact.fields_present.append(f"state:{state}")
        facts.append(fact)
        emitted_trace_keys.add(trace_id)

    # Emit facts for standalone lines not in a trace (or no trace_id)
    for idx, ts_str, data, rest, raw_line in lines_parsed:
        trace_id = (data or {}).get("trace_id") if isinstance(data, dict) else None
        if trace_id and trace_id in emitted_trace_keys:
            continue

        resource_id = _resource_from_event(data or rest)
        if not resource_id:
            continue

        identifiers = _collect_identifiers(data, rest)
        if not identifiers:
            continue

        category = _data_category_from_resource(resource_id) or "USER_PROFILE"
        system_id = (data or {}).get("service") if isinstance(data, dict) else None
        if not system_id:
            m = re.search(r"service=(\w+)", rest)
            if m:
                system_id = m.group(1)

        state = None
        if _is_absence_signal(data, rest):
            state = "ABSENT"
        elif _is_presence_signal(data, rest):
            state = "PRESENT"

        fact = Fact(
            source_kind="file",
            source_id=file_id,
            source_path=str(path),
            locator=f"line:{idx}",
            system_id=system_id,
            resource_id=resource_id,
            data_category=category,
            fields_present=["line"],
            identifiers=identifiers,
            record_time=parse_iso_utc(ts_str),
            capture_time=captured_at,
            raw_excerpt=raw_line[:500],
            extractor="log-regex",
            confidence=1.0,
        )
        if state:
            fact.fields_present.append(f"state:{state}")
        facts.append(fact)

    return facts
