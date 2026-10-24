import csv
from pathlib import Path

ROOT = Path(r'D:\ramuser\Downloads\Hackathon\hackerrank-orchestrate-october26')
DATASET = ROOT / 'dataset'

terms = ['account_001', 'user_01', 'amina.elmasri@gmail.com']
results = {t: [] for t in terms}

with open(DATASET / 'evidence_files.csv', encoding='utf-8-sig', newline='') as f:
    manifest = list(csv.DictReader(f))

for row in manifest:
    path = DATASET / row['file_path']
    try:
        text = path.read_text(encoding='utf-8-sig', errors='replace')
    except Exception:
        continue
    for term in terms:
        if term in text:
            results[term].append((row['file_id'], row['file_path'], row['captured_at']))

for term, hits in results.items():
    print(f"=== {term} ===")
    for h in hits[:20]:
        print(h)
    print()
