import csv, re
from pathlib import Path
from collections import Counter

ROOT = Path(r'D:\ramuser\Downloads\Hackathon\hackerrank-orchestrate-october26')
DATASET = ROOT / 'dataset'

with open(DATASET / 'evidence_files.csv', encoding='utf-8-sig', newline='') as f:
    manifest = list(csv.DictReader(f))

account_to_user = {}
email_to_account = {}
for row in manifest:
    path = DATASET / row['file_path']
    try:
        text = path.read_text(encoding='utf-8-sig', errors='replace')
    except Exception:
        continue
    # Look for account_XXX paired with user_YYY
    for m in re.finditer(r"account_(\d+)[^\n]{0,200}user_(\d+)", text):
        account_to_user[m.group(1)] = m.group(2)
    for m in re.finditer(r"user_(\d+)[^\n]{0,200}account_(\d+)", text):
        account_to_user[m.group(2)] = m.group(1)
    # Look for email paired with account
    for m in re.finditer(r"account_(\d+)[^\n]{0,300}([\w.\-+]+@[\w.\-]+\.[a-zA-Z]{2,})", text):
        email_to_account[m.group(2)] = m.group(1)

print("Account to user samples:")
for k, v in sorted(account_to_user.items(), key=lambda x: int(x[0]))[:30]:
    print(k, v)
print("...")
for k, v in sorted(account_to_user.items(), key=lambda x: int(x[0]))[-10:]:
    print(k, v)
print(f"Total mappings: {len(account_to_user)}")
