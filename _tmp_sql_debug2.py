import re
text = open('dataset/evidence/databases/customer_data_inventory_20260916.sql', encoding='utf-8-sig').read()

for m in re.finditer(r"INSERT\s+INTO\s+['\"`]?(\w+)['\"`]?\s+VALUES\s*\((.+?)\);", text, re.IGNORECASE | re.DOTALL):
    table = m.group(1)
    if table != 'backup_restore_entries':
        continue
    values_str = m.group(2)
    print("values_str:", repr(values_str))
    vals = []
    i = 0
    n = len(values_str)
    while i < n:
        if values_str[i].isspace() or values_str[i] == ',':
            i += 1
            continue
        if values_str[i] == "'":
            j = i + 1
            while j < n:
                if values_str[j] == "'" and (j + 1 >= n or values_str[j + 1] != "'"):
                    break
                if values_str[j] == "'" and j + 1 < n and values_str[j + 1] == "'":
                    j += 2
                else:
                    j += 1
            token = values_str[i + 1:j].replace("''", "'")
            vals.append(token)
            i = j + 1
        else:
            j = i
            while j < n and values_str[j] not in ",)":
                j += 1
            token = values_str[i:j].strip()
            if token.lower() == "null":
                vals.append(None)
            else:
                vals.append(token)
            i = j
    print("vals:", vals)
