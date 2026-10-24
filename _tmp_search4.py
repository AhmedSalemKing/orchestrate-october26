import csv, re
from pathlib import Path
from collections import defaultdict

ROOT = Path(r'D:\ramuser\Downloads\Hackathon\hackerrank-orchestrate-october26')
DATASET = ROOT / 'dataset'

# Build email -> user_id mapping
with open(DATASET / 'user_identities.csv', encoding='utf-8-sig', newline='') as f:
    identities = {r['email'].lower().strip(): r['user_id'] for r in csv.DictReader(f)}

# Sample cases
sample_cases = []
with open(DATASET / 'sample_deletion_requests.csv', encoding='utf-8-sig', newline='') as f:
    for r in csv.DictReader(f):
        r['user_id'] = identities.get(r['email'].lower().strip(), '?')
        sample_cases.append(r)

with open(DATASET / 'sample_output.csv', encoding='utf-8-sig', newline='') as f:
    sample_out = {r['case_id']: r for r in csv.DictReader(f)}

# For each sample case, find resource_id from sample output
for case in sample_cases:
    cid = case['case_id']
    out = sample_out[cid]
    import json
    steps = json.loads(out['steps_json'])
    resource_ids = [s['resource_id'] for s in steps if s['system_id'] == 'account_service']
    print(cid, case['email'], case['user_id'], 'audit_at=', case['audit_at'], 'status=', out['deletion_status'], 'account_resources=', resource_ids[:3])
