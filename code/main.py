"""Main entry point for the deletion-audit agent."""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

from config import ROOT, DATASET
from dataload.loaders import DataBundle
from evidence.index import EvidenceIndex
from policy.engine import Rules
from state.builder import build_state
from decide import decide
from validators import validate_row, validate_output_file


def main():
    parser = argparse.ArgumentParser(description="Ghost Data Still Exists deletion audit agent")
    parser.add_argument("--input", default=str(DATASET / "deletion_requests.csv"), help="Input deletion requests CSV")
    parser.add_argument("--output", default=str(ROOT / "output.csv"), help="Output CSV path")
    parser.add_argument("--sample", action="store_true", help="Run on sample and evaluate")
    parser.add_argument("--verbose", action="store_true", help="Print progress")
    args = parser.parse_args()

    if args.sample:
        input_path = DATASET / "sample_deletion_requests.csv"
    else:
        input_path = Path(args.input)

    output_path = Path(args.output)

    if args.verbose:
        print("Loading datasets...", file=sys.stderr)
    bundle = DataBundle.load(DATASET)

    if args.verbose:
        print("Building evidence index...", file=sys.stderr)
    index = EvidenceIndex().build(bundle)

    if args.verbose:
        print(f"Indexed {len(index.facts)} facts, {len(index.extraction_errors)} extraction errors", file=sys.stderr)

    rules = Rules.load(bundle.deletion_rules)

    # Build validation context
    cases_by_id = {}
    for r in bundle.deletion_requests:
        cases_by_id[r["case_id"]] = r
    for r in bundle.sample_deletion_requests:
        cases_by_id[r["case_id"]] = r
    file_capture_times = {fid: info["captured_at"] for fid, info in index.file_index.items()}
    ctx = {
        "cases": cases_by_id,
        "deletion_request_ids": {r["case_id"] for r in bundle.deletion_requests},
        "allowed_ids": index.allowed_ids(),
        "file_capture_times": file_capture_times,
    }

    if args.sample:
        requests = bundle.sample_deletion_requests
    else:
        requests = bundle.deletion_requests

    rows = []
    for case in requests:
        state = build_state(case, bundle, index, rules)
        status, steps = decide(case, state, rules, bundle, index)
        try:
            validate_row(case["case_id"], status, steps, ctx)
        except ValueError as e:
            print(f"Validation error for {case['case_id']}: {e}", file=sys.stderr)
            raise
        rows.append((case["case_id"], status, json.dumps(steps, ensure_ascii=False, separators=(",", ":"))))

    rows.sort(key=lambda x: x[0])

    with open(output_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f, quoting=csv.QUOTE_MINIMAL, lineterminator="\n")
        writer.writerow(["case_id", "deletion_status", "steps_json"])
        for r in rows:
            writer.writerow(r)

    if not args.sample:
        validate_output_file(str(output_path), ctx)

    if args.sample:
        from evaluation.main import evaluate
        pred_path = output_path
        gold_path = DATASET / "sample_output.csv"
        evaluate(str(pred_path), str(gold_path))

    print(f"Wrote {len(rows)} rows to {output_path}")


if __name__ == "__main__":
    main()
