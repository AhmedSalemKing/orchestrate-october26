"""Request intent classification and policy rule loading."""
from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class Rules:
    rules: list[dict] = field(default_factory=list)
    by_category: dict[str, dict] = field(default_factory=dict)

    @staticmethod
    def load(rows: list[dict]) -> "Rules":
        r = Rules(rules=rows)
        for row in rows:
            r.by_category[row["data_category"]] = row
        return r

    def action_for(self, data_category: str) -> str:
        if data_category not in self.by_category:
            raise ValueError(f"Unknown data_category: {data_category}")
        return self.by_category[data_category]["required_action"]


_DELETION_KEYWORDS = [
    r"delete", r"deletion", r"remove\s+(?:my|the)\s+(?:account|profile|data)",
    r"erase", r"right\s+to\s+be\s+forgotten",
    r"supprimer", r"\u00e9liminer", r"eliminar", r"borrar", r"l\u00f6schen",
    r"\u524a\u9664", r"\u5220\u9664", r"\uc0ad\uc81c",
    r"permanently\s+close", r"close\s+my\s+account",
    r"exclus\u00e3o", r"excluir",
]

_NON_DELETION_KEYWORDS = [
    r"\bexport\b", r"\bdownload\s+my\s+data\b", r"\bopt\s+out\s+of\s+marketing\b",
    r"\bunsubscribe\b", r"\bcorrect\s+my\s+data\b", r"\bupdate\s+my\s+email\b",
    r"\bchange\s+my\s+address\b", r"\baccess\s+request\b", r"\bsubject\s+access\b",
    r"\bportability\b", r"\bcancel\s+order\b",
]


def classify_request_intent(request_text: str) -> str:
    """Deterministic intent classification."""
    text = request_text.lower()
    # Unicode normalize
    import unicodedata
    text = unicodedata.normalize("NFC", text)

    # Check deletion first; many requests mention both export/download and deletion.
    deletion_match = any(re.search(pat, text) for pat in _DELETION_KEYWORDS)
    non_deletion_match = any(re.search(pat, text) for pat in _NON_DELETION_KEYWORDS)
    if deletion_match and non_deletion_match:
        return "DELETION"
    if non_deletion_match:
        return "NON_DELETION"
    if deletion_match:
        return "DELETION"
    return "AMBIGUOUS"
