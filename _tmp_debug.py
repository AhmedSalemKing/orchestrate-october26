import sys
sys.path.insert(0, 'code')
from dataload.loaders import DataBundle
from evidence.index import EvidenceIndex
from policy.engine import Rules
from state.builder import build_state
from decide import decide

from pathlib import Path
bundle = DataBundle.load(Path('dataset'))
index = EvidenceIndex().build(bundle)
rules = Rules.load(bundle.deletion_rules)

cases = ['case_09', 'case_12', 'case_15', 'case_16', 'case_22', 'case_26', 'case_27', 'case_28']
case_by_id = {c['case_id']: c for c in bundle.sample_deletion_requests}
for cid in cases:
    case = case_by_id[cid]
    state = build_state(case, bundle, index, rules)
    status, steps = decide(case, state, rules, bundle, index)
    print(f"=== {cid} {case['email']} audit_at={case['audit_at']} ===")
    print(f"idctx: user_ids={state.idctx.all_user_ids}, emails={state.idctx.all_emails}")
    print(f"expected_account={state.expected_account_resource}")
    for g in state.groups:
        print(f"  group {g.system_id}/{g.resource_id}/{g.data_category} -> {g.effective_state}")
        for f in g.facts:
            print(f"    fact {f.source_id} {f.locator} {f.identifiers} fields={f.fields_present}")
    print(f"status={status} steps={steps}")
    print()
