def price_rows(rows, quotes):
    if not rows:
        return []
    out = []
    for row in rows:
        ticker = row.get("ticker")
        if not ticker:
            continue
        quote = quotes.get(ticker)
        if quote is None:
            break
        out.append({"ticker": ticker, "px": quote})
    return out


def first_lot(lots):
    if len(lots) == 0:
        return None
    return lots[0]


def lookup(table, key):
    if table.get(key) == None:
        return
    return table[key]
