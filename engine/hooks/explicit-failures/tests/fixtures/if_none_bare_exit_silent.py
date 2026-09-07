import logging

log = logging.getLogger(__name__)


def price_rows(rows, quotes):
    if not rows:
        raise ValueError("price_rows: no input rows; upstream parse returned nothing")
    out = []
    for row in rows:
        ticker = row.get("ticker")
        if not ticker:
            out.append({"ticker": None, "px": None, "status": "unparsed", "reason": "row has no ticker"})
            continue
        quote = quotes.get(ticker)
        if quote is None:
            out.append({"ticker": ticker, "px": None, "status": "unpriced", "reason": "no quote"})
            continue
        out.append({"ticker": ticker, "px": quote, "status": "ok"})
    return out


def first_lot(lots):
    if len(lots) == 0:
        log.info("first_lot: no open lots")
        return None
    return lots[0]
