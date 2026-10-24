import csv
from pathlib import Path
from datetime import datetime

ROOT = Path(r'D:\ramuser\Downloads\Hackathon\hackerrank-orchestrate-october26')
DATASET = ROOT / 'dataset'

cutoff = datetime.fromisoformat('2026-09-03T11:30:00+00:00')

with open(DATASET / 'evidence_files.csv', encoding='utf-8-sig', newline='') as f:
    manifest = list(csv.DictReader(f))

for row in manifest:
    cap = datetime.fromisoformat(row['captured_at'].replace('Z', '+00:00'))
    if cap <= cutoff:
        print(row['file_id'], row['file_path'], row['captured_at'])
