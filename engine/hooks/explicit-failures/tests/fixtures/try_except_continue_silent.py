def parse_values(rows):
    out = []
    for row in rows:
        try:
            value = int(row["value"])
        except (KeyError, ValueError) as exc:
            out.append({"value": None, "status": "unparsed", "reason": f"{type(exc).__name__}: {exc}"})
            continue
        out.append({"value": value, "status": "ok"})
    return out
