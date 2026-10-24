"""Decision engine: status and steps for a case."""
from __future__ import annotations

from state.builder import CaseState
from policy.engine import classify_request_intent
from policy.rule_handlers import expected_steps
from steps.ordering import sort_steps
from config import VALID_COMBOS


# Canonical service name for each data category.
_CANONICAL_SYSTEM = {
    "USER_PROFILE": "account_service",
    "SECONDARY_IDENTIFIER": "account_service",
    "ACCOUNT_TOMBSTONE": "identity_service",
    "SEARCH_INDEX_ENTRY": "search_service",
    "ANALYTICS_PROFILE": "analytics_platform",
    "PRODUCT_TELEMETRY": "analytics_platform",
    "SUPPORT_MESSAGE": "support_platform",
    "SUPPORT_ATTACHMENT": "support_platform",
    "USER_EXPORT": "export_service",
    "BACKUP_ARCHIVE": "backup_service",
    "DATA_FLOW": "integration_service",
    "CACHE_ENTRY": "cache_service",
    "EMAIL_DELIVERY_LOG": "email_delivery_service",
    "SECURITY_AUDIT_LOG": "security_service",
    "LEGAL_HOLD_RECORD": "legal_service",
    "MARKETING_PROFILE": "marketing_platform",
}


def _best_evidence(group) -> str:
    """Pick the best evidence_id for a group: earliest fact with a real file id."""
    for fact in group.facts:
        if fact.source_kind == "file" and fact.source_id:
            return fact.source_id
    return ""


def _step_key(s: dict) -> tuple:
    return (s["phase"], s["system_id"], s["resource_id"], s["operation"])


def decide(case, state: CaseState, rules, bundle, index) -> tuple[str, list[dict]]:
    intent = classify_request_intent(case["request_text"])
    if intent == "NON_DELETION":
        return "NOT_APPLICABLE", []

    findings = []
    remediations = []
    verifications = []

    for group in state.groups:
        category = group.data_category
        resource_id = group.resource_id

        # Skip placeholder groups
        if not resource_id or resource_id == "unknown":
            continue

        system_id = _CANONICAL_SYSTEM.get(category, group.system_id or "unknown")

        current_state = group.effective_state or "PRESENT"

        # Map retained records to PRESENT verification
        if category in ("SECURITY_AUDIT_LOG", "LEGAL_HOLD_RECORD"):
            current_state = "PRESENT"

        try:
            expected = expected_steps(category, current_state, rules)
        except ValueError:
            continue

        evidence_id = _best_evidence(group)

        for phase, operation, final_state, needs_evidence in expected:
            step = {
                "step_no": 0,  # assigned later
                "phase": phase,
                "system_id": system_id,
                "resource_id": resource_id,
                "operation": operation,
                "state": final_state,
                "evidence_id": "",
            }
            if phase == "FINDING":
                step["evidence_id"] = evidence_id
                findings.append(step)
            elif phase == "REMEDIATION":
                step["evidence_id"] = ""
                remediations.append(step)
            elif phase == "VERIFICATION":
                step["evidence_id"] = evidence_id if needs_evidence else ""
                verifications.append(step)

    # Deduplicate by (phase, system_id, resource_id, operation)
    seen = set()
    def dedupe(steps):
        out = []
        for s in steps:
            k = _step_key(s)
            if k in seen:
                continue
            seen.add(k)
            out.append(s)
        return out

    findings = dedupe(findings)
    remediations = dedupe(remediations)
    verifications = dedupe(verifications)

    if findings or remediations:
        status = "INCOMPLETE"
        for v in verifications:
            v["evidence_id"] = ""
    else:
        status = "COMPLETE"
        # Safety net: if any verification lacks evidence, downgrade
        if any(v["evidence_id"] == "" for v in verifications):
            status = "INCOMPLETE"
            for v in verifications:
                v["evidence_id"] = ""

    steps = sort_steps(findings + remediations + verifications)
    for i, s in enumerate(steps, 1):
        s["step_no"] = i

    return status, steps
