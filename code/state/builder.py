"""Build per-case state from facts and activity."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from identity.resolver import IdentityContext, resolve
from evidence.facts import Fact
from dataload.normalization import normalize_user_id
from dataload.timeutil import is_before_or_equal


@dataclass
class RecordGroup:
    system_id: str
    resource_id: str
    data_category: str
    facts: list = field(default_factory=list)
    effective_state: str | None = None
    from_activity: bool = False


@dataclass
class CaseState:
    case: dict
    idctx: IdentityContext
    intent: str
    groups: list[RecordGroup] = field(default_factory=list)
    activity_linked: list[dict] = field(default_factory=list)
    inferred_status_hint: str = "COMPLETE"
    expected_account_resource: str | None = None


def _matches_idctx(fact, idctx: IdentityContext) -> bool:
    for ident in fact.identifiers:
        kind = ident["kind"]
        norm = ident["normalized"]
        if not norm:
            continue
        if kind == "email" and norm in idctx.all_emails:
            return True
        if kind == "phone" and norm in idctx.all_phones:
            return True
        if kind == "hash" and norm in idctx.all_hashes:
            return True
        if kind == "user_id" and norm in idctx.all_user_ids:
            return True
        if kind == "name" and norm in idctx.all_names:
            return True
    return False


def _has_contradictory_idents(fact, idctx: IdentityContext, all_known_idents: set[str]) -> bool:
    """Return True if fact contains a non-empty identifier known to belong to someone else."""
    for ident in fact.identifiers:
        kind = ident["kind"]
        norm = ident["normalized"]
        if not norm:
            continue
        if kind in ("email", "phone", "hash", "user_id", "name") and norm in all_known_idents:
            # It's known globally; if it's not in this case's idctx, it belongs to someone else
            if kind == "email" and norm not in idctx.all_emails:
                return True
            if kind == "phone" and norm not in idctx.all_phones:
                return True
            if kind == "hash" and norm not in idctx.all_hashes:
                return True
            if kind == "user_id" and norm not in idctx.all_user_ids:
                return True
            if kind == "name" and norm not in idctx.all_names:
                return True
    return False


def _discover_account_resource(case, idctx, all_facts, all_activity) -> str | None:
    """Find the primary account resource_id for this case."""
    for fact in all_facts:
        rid = fact.resource_id
        if not rid or not rid.startswith("account_"):
            continue
        for ident in fact.identifiers:
            if ident["kind"] == "email" and ident["normalized"] in idctx.all_emails:
                return rid
            if ident["kind"] == "user_id" and ident["normalized"] in idctx.all_user_ids:
                return rid
            if ident["kind"] == "phone" and ident["normalized"] in idctx.all_phones:
                return rid

    for act in all_activity:
        rid = act.get("resource_id")
        if not rid or not rid.startswith("account_"):
            continue
        details = act.get("details", "")
        if any(uid in details for uid in idctx.all_user_ids):
            return rid
        if any(email in details for email in idctx.all_emails):
            return rid

    if idctx.all_user_ids:
        for uid in idctx.all_user_ids:
            num = uid.split("_")[-1]
            try:
                return f"account_{int(num):03d}"
            except ValueError:
                pass
    return None


def _effective_state_for_group(facts: list, category: str) -> str:
    """Infer effective state at cutoff from facts in chronological order."""
    def sort_key(f):
        epoch = datetime.min.replace(tzinfo=timezone.utc)
        rt = f.record_time or epoch
        ct = f.capture_time or epoch
        return (rt, ct)

    sorted_facts = sorted(facts, key=sort_key)

    # Explicit state annotations and status fields
    for f in reversed(sorted_facts):
        if "state:ABSENT" in f.fields_present:
            return "ABSENT"
        if "state:PRESENT" in f.fields_present:
            return "PRESENT"
        if "state:DISABLED" in f.fields_present:
            return "DISABLED"
        if "state:BLOCKED" in f.fields_present:
            return "BLOCKED"
        # Interpret account_status / status values carried in fields_present
        status_vals = [fld.split(":", 1)[1].lower() for fld in f.fields_present if fld.startswith("status:")]
        for sv in status_vals:
            if sv in ("active", "present", "found"):
                return "PRESENT"
            if sv in ("deleted", "not_found", "absent", "removed"):
                return "ABSENT"

    # Data flow / backup heuristics
    if category == "DATA_FLOW":
        for f in reversed(sorted_facts):
            text = f.raw_excerpt.lower()
            if "enabled=false" in text or "disabled" in text or "stopped" in text:
                return "DISABLED"
            if "enabled=true" in text or "active" in text:
                return "ACTIVE"
        return "ACTIVE"

    if category == "BACKUP_ARCHIVE":
        for f in reversed(sorted_facts):
            text = f.raw_excerpt.lower()
            if "restore_allowed=false" in text or "blocked" in text:
                return "BLOCKED"
            if "restore_allowed=true" in text or "can still be restored" in text:
                return "ACTIVE"
        return "ACTIVE"

    # Tombstone
    if category == "ACCOUNT_TOMBSTONE":
        for f in sorted_facts:
            pii_fields = {"email", "phone", "email_hash", "name"}
            present_pii = [fld for fld in f.fields_present if fld in pii_fields]
            if present_pii:
                return "PRESENT"
        return "REDACTED"

    # Analytics/telemetry attributable check
    if category in ("ANALYTICS_PROFILE", "PRODUCT_TELEMETRY"):
        for f in sorted_facts:
            if f.has_identifier("email", None) or f.has_identifier("phone", None) or f.has_identifier("hash", None):
                return "PRESENT"
        return "ANONYMIZED"

    # Support message / email log exposed PII check
    if category in ("SUPPORT_MESSAGE", "EMAIL_DELIVERY_LOG"):
        for f in sorted_facts:
            if f.has_identifier("email", None) or f.has_identifier("phone", None) or f.has_identifier("name", None):
                return "PRESENT"
        return "REDACTED"

    # Delete-required categories
    delete_categories = {"USER_PROFILE", "SECONDARY_IDENTIFIER", "SEARCH_INDEX_ENTRY", "CACHE_ENTRY", "USER_EXPORT", "MARKETING_PROFILE", "SUPPORT_ATTACHMENT"}
    if category in delete_categories:
        if sorted_facts:
            return "PRESENT"
        return "ABSENT"

    # Retained records
    if category in ("SECURITY_AUDIT_LOG", "LEGAL_HOLD_RECORD"):
        if sorted_facts:
            return "PRESENT"
        return "ABSENT"

    if sorted_facts:
        return "PRESENT"
    return "ABSENT"


def _resource_kinds(rid: str | None) -> bool:
    if not rid:
        return False
    return any(rid.startswith(p) for p in (
        "account_", "search_", "analytics_", "support_", "export_",
        "backup_", "data_flow_", "cache_", "email_delivery_", "audit_record_",
        "tombstone_", "legal_",
    ))


def build_state(case, bundle, index, rules) -> CaseState:
    cutoff = case["audit_at_dt"]
    idctx = resolve(case, bundle.user_identities, bundle.user_audit_log, index.facts)

    # Pre-compute global known identifiers to detect cross-user contamination
    all_known_idents: set[str] = set()
    for ident in ("email", "phone", "hash", "user_id", "name"):
        for row in bundle.user_identities:
            if ident == "email" and row.get("email"):
                all_known_idents.add(row["email"].strip().lower())
            elif ident == "phone" and row.get("phone"):
                from dataload.normalization import normalize_phone
                np = normalize_phone(row["phone"])
                if np:
                    all_known_idents.add(np)
            elif ident == "hash" and row.get("email_hash"):
                all_known_idents.add(row["email_hash"].strip().lower())
            elif ident == "user_id" and row.get("user_id"):
                all_known_idents.add(normalize_user_id(row["user_id"]))
            elif ident == "name" and row.get("name"):
                from dataload.normalization import normalize_name
                nn = normalize_name(row["name"])
                if nn:
                    all_known_idents.add(nn)
    # Include audit log historical values
    for row in bundle.user_audit_log:
        uid = normalize_user_id(row["user_id"])
        field = row["field_name"].lower()
        for val in (row.get("old_value"), row.get("new_value")):
            if not val:
                continue
            if field == "email":
                all_known_idents.add(val.strip().lower())
            elif field == "phone":
                from dataload.normalization import normalize_phone
                np = normalize_phone(val)
                if np:
                    all_known_idents.add(np)
            elif field == "email_hash":
                all_known_idents.add(val.strip().lower())

    def _fact_is_timely(fact: Fact) -> bool:
        # Log files have reliable per-event record_time; use it.
        # For other file types, trust capture_time (snapshot / export time).
        if fact.source_path and fact.source_path.lower().endswith(".log"):
            if fact.record_time and fact.record_time > cutoff:
                return False
            if not fact.record_time and fact.capture_time and fact.capture_time > cutoff:
                return False
            return True
        if fact.record_time and fact.record_time > cutoff:
            return False
        if fact.capture_time and fact.capture_time > cutoff:
            return False
        return True

    # First pass: facts matching identity.
    identity_matched_facts = []
    candidate_resources: set[str] = set()
    for fact in index.facts:
        if not _fact_is_timely(fact):
            continue
        if _matches_idctx(fact, idctx):
            identity_matched_facts.append(fact)
            if fact.resource_id:
                candidate_resources.add(fact.resource_id)

    # Discover primary account resource
    expected_account = _discover_account_resource(case, idctx, index.facts, bundle.system_activity)
    if expected_account:
        candidate_resources.add(expected_account)

    # Link activity rows and discover additional resources from the deletion workflow.
    # Tight attribution: an activity is linked if (a) its resource is already a candidate,
    # (b) its details contain case identifiers, or (c) it is a deletion-worker operation
    # whose event_time is close to the case's reported_at (the workflow that produced the claim).
    activity_linked = []
    reported_at = case.get("reported_at_dt")
    attribution_window = timedelta(hours=4)

    # Mutating / policy-action event types that we can attribute to a deletion workflow.
    deletion_event_types = {
        "DELETE_RECORD", "ANONYMIZE_RECORD", "REDACT_RECORD",
        "DISABLE_DATA_FLOW", "BLOCK_RESTORE", "RETAIN_RECORD",
    }
    # Diagnostic event types only when the resource is already a candidate.
    diagnostic_event_types = {"CHECK_DATA_FLOW", "CHECK_RESTORE_ACCESS", "SYNC_RECORD"}

    for act in bundle.system_activity:
        et = act["event_time_dt"]
        if et and et > cutoff:
            continue

        resource_id = act.get("resource_id")
        is_linked = False

        # (a) resource already a candidate
        if resource_id and resource_id in candidate_resources:
            is_linked = True
        else:
            # (b) identifiers in details
            details = act.get("details", "")
            for uid in idctx.all_user_ids:
                if uid and uid in details:
                    is_linked = True
                    break
            if not is_linked:
                for email in idctx.all_emails:
                    if email and email in details:
                        is_linked = True
                        break

        # (c) deletion-worker operation near reported_at for a resource relevant to deletion.
        # Analytics resources are only attributed when the request explicitly mentions
        # analytics or anonymous statistics, to avoid cross-case contamination.
        if not is_linked and resource_id and _resource_kinds(resource_id):
            if act.get("event_type") in deletion_event_types:
                if reported_at and (reported_at - attribution_window) <= et <= (reported_at + attribution_window):
                    if resource_id.startswith("analytics_"):
                        text = (case.get("request_text") or "").lower()
                        if any(kw in text for kw in ("analytics", "statistics", "statistical", "anonymous", "anonymized")):
                            is_linked = True
                            candidate_resources.add(resource_id)
                    else:
                        is_linked = True
                        candidate_resources.add(resource_id)

        if is_linked:
            activity_linked.append(act)
            if resource_id:
                candidate_resources.add(resource_id)

    # Second pass: collect facts for candidate resources or identity
    relevant_facts = list(identity_matched_facts)
    seen_fact_keys = {(f.source_kind, f.source_id, f.locator) for f in relevant_facts}
    for fact in index.facts:
        key = (fact.source_kind, fact.source_id, fact.locator)
        if key in seen_fact_keys:
            continue
        if not _fact_is_timely(fact):
            continue
        if fact.resource_id and fact.resource_id in candidate_resources:
            relevant_facts.append(fact)
            seen_fact_keys.add(key)

    # Generate absence facts from SQL snapshots if expected account not present
    if expected_account:
        for fact in index.facts:
            if fact.source_kind != "file":
                continue
            if not _fact_is_timely(fact):
                continue
            if fact.data_category != "USER_PROFILE":
                continue
            if not (fact.source_path and (".sql" in fact.source_path.lower())):
                continue
            if fact.system_id not in ("account_service", "primary", "failover_replica", "regional_replica", "reporting_replica", "sql_snapshot"):
                continue
            file_facts = [f for f in index.facts if f.source_id == fact.source_id and f.system_id == fact.system_id and f.data_category == "USER_PROFILE"]
            file_resource_ids = {f.resource_id for f in file_facts}
            if expected_account in file_resource_ids:
                continue
            uid = next(iter(idctx.all_user_ids)) if idctx.all_user_ids else ""
            absent_fact = Fact(
                source_kind="file",
                source_id=fact.source_id,
                source_path=fact.source_path,
                locator=f"{fact.locator.split(':')[0]}:expected_absent",
                system_id=fact.system_id,
                resource_id=expected_account,
                data_category="USER_PROFILE",
                fields_present=["state:ABSENT"],
                identifiers=[{"kind": "user_id", "value": uid, "normalized": uid}],
                record_time=fact.capture_time,
                capture_time=fact.capture_time,
                raw_excerpt=f"Expected account {expected_account} not found in {fact.system_id} snapshot",
                extractor="sql-absence",
                confidence=1.0,
            )
            if _matches_idctx(absent_fact, idctx):
                relevant_facts.append(absent_fact)

    # Group facts
    grouped = defaultdict(list)
    for fact in relevant_facts:
        key = (fact.system_id or "unknown", fact.resource_id or "unknown", fact.data_category or "USER_PROFILE")
        grouped[key].append(fact)

    groups = []
    for (system_id, resource_id, category), facts in grouped.items():
        if resource_id == "unknown":
            continue
        state = _effective_state_for_group(facts, category)

        # Determine if this group is genuinely tied to the case
        identity_match = any(_matches_idctx(f, idctx) for f in facts)
        activity_discovered = resource_id in candidate_resources and not identity_match
        if activity_discovered:
            # Reject if any fact points to a different known user
            if any(_has_contradictory_idents(f, idctx, all_known_idents) for f in facts):
                continue

        groups.append(RecordGroup(
            system_id=system_id,
            resource_id=resource_id,
            data_category=category,
            facts=facts,
            effective_state=state,
            from_activity=activity_discovered,
        ))

    # Retain only one primary account group to avoid reporting stale or decoy account lookups.
    if expected_account:
        groups = [g for g in groups if g.data_category != "USER_PROFILE" or g.resource_id == expected_account]
    else:
        # If no expected account, keep at most one account group (prefer one with explicit state).
        account_groups = [g for g in groups if g.data_category == "USER_PROFILE"]
        if len(account_groups) > 1:
            # Prefer account groups with explicit PRESENT/ABSENT state
            best = max(account_groups, key=lambda g: (g.effective_state in ("PRESENT", "ABSENT"), len(g.facts)))
            groups = [g for g in groups if g.data_category != "USER_PROFILE" or g.resource_id == best.resource_id]

    # Add DATA_FLOW groups from activity
    active_flows = set()
    disabled_flows = set()
    for act in activity_linked:
        etype = act["event_type"]
        rid = act.get("resource_id")
        if not rid or not rid.startswith("data_flow_"):
            continue
        if etype == "DISABLE_DATA_FLOW":
            disabled_flows.add(rid)
        elif etype in ("CHECK_DATA_FLOW", "SYNC_RECORD"):
            active_flows.add(rid)
    existing_flow_resources = {g.resource_id for g in groups if g.data_category == "DATA_FLOW"}
    for rid in active_flows:
        if rid in existing_flow_resources or rid in disabled_flows:
            continue
        groups.append(RecordGroup(
            system_id="integration_service",
            resource_id=rid,
            data_category="DATA_FLOW",
            facts=[],
            effective_state="ACTIVE",
        ))

    # Add BACKUP_ARCHIVE groups from activity
    active_backups = set()
    blocked_backups = set()
    for act in activity_linked:
        etype = act["event_type"]
        rid = act.get("resource_id")
        if not rid or not rid.startswith("backup_"):
            continue
        if etype == "BLOCK_RESTORE":
            blocked_backups.add(rid)
        elif etype == "CHECK_RESTORE_ACCESS":
            active_backups.add(rid)
    existing_backup_resources = {g.resource_id for g in groups if g.data_category == "BACKUP_ARCHIVE"}
    for rid in active_backups:
        if rid in existing_backup_resources or rid in blocked_backups:
            continue
        groups.append(RecordGroup(
            system_id="backup_service",
            resource_id=rid,
            data_category="BACKUP_ARCHIVE",
            facts=[],
            effective_state="ACTIVE",
        ))

    # Infer status hint
    hint = "COMPLETE"
    for g in groups:
        if g.data_category in ("USER_PROFILE", "SEARCH_INDEX_ENTRY", "CACHE_ENTRY", "USER_EXPORT", "MARKETING_PROFILE", "SUPPORT_ATTACHMENT") and g.effective_state != "ABSENT":
            hint = "INCOMPLETE"
            break
        if g.data_category in ("SUPPORT_MESSAGE", "EMAIL_DELIVERY_LOG") and g.effective_state != "REDACTED":
            hint = "INCOMPLETE"
            break
        if g.data_category in ("ANALYTICS_PROFILE", "PRODUCT_TELEMETRY") and g.effective_state != "ANONYMIZED":
            hint = "INCOMPLETE"
            break
        if g.data_category == "ACCOUNT_TOMBSTONE" and g.effective_state != "REDACTED":
            hint = "INCOMPLETE"
            break
        if g.data_category == "DATA_FLOW" and g.effective_state != "DISABLED":
            hint = "INCOMPLETE"
            break
        if g.data_category == "BACKUP_ARCHIVE" and g.effective_state != "BLOCKED":
            hint = "INCOMPLETE"
            break

    return CaseState(
        case=case,
        idctx=idctx,
        intent="DELETION",
        groups=groups,
        activity_linked=activity_linked,
        inferred_status_hint=hint,
        expected_account_resource=expected_account,
    )
