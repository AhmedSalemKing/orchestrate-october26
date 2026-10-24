"""Fact dataclass representing one extracted record from evidence."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal


@dataclass
class Fact:
    source_kind: Literal["file", "activity", "audit"]
    source_id: str
    source_path: str | None
    locator: str
    system_id: str | None
    resource_id: str | None
    data_category: str | None
    fields_present: list[str] = field(default_factory=list)
    identifiers: list[dict] = field(default_factory=list)
    record_time: datetime | None = None
    capture_time: datetime | None = None
    raw_excerpt: str = ""
    extractor: str = ""
    confidence: float = 1.0

    def has_identifier(self, kind: str, normalized_value: str | None = None) -> bool:
        for ident in self.identifiers:
            if ident.get("kind") != kind:
                continue
            if normalized_value is None:
                return True
            if ident.get("normalized") == normalized_value:
                return True
        return False

    def get_identifier_values(self, kind: str) -> list[str]:
        return [i.get("value", "") for i in self.identifiers if i.get("kind") == kind]
