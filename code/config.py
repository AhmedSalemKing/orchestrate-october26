"""Configuration and path resolution."""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / "dataset"
CODE = ROOT / "code"

# Optional LLM configuration (not used for status/step decisions)
LLM_PROVIDER = os.environ.get("LLM_PROVIDER", "").strip()
LLM_MODEL = os.environ.get("LLM_MODEL", "").strip()
# Provider-specific API keys are read from env only and never logged.

# Time format used throughout the project
ISO_FMT = "%Y-%m-%dT%H:%M:%SZ"

# Allowed statuses and step fields
ALLOWED_STATUSES = {"COMPLETE", "INCOMPLETE", "NOT_APPLICABLE"}

STEP_KEYS = {"step_no", "phase", "system_id", "resource_id", "operation", "state", "evidence_id"}

PHASE_ORDER = {"FINDING": 0, "REMEDIATION": 1, "VERIFICATION": 2}

OP_ORDER = {
    "FINDING": {
        "REPORT_REMAINING_RECORD": 0,
        "REPORT_EXPOSED_PII": 1,
        "REPORT_ACTIVE_DATA_FLOW": 2,
        "REPORT_RESTORE_RISK": 3,
    },
    "REMEDIATION": {
        "DISABLE_DATA_FLOW": 0,
        "BLOCK_RESTORE": 1,
        "DELETE_RECORD": 2,
        "REDACT_RECORD": 3,
        "ANONYMIZE_RECORD": 4,
    },
    "VERIFICATION": {
        "VERIFY_RECORD_ABSENT": 0,
        "VERIFY_RECORD_PRESENT": 1,
        "VERIFY_RECORD_REDACTED": 2,
        "VERIFY_RECORD_ANONYMIZED": 3,
        "VERIFY_DATA_FLOW_DISABLED": 4,
        "VERIFY_RESTORE_BLOCKED": 5,
    },
}

VALID_COMBOS = {
    ("FINDING", "REPORT_REMAINING_RECORD", "PRESENT"),
    ("FINDING", "REPORT_EXPOSED_PII", "PRESENT"),
    ("FINDING", "REPORT_ACTIVE_DATA_FLOW", "ACTIVE"),
    ("FINDING", "REPORT_RESTORE_RISK", "ACTIVE"),
    ("REMEDIATION", "DISABLE_DATA_FLOW", "DISABLED"),
    ("REMEDIATION", "BLOCK_RESTORE", "BLOCKED"),
    ("REMEDIATION", "DELETE_RECORD", "ABSENT"),
    ("REMEDIATION", "REDACT_RECORD", "REDACTED"),
    ("REMEDIATION", "ANONYMIZE_RECORD", "ANONYMIZED"),
    ("VERIFICATION", "VERIFY_RECORD_ABSENT", "ABSENT"),
    ("VERIFICATION", "VERIFY_RECORD_PRESENT", "PRESENT"),
    ("VERIFICATION", "VERIFY_RECORD_REDACTED", "REDACTED"),
    ("VERIFICATION", "VERIFY_RECORD_ANONYMIZED", "ANONYMIZED"),
    ("VERIFICATION", "VERIFY_DATA_FLOW_DISABLED", "DISABLED"),
    ("VERIFICATION", "VERIFY_RESTORE_BLOCKED", "BLOCKED"),
}

IDENTIFIER_FIELDS = {"email", "phone", "email_hash", "user_id", "name"}
