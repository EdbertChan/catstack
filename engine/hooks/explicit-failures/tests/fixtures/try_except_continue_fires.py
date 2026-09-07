def parse_values(rows):
    out = []
    for row in rows:
        try:
            value = int(row["value"])
        except (KeyError, ValueError):
            continue
        out.append(value)
    return out
