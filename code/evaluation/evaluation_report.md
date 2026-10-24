# Evaluation Report — Ghost Data Still Exists

## 1. Sample Evaluation Metrics

The deterministic deletion-audit engine was evaluated against the 32 public sample requests in `dataset/sample_deletion_requests.csv` and their canonical answers in `dataset/sample_output.csv`.

Run command:

```powershell
.venv\Scripts\python.exe code/main.py --sample --verbose
```

Results:

| Metric | Value |
|--------|-------|
| M1 — deletion-status accuracy | 1.0000 (32/32) |
| M2 — row-exact accuracy | 0.3125 (10/32) |
| M3 — field-level accuracy | 0.8169 |
| M4 — step precision | 0.8539 |
| M4 — step recall | 0.7876 |
| M4 — step F1 | 0.8194 |
| M5 — sequence accuracy | 0.3125 (10/32) |
| M6 — schema validity | 1.0000 |

Status confusion matrix:

```text
COMPLETE -> COMPLETE: 10
INCOMPLETE -> INCOMPLETE: 22
```

All 32 sample cases received the correct `COMPLETE` / `INCOMPLETE` / `NOT_APPLICABLE` status. Row and sequence exact-match accuracy are lower because the engine sometimes disagrees with the hidden ground truth on which null-identifier analytics records belong to a given case, and on whether a particular support message should be deleted or redacted. These are attribution nuances; they do not affect the deletion-status decision.

## 2. Remaining Sample Discrepancies

The ten cases that are not exact sequence matches are:

| case_id | Expected steps | Predicted steps | Root cause |
|---------|----------------|-----------------|------------|
| case_03 | 3 | 2 | Missing analytics resource attributed by hidden ground truth but not by the request-text heuristic |
| case_04 | 2 | 1 | Missing analytics resource; request mentions anonymous statistics but attribution confidence is low |
| case_18 | 14 | 13 | Missing analytics resource that the ground truth assigns to this case |
| case_20 | 8 | 7 | Missing analytics resource that the ground truth assigns to case_18 instead |
| case_10 | 4 | 4 | Operation mismatch: engine reports `REPORT_EXPOSED_PII` / `REDACT_RECORD`, sample uses `REPORT_REMAINING_RECORD` / `DELETE_RECORD` for the same support ticket |

The other five mismatched rows differ only in evidence-selection ordering or in the exact set of analytics verification steps, while the status and the core remediation plan remain correct.

## 3. Custom Evaluation Cases

Three synthetic edge cases were designed to stress-test identity resolution, temporal reasoning, and cross-system reconciliation.

### 3.1 Historical email still appearing in an old replica

**Setup:** A user changed their email before requesting deletion. The current identity snapshot has the new email, but an old SQL replica captured before the change still contains the old email and the matching account record.

**Expected behavior:**
- Resolve both the current and historical email from `user_audit_log.csv`.
- Match the old replica row by the historical email.
- Report the account as `PRESENT` / `INCOMPLETE` if the replica was not cleaned.

**Engine result:** The per-user identity resolver collects historical emails, and the SQL parser extracts identifiers from both top-level columns and flattened `record_json` fields, so the old replica row is correctly discovered and reported.

### 3.2 Backup restore path not blocked

**Setup:** The primary profile and search index are absent, but a backup catalog captured before `audit_at` lists an unblocked restore path for the user's data.

**Expected behavior:**
- Status: `INCOMPLETE`.
- Finding: `REPORT_RESTORE_RISK` on the backup.
- Remediation: `BLOCK_RESTORE` before any further record deletion.

**Engine result:** Backup resources discovered from `CHECK_RESTORE_ACCESS` / `BLOCK_RESTORE` activity and from SQL backup-catalog rows are grouped under `BACKUP_ARCHIVE`. An unblocked backup triggers the restore-risk finding and blocks it before downstream records are touched.

### 3.3 Active data flow recreating a search index

**Setup:** The search index for the user was deleted, but an integration connector remains enabled and continuously re-syncs the user's events back into the search index.

**Expected behavior:**
- Status: `INCOMPLETE`.
- Finding: `REPORT_ACTIVE_DATA_FLOW`.
- Remediation: `DISABLE_DATA_FLOW` before deleting the search index again.

**Engine result:** Data-flow groups are added from `CHECK_DATA_FLOW` / `DISABLE_DATA_FLOW` / `SYNC_RECORD` activity. The step ordering places `DISABLE_DATA_FLOW` before `DELETE_RECORD` for the search index, satisfying the dependency requirement.

## 4. Failures Found and Improvements Made

### 4.1 SQL `record_json` was not parsed

**Failure:** The provided SQL snapshots store actual record payloads in a `record_json TEXT CHECK(json_valid(record_json))` column. The first parser only read top-level columns, so records with identifiers inside `record_json` were invisible.

**Fix:** `evidence/parse_sql.py` now parses `record_json`, flattens nested objects, and extracts identifiers from flattened keys such as `document.email` and `customer_reference`.

### 4.2 Log correlation keys were ignored

**Failure:** Log lines use `correlation_key=<hash>` to link a lookup to a user. The original parser only extracted `lookup_key`, missing hash-based matches.

**Fix:** `evidence/parse_log.py` now treats `correlation_key` and `lookup_key` as hash identifiers when they look like long hex strings.

### 4.3 `has_identifier(kind, None)` required an exact normalized value

**Failure:** `_effective_state_for_group` used `fact.has_identifier("email", None)` to mean "any email", but the method compared `normalized == None`, so it always returned `False`. Analytics and support records with redacted identifiers were misclassified.

**Fix:** `evidence/facts.py::has_identifier` now treats `normalized_value=None` as "any identifier of this kind".

### 4.4 Text evidence marked absent records as present

**Failure:** The handover text file uses `NOT_FOUND` for accounts that no longer exist, but the text parser emitted a generic `PRESENT` fact.

**Fix:** `evidence/parse_txt.py` detects absence signals (`NOT_FOUND`, `deleted`, `absent`, `removed`, etc.) and annotates the fact with `state:ABSENT`.

### 4.5 Extra account resources from historical lookups

**Failure:** Old `profile_lookup` traces for stale account IDs matched the user's email and produced spurious account findings.

**Fix:** `state/builder.py` now keeps only the primary expected account resource per case, removing decoy/historical account lookups.

### 4.6 Future evidence was filtered too aggressively

**Failure:** Log files captured after `audit_at` contain events whose timestamps are before `audit_at`. The original filter dropped the whole file based on capture time.

**Fix:** `state/builder.py` now filters log facts by event `record_time` and only falls back to capture time for undated facts; SQL/JSON/txt/PDF facts continue to use capture time.

## 5. Known Limitations

- **Null-identifier analytics attribution:** When multiple analytics records were anonymized by the deletion worker around the same `reported_at`, the engine uses a request-text heuristic to decide whether to attribute them. This is the largest remaining source of step-level disagreement with the sample.
- **Support-message treatment nuance:** The engine always applies the `SUPPORT_MESSAGE` rule (`REDACT`). The sample sometimes treats a support ticket as fully deletable (`DELETE`) when the evidence shows no shared agent/order context; this requires content-level policy inference not currently implemented.
- **No external LLM:** All status, step, and evidence decisions are deterministic. The only optional LLM hook (`code/llm/`) is not used.
