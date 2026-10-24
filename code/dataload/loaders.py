"""CSV and dataset loaders."""
from __future__ import annotations

import csv
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from config import ROOT, DATASET
from dataload.timeutil import parse_iso_utc


def load_csv(path: Path, expected_columns: set[str]) -> list[dict[str, str]]:
    """Load a CSV file, validate columns, and warn on duplicate IDs."""
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames is None:
            raise ValueError(f"No header in {path}")
        missing = expected_columns - set(reader.fieldnames)
        extra = set(reader.fieldnames) - expected_columns
        if missing:
            raise ValueError(f"{path} missing columns: {missing}")
        if extra:
            # Allow extra columns with a warning
            print(f"Warning: {path} has extra columns: {extra}", file=sys.stderr)
        rows = [dict(r) for r in reader]

    # Detect duplicate IDs if first expected column looks like an id column
    id_col = sorted(expected_columns)[0]
    if id_col.endswith("_id"):
        seen = set()
        for r in rows:
            val = r[id_col]
            if val in seen:
                print(f"Warning: duplicate {id_col}={val} in {path}", file=sys.stderr)
            seen.add(val)
    return rows


def load_evidence_manifest(path: Path) -> list[dict[str, Any]]:
    """Load evidence_files.csv and verify paths are under dataset."""
    rows = load_csv(path, {"file_id", "file_path", "origin", "captured_at"})
    result = []
    for r in rows:
        fp = DATASET / r["file_path"]
        if not fp.resolve().is_relative_to(DATASET.resolve()):
            raise ValueError(f"Evidence path escapes dataset: {fp}")
        if not fp.exists():
            raise ValueError(f"Evidence file missing: {fp}")
        r["resolved_path"] = fp
        r["captured_at_dt"] = parse_iso_utc(r["captured_at"])
        result.append(r)
    return result


@dataclass
class DataBundle:
    deletion_requests: list[dict] = field(default_factory=list)
    sample_deletion_requests: list[dict] = field(default_factory=list)
    sample_output: list[dict] = field(default_factory=list)
    user_identities: list[dict] = field(default_factory=list)
    user_audit_log: list[dict] = field(default_factory=list)
    system_activity: list[dict] = field(default_factory=list)
    deletion_rules: list[dict] = field(default_factory=list)
    evidence_files: list[dict] = field(default_factory=list)

    @staticmethod
    def load(dataset_dir: Path = DATASET) -> "DataBundle":
        b = DataBundle()
        b.deletion_requests = load_csv(dataset_dir / "deletion_requests.csv", {
            "case_id", "email", "requested_at", "reported_status", "reported_at", "audit_at", "request_text"
        })
        b.sample_deletion_requests = load_csv(dataset_dir / "sample_deletion_requests.csv", {
            "case_id", "email", "requested_at", "reported_status", "reported_at", "audit_at", "request_text"
        })
        b.sample_output = load_csv(dataset_dir / "sample_output.csv", {
            "case_id", "deletion_status", "steps_json"
        })
        b.user_identities = load_csv(dataset_dir / "user_identities.csv", {
            "user_id", "name", "email", "phone", "email_hash", "updated_at"
        })
        b.user_audit_log = load_csv(dataset_dir / "user_audit_log.csv", {
            "audit_id", "user_id", "event_time", "field_name", "old_value", "new_value"
        })
        b.system_activity = load_csv(dataset_dir / "system_activity.csv", {
            "activity_id", "event_time", "event_type", "source_system", "target_system",
            "resource_id", "reported_result", "details"
        })
        b.deletion_rules = load_csv(dataset_dir / "deletion_rules.csv", {
            "rule_id", "data_category", "condition", "required_action"
        })
        b.evidence_files = load_evidence_manifest(dataset_dir / "evidence_files.csv")

        # Parse datetimes
        for r in b.deletion_requests:
            r["requested_at_dt"] = parse_iso_utc(r["requested_at"])
            r["reported_at_dt"] = parse_iso_utc(r["reported_at"])
            r["audit_at_dt"] = parse_iso_utc(r["audit_at"])
        for r in b.sample_deletion_requests:
            r["requested_at_dt"] = parse_iso_utc(r["requested_at"])
            r["reported_at_dt"] = parse_iso_utc(r["reported_at"])
            r["audit_at_dt"] = parse_iso_utc(r["audit_at"])
        for r in b.user_identities:
            r["updated_at_dt"] = parse_iso_utc(r["updated_at"])
        for r in b.user_audit_log:
            r["event_time_dt"] = parse_iso_utc(r["event_time"])
        for r in b.system_activity:
            r["event_time_dt"] = parse_iso_utc(r["event_time"])

        return b
