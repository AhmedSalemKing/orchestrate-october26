"""Step ordering utilities."""
from __future__ import annotations

from config import PHASE_ORDER, OP_ORDER


def sort_steps(steps: list[dict]) -> list[dict]:
    """Sort steps by phase, operation, system_id, resource_id."""
    def key(s):
        phase = s["phase"]
        op = s["operation"]
        return (
            PHASE_ORDER.get(phase, 99),
            OP_ORDER.get(phase, {}).get(op, 99),
            s.get("system_id") or "",
            s.get("resource_id") or "",
        )
    return sorted(steps, key=key)
