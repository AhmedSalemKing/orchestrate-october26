import re
text = open('dataset/evidence/databases/customer_data_inventory_20260916.sql', encoding='utf-8-sig').read()
for m in re.finditer(r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?['\"`]?(\w+)['\"`]?\s*\((.+?)\);", text, re.IGNORECASE | re.DOTALL):
    print("table:", m.group(1))
    body = m.group(2)
    parts = re.split(r",(?![^()]*\))", body)
    cols = []
    for part in parts:
        part = part.strip()
        if not part:
            continue
        mm = re.match(r"['\"`]?(\w+)['\"`]?\s+", part)
        if mm:
            cols.append(mm.group(1))
    print("  cols:", cols)
