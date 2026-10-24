"""Global evidence index."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from config import DATASET
from evidence.facts import Fact
from evidence.parse_sql import parse_sql
from evidence.parse_log import parse_log
from evidence.parse_json import parse_json
from evidence.parse_txt import parse_txt
from evidence.parse_pdf import parse_pdf
from evidence.parse_image import parse_image
from dataload.timeutil import parse_iso_utc


@dataclass
class EvidenceIndex:
    facts: list[Fact] = field(default_factory=list)
    file_index: dict[str, dict] = field(default_factory=dict)
    activity_index: dict[str, dict] = field(default_factory=dict)
    audit_index: dict[str, dict] = field(default_factory=dict)
    extraction_errors: list[dict] = field(default_factory=list)

    def build(self, bundle) -> "EvidenceIndex":
        # Build activity and audit indexes
        for row in bundle.system_activity:
            self.activity_index[row["activity_id"]] = {
                **row,
                "event_time_dt": parse_iso_utc(row["event_time"]),
            }
        for row in bundle.user_audit_log:
            self.audit_index[row["audit_id"]] = {
                **row,
                "changed_at_dt": parse_iso_utc(row["event_time"]),
            }

        # Parse evidence files
        for ef in bundle.evidence_files:
            file_id = ef["file_id"]
            path = ef["resolved_path"]
            captured_at = ef["captured_at_dt"]
            self.file_index[file_id] = {
                "path": str(path),
                "origin": ef["origin"],
                "captured_at": captured_at,
            }

            try:
                suffix = path.suffix.lower()
                if suffix == ".sql":
                    facts = parse_sql(path, file_id, captured_at)
                elif suffix == ".log":
                    facts = parse_log(path, file_id, captured_at)
                elif suffix == ".json":
                    facts = parse_json(path, file_id, captured_at)
                elif suffix == ".txt":
                    facts = parse_txt(path, file_id, captured_at)
                elif suffix == ".pdf":
                    facts = parse_pdf(path, file_id, captured_at)
                elif suffix in (".png", ".jpg", ".jpeg"):
                    facts = parse_image(path, file_id, captured_at)
                else:
                    self.extraction_errors.append({
                        "file_id": file_id,
                        "path": str(path),
                        "error_type": "unsupported_type",
                        "error_message": f"Unsupported extension: {suffix}",
                    })
                    continue

                if not facts:
                    self.extraction_errors.append({
                        "file_id": file_id,
                        "path": str(path),
                        "error_type": "no_facts",
                        "error_message": "Parser produced no facts",
                    })
                else:
                    self.facts.extend(facts)
                    self.file_index[file_id]["fact_count"] = len(facts)
            except Exception as e:
                self.extraction_errors.append({
                    "file_id": file_id,
                    "path": str(path),
                    "error_type": type(e).__name__,
                    "error_message": str(e),
                })

        return self

    def get_file_capture_time(self, file_id: str) -> datetime | None:
        return self.file_index.get(file_id, {}).get("captured_at")

    def allowed_ids(self) -> set[str]:
        return set(self.file_index.keys()) | set(self.activity_index.keys()) | set(self.audit_index.keys())
