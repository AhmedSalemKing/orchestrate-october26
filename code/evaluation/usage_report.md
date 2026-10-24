# Usage Report — Ghost Data Still Exists

## Final Full-Dataset Run

The final `output.csv` for all 518 evaluation requests was produced with the following command:

```powershell
.venv\Scripts\python.exe code/main.py --verbose
```

Run environment:

| Item | Value |
|------|-------|
| Working directory | `D:\ramuser\Downloads\Hackathon\hackerrank-orchestrate-october26` |
| Python version | 3.14.0a? (virtual environment `.venv/`) |
| Input | `dataset/deletion_requests.csv` (518 rows) |
| Output | `output.csv` (518 data rows + header) |
| Evidence files processed | 94 |
| Facts indexed | 2,095 |
| Extraction errors | 14 (mostly empty image/OCR and unsupported image files) |

## Model Usage

This submission uses a **fully deterministic** pipeline. No external LLM is invoked for:

- request-intent classification,
- identity resolution,
- evidence-state inference,
- deletion-status decisions,
- step selection or ordering.

The request-text classifier is a small set of regex keywords in `code/policy/engine.py`. All parsing, matching, and reasoning is rule-based.

| Provider | Model | Calls | Input tokens | Output tokens | Total tokens | Est. cost |
|----------|-------|-------|--------------|---------------|--------------|-----------|
| N/A | N/A | 0 | 0 | 0 | 0 | $0.00 |
| **Total** | | **0** | **0** | **0** | **0** | **$0.00** |

## Runtime Profile

Approximate timings from the final full-dataset run on the development machine:

| Phase | Approximate time |
|-------|------------------|
| Load CSVs | < 1 s |
| Build evidence index | ~5–10 s |
| Process 518 cases | ~10–20 s |
| Validate and write `output.csv` | < 1 s |
| **Total** | **~20–30 s** |

Per-request average: ~40–60 ms.

## Determinism Notes

- The solution does not use randomness.
- Step ordering is deterministic: phase order (`FINDING` → `REMEDIATION` → `VERIFICATION`), then operation order, then `system_id`, then `resource_id`.
- Re-running `code/main.py` on the same dataset produces the same `output.csv`.
