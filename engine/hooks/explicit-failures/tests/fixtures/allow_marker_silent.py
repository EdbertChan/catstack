def tickers(rows):
    out = []
    for row in rows:
        ticker = row.get("ticker")
        if not ticker:  # pragma: explicit-failures: allow
            continue
        out.append(ticker)
    return out


def maybe_read(path):
    try:
        with open(path) as fh:
            return fh.read()
    except FileNotFoundError:  # pragma: explicit-failures: allow
        pass
    return None
