"""Identity resolver: per-user_id identifier collection."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from dataload.normalization import normalize_email, normalize_phone, normalize_hash, normalize_name, normalize_user_id


@dataclass
class IdentityContext:
    seed_email: str | None = None
    all_emails: set[str] = field(default_factory=set)
    all_phones: set[str] = field(default_factory=set)
    all_hashes: set[str] = field(default_factory=set)
    all_user_ids: set[str] = field(default_factory=set)
    all_names: set[str] = field(default_factory=set)
    provenance: list[dict] = field(default_factory=list)
    confidence: str = "UNKNOWN"  # EXACT, HISTORICAL, UNKNOWN

    def any_identifier(self) -> set[str]:
        return self.all_emails | self.all_phones | self.all_hashes | self.all_user_ids | self.all_names


def _collect_user_identifiers(identities, audit_log) -> dict[str, dict[str, set[str]]]:
    """For each user_id, collect all historical identifiers from identities + audit log."""
    users: dict[str, dict[str, set[str]]] = {}

    def ensure(uid):
        if uid not in users:
            users[uid] = {"emails": set(), "phones": set(), "hashes": set(), "names": set()}

    for row in identities:
        uid = normalize_user_id(row["user_id"])
        ensure(uid)
        if row.get("email"):
            users[uid]["emails"].add(normalize_email(row["email"]))
        if row.get("phone"):
            users[uid]["phones"].add(normalize_phone(row["phone"]))
        if row.get("email_hash"):
            users[uid]["hashes"].add(normalize_hash(row["email_hash"]))
        if row.get("name"):
            users[uid]["names"].add(normalize_name(row["name"]))

    for row in audit_log:
        uid = normalize_user_id(row["user_id"])
        ensure(uid)
        field = row["field_name"].lower()
        old = row["old_value"]
        new = row["new_value"]
        audit_id = row["audit_id"]
        if field == "email":
            if old:
                users[uid]["emails"].add(normalize_email(old))
            if new:
                users[uid]["emails"].add(normalize_email(new))
        elif field == "phone":
            if old:
                users[uid]["phones"].add(normalize_phone(old))
            if new:
                users[uid]["phones"].add(normalize_phone(new))
        elif field == "email_hash":
            if old:
                users[uid]["hashes"].add(normalize_hash(old))
            if new:
                users[uid]["hashes"].add(normalize_hash(new))

    return users


def resolve(case, identities, audit_log, facts: list[Any] | None = None) -> IdentityContext:
    """Resolve identity context for a case by user_id."""
    seed = normalize_email(case["email"])
    ctx = IdentityContext(seed_email=seed)
    users = _collect_user_identifiers(identities, audit_log)

    # Determine which user_id(s) match the seed
    matched_uids = set()
    for uid, vals in users.items():
        if seed in vals["emails"]:
            matched_uids.add(uid)
            ctx.confidence = "EXACT"

    if not matched_uids and facts:
        # Try to find a user_id from evidence facts with this email
        for fact in facts:
            if fact.source_kind == "file" and fact.capture_time and fact.capture_time <= parse_iso_utc(case["audit_at"]):
                if fact.has_identifier("email", seed):
                    for ident in fact.identifiers:
                        if ident["kind"] == "user_id":
                            matched_uids.add(ident["normalized"])
                            ctx.confidence = "EVIDENCE"

    if not matched_uids:
        ctx.confidence = "UNKNOWN"
        ctx.all_emails.add(seed)
        return ctx

    # Collect all identifiers for matched user_ids
    for uid in matched_uids:
        ctx.all_user_ids.add(uid)
        ctx.all_emails.update(users[uid]["emails"])
        ctx.all_phones.update(users[uid]["phones"])
        ctx.all_hashes.update(users[uid]["hashes"])
        ctx.all_names.update(users[uid]["names"])

    return ctx


# Import here to avoid circular import at module load
from dataload.timeutil import parse_iso_utc
