"""Validation functions for steps and output rows."""
from __future__ import annotations

from config import ALLOWED_STATUSES, STEP_KEYS, PHASE_ORDER, OP_ORDER, VALID_COMBOS


def validate_step_object(step: dict) -> None:
    """Validate a single step object."""
    keys = set(step.keys())
    if keys != STEP_KEYS:
        raise ValueError(f"Step has wrong keys: {keys}")
    if not isinstance(step["step_no"], int):
        raise ValueError(f"step_no must be int: {step['step_no']}")
    phase = step["phase"]
    operation = step["operation"]
    state = step["state"]
    if (phase, operation, state) not in VALID_COMBOS:
        raise ValueError(f"Invalid (phase, operation, state) combo: {(phase, operation, state)}")


def validate_step_sequence(steps: list[dict], expect_phases: list[str] | None = None) -> None:
    """Validate ordering of a step sequence."""
    prev = None
    for i, s in enumerate(steps, 1):
        validate_step_object(s)
        if s["step_no"] != i:
            raise ValueError(f"step_no out of sequence: expected {i}, got {s['step_no']}")
        if prev is not None:
            key_prev = (PHASE_ORDER[prev["phase"]], OP_ORDER[prev["phase"]][prev["operation"]], prev["system_id"] or "", prev["resource_id"] or "")
            key_cur = (PHASE_ORDER[s["phase"]], OP_ORDER[s["phase"]][s["operation"]], s["system_id"] or "", s["resource_id"] or "")
            if key_cur < key_prev:
                raise ValueError(f"Steps out of order: {prev} -> {s}")
            if key_cur == key_prev:
                raise ValueError(f"Duplicate step: {s}")
        prev = s
    if expect_phases:
        actual = [s["phase"] for s in steps]
        if actual != expect_phases:
            raise ValueError(f"Phase sequence mismatch: expected {expect_phases}, got {actual}")


def validate_evidence_ref(evidence_id: str, ctx: dict) -> None:
    """Validate that evidence_id exists and (if file) is not captured after cutoff."""
    if evidence_id == "":
        return
    allowed = ctx.get("allowed_ids", set())
    if evidence_id not in allowed:
        raise ValueError(f"Unknown evidence_id: {evidence_id}")
    # File capture time check is done per-case in validate_row


def validate_row(case_id: str, status: str, steps: list[dict], ctx: dict) -> None:
    """Validate a full output row against the contract."""
    if status not in ALLOWED_STATUSES:
        raise ValueError(f"Invalid status for {case_id}: {status}")
    if status == "NOT_APPLICABLE":
        if steps:
            raise ValueError(f"NOT_APPLICABLE must have empty steps for {case_id}")
        return

    case = ctx["cases"][case_id]
    allowed_ids = ctx["allowed_ids"]

    # Build expected phase sequence based on status
    if status == "COMPLETE":
        # Only VERIFICATION steps with non-empty evidence
        for s in steps:
            if s["phase"] != "VERIFICATION":
                raise ValueError(f"COMPLETE row {case_id} has non-VERIFICATION step: {s}")
            if s["evidence_id"] == "":
                raise ValueError(f"COMPLETE row {case_id} has empty evidence_id: {s}")
            validate_evidence_ref(s["evidence_id"], ctx)
    else:  # INCOMPLETE
        # Must have at least one FINDING with evidence and one REMEDIATION
        has_finding = any(s["phase"] == "FINDING" and s["evidence_id"] != "" for s in steps)
        has_remediation = any(s["phase"] == "REMEDIATION" for s in steps)
        if not has_finding:
            raise ValueError(f"INCOMPLETE row {case_id} lacks FINDING with evidence")
        if not has_remediation:
            raise ValueError(f"INCOMPLETE row {case_id} lacks REMEDIATION step")
        for s in steps:
            if s["phase"] == "FINDING" and s["evidence_id"] == "":
                raise ValueError(f"FINDING step lacks evidence for {case_id}: {s}")
            if s["phase"] == "REMEDIATION" and s["evidence_id"] != "":
                raise ValueError(f"REMEDIATION step must have empty evidence for {case_id}: {s}")
            if s["phase"] == "VERIFICATION" and s["evidence_id"] != "":
                raise ValueError(f"INCOMPLETE VERIFICATION must have empty evidence for {case_id}: {s}")
            if s["evidence_id"]:
                validate_evidence_ref(s["evidence_id"], ctx)

    validate_step_sequence(steps)


def validate_output_file(path: str, ctx: dict) -> None:
    """Validate the whole output CSV file."""
    import csv
    import json
    from dataload.timeutil import parse_iso_utc

    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames != ["case_id", "deletion_status", "steps_json"]:
            raise ValueError(f"Bad header: {reader.fieldnames}")
        rows = list(reader)

    if len(rows) != 518:
        raise ValueError(f"Expected 518 rows, got {len(rows)}")

    case_ids = [r["case_id"] for r in rows]
    if case_ids != sorted(case_ids):
        raise ValueError("Rows not sorted by case_id")
    if len(set(case_ids)) != len(case_ids):
        raise ValueError("Duplicate case_ids")

    expected_ids = ctx.get("deletion_request_ids", set(ctx["cases"].keys()))
    if set(case_ids) != expected_ids:
        raise ValueError(f"Case id mismatch: missing={expected_ids - set(case_ids)}, extra={set(case_ids) - expected_ids}")

    for r in rows:
        steps = json.loads(r["steps_json"])
        if not isinstance(steps, list):
            raise ValueError(f"steps_json not a list for {r['case_id']}")
        validate_row(r["case_id"], r["deletion_status"], steps, ctx)
