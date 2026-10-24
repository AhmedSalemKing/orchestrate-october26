import sys, json
sys.path.insert(0, 'code')
from pathlib import Path
from dataload.loaders import DataBundle
from evidence.index import EvidenceIndex
from policy.engine import Rules
from state.builder import build_state
from decide import decide

bundle = DataBundle.load(Path('dataset'))
index = EvidenceIndex().build(bundle)
rules = Rules.load(bundle.deletion_rules)

case_by_id = {c['case_id']: c for c in bundle.sample_deletion_requests}
with open('dataset/sample_output.csv', encoding='utf-8-sig', newline='') as f:
    import csv
    gold = {r['case_id']: r for r in csv.DictReader(f)}

mismatches = []
for cid in sorted(case_by_id):
    case = case_by_id[cid]
    state = build_state(case, bundle, index, rules)
    status, steps = decide(case, state, rules, bundle, index)
    g_status = gold[cid]['deletion_status']
    if status != g_status:
        mismatches.append((cid, case['email'], g_status, status, state.expected_account_resource, [(g.system_id, g.resource_id, g.data_category) for g in state.groups]))
        print(f"{cid} expected={g_status} got={status} email={case['email']} expected_account={state.expected_account_resource}")
        for g in state.groups:
            print(f"  {g.system_id}/{g.resource_id}/{g.data_category} -> {g.effective_state}")

print(f"\nTotal mismatches: {len(mismatches)}")
