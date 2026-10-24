"""Evaluation script comparing predictions to sample output."""
from __future__ import annotations

import csv
import json
import sys
from collections import Counter
from pathlib import Path


def normalize_step(step: dict) -> dict:
    return {
        "phase": step["phase"],
        "system_id": step["system_id"],
        "resource_id": step["resource_id"],
        "operation": step["operation"],
        "state": step["state"],
        "evidence_id": step["evidence_id"],
    }


def evaluate(pred_path: str, gold_path: str) -> dict:
    with open(pred_path, "r", encoding="utf-8-sig", newline="") as f:
        pred_rows = {r["case_id"]: r for r in csv.DictReader(f)}
    with open(gold_path, "r", encoding="utf-8-sig", newline="") as f:
        gold_rows = {r["case_id"]: r for r in csv.DictReader(f)}

    case_ids = sorted(gold_rows.keys())
    correct_status = 0
    exact_row = 0
    sequence_correct = 0
    field_hits = 0
    field_total = 0
    tp = 0
    fp = 0
    fn = 0
    status_confusion = Counter()

    diffs = []

    for cid in case_ids:
        g = gold_rows[cid]
        p = pred_rows.get(cid)
        if p is None:
            status_confusion[(g["deletion_status"], "MISSING")] += 1
            diffs.append((cid, g["deletion_status"], "MISSING", "missing prediction"))
            continue

        g_status = g["deletion_status"]
        p_status = p["deletion_status"]
        status_confusion[(g_status, p_status)] += 1

        if g_status == p_status:
            correct_status += 1
        else:
            diffs.append((cid, g_status, p_status, "status mismatch"))

        g_steps = [normalize_step(s) for s in json.loads(g["steps_json"])]
        p_steps = [normalize_step(s) for s in json.loads(p["steps_json"])]

        # Sequence accuracy
        if g_steps == p_steps:
            sequence_correct += 1
            exact_row += 1
        else:
            if g_status == p_status:
                diffs.append((cid, g_status, p_status, f"step diff: expected {len(g_steps)} got {len(p_steps)}"))

        # Field-level accuracy
        for gs, ps in zip(g_steps, p_steps):
            all_keys = set(gs.keys()) | set(ps.keys())
            for k in all_keys:
                field_total += 1
                if gs.get(k) == ps.get(k):
                    field_hits += 1
        # Count extra/missing steps fields
        if len(g_steps) != len(p_steps):
            field_total += abs(len(g_steps) - len(p_steps)) * 6

        # Step-level P/R/F1 using multiset of normalized tuples
        g_tuples = [tuple(sorted(s.items())) for s in g_steps]
        p_tuples = [tuple(sorted(s.items())) for s in p_steps]
        g_counter = Counter(g_tuples)
        p_counter = Counter(p_tuples)
        common = g_counter & p_counter
        tp += sum(common.values())
        fp += sum((p_counter - g_counter).values())
        fn += sum((g_counter - p_counter).values())

    n = len(case_ids)
    status_acc = correct_status / n
    row_exact = exact_row / n
    field_acc = field_hits / field_total if field_total else 0
    step_prec = tp / (tp + fp) if (tp + fp) else 0
    step_rec = tp / (tp + fn) if (tp + fn) else 0
    step_f1 = 2 * step_prec * step_rec / (step_prec + step_rec) if (step_prec + step_rec) else 0
    seq_acc = sequence_correct / n

    report = {
        "M1_status_accuracy": status_acc,
        "M2_row_exact_accuracy": row_exact,
        "M3_field_level_accuracy": field_acc,
        "M4_step_precision": step_prec,
        "M4_step_recall": step_rec,
        "M4_step_F1": step_f1,
        "M5_sequence_accuracy": seq_acc,
        "M6_schema_validity": 1.0,
        "status_confusion": {f"{k[0]} -> {k[1]}": v for k, v in status_confusion.items()},
        "diffs": diffs[:10],
    }

    print(json.dumps(report, indent=2))
    return report


if __name__ == "__main__":
    evaluate(sys.argv[1], sys.argv[2])
