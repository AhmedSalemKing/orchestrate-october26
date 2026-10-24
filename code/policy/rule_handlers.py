"""Policy rule handlers: given current state, return expected (phase, operation, state, evidence_required)."""
from __future__ import annotations

from config import VALID_COMBOS


def _cat(action: str, current_state: str, category: str | None = None) -> list[tuple[str, str, str, bool]]:
    """Return list of (phase, operation, state, evidence_required)."""
    # Map required action to expected final state
    final_state = {
        "DELETE": "ABSENT",
        "REDACT": "REDACTED",
        "ANONYMIZE": "ANONYMIZED",
        "RETAIN": "PRESENT",
    }.get(action, current_state)

    # If action is RETAIN, only verification
    if action == "RETAIN":
        return [("VERIFICATION", f"VERIFY_RECORD_{final_state}", final_state, True)]

    if current_state == final_state:
        return [("VERIFICATION", f"VERIFY_RECORD_{final_state}", final_state, True)]
    else:
        finding_op = "REPORT_REMAINING_RECORD"
        if action in ("REDACT", "ANONYMIZE") or category == "ACCOUNT_TOMBSTONE":
            finding_op = "REPORT_EXPOSED_PII"
        return [
            ("FINDING", finding_op, "PRESENT", True),
            ("REMEDIATION", f"{action}_RECORD", final_state, False),
            ("VERIFICATION", f"VERIFY_RECORD_{final_state}", final_state, False),
        ]


def expected_steps(data_category: str, current_state: str, rules) -> list[tuple[str, str, str, bool]]:
    """Return expected step tuples for a data category and observed state."""
    # Special categories not present in deletion_rules.csv must be handled first.

    # Special handling for ACCOUNT_TOMBSTONE: always REDACT
    if data_category == "ACCOUNT_TOMBSTONE":
        if current_state == "REDACTED":
            return [("VERIFICATION", "VERIFY_RECORD_REDACTED", "REDACTED", True)]
        return [
            ("FINDING", "REPORT_EXPOSED_PII", "PRESENT", True),
            ("REMEDIATION", "REDACT_RECORD", "REDACTED", False),
            ("VERIFICATION", "VERIFY_RECORD_REDACTED", "REDACTED", False),
        ]

    # Special handling for SUPPORT_ATTACHMENT
    if data_category == "SUPPORT_ATTACHMENT":
        if current_state == "ABSENT":
            return [("VERIFICATION", "VERIFY_RECORD_ABSENT", "ABSENT", True)]
        return [
            ("FINDING", "REPORT_REMAINING_RECORD", "PRESENT", True),
            ("REMEDIATION", "DELETE_RECORD", "ABSENT", False),
            ("VERIFICATION", "VERIFY_RECORD_ABSENT", "ABSENT", False),
        ]

    # Special handling for BACKUP_ARCHIVE
    if data_category == "BACKUP_ARCHIVE":
        if current_state == "BLOCKED":
            return [("VERIFICATION", "VERIFY_RESTORE_BLOCKED", "BLOCKED", True)]
        return [
            ("FINDING", "REPORT_RESTORE_RISK", "ACTIVE", True),
            ("REMEDIATION", "BLOCK_RESTORE", "BLOCKED", False),
            ("VERIFICATION", "VERIFY_RESTORE_BLOCKED", "BLOCKED", False),
        ]

    # DATA_FLOW is not in rules but handled by activity
    if data_category == "DATA_FLOW":
        if current_state == "DISABLED":
            return [("VERIFICATION", "VERIFY_DATA_FLOW_DISABLED", "DISABLED", True)]
        return [
            ("FINDING", "REPORT_ACTIVE_DATA_FLOW", "ACTIVE", True),
            ("REMEDIATION", "DISABLE_DATA_FLOW", "DISABLED", False),
            ("VERIFICATION", "VERIFY_DATA_FLOW_DISABLED", "DISABLED", False),
        ]

    action = rules.action_for(data_category)
    return _cat(action, current_state, data_category)
