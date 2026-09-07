from collections import defaultdict, deque

COST_UNKNOWN = "unknown"


def build_lots_and_realized(rows, period_price, share_delta, note_est, unknown_reason):
    lots = defaultdict(deque)
    realized = []
    unlotted = defaultdict(float)
    for row in rows:
        t = row.get("investee_ticker")
        if not t:
            realized.append({"period_end": row.get("period_end"), "status": "unparsed", "reason": "row has no ticker"})
            continue
        delta = share_delta(row)
        px = period_price(row)
        pe = str(row.get("period_end") or "")
        if delta > 0:
            if px is None:
                unlotted[t] += float(delta)
                realized.append({"period_end": pe, "investee_ticker": t, "status": "unpriced_buy", "reason": "no period price"})
                continue
            lots[t].append({"shares": float(delta), "cost_px": float(px), "open_period": pe})
            continue
        if delta >= 0:
            continue
        need = -float(delta)
        if need <= 1e-12:
            continue
        exit_px = float(px) if px is not None else None
        base = {"period_end": pe, "investee_ticker": t, "exit_px": exit_px}
        if not lots[t]:
            reason = unknown_reason(t, row)
            unlotted[t] = max(0.0, unlotted[t] - need)
            realized.append(
                {
                    **base,
                    "shares_sold": need,
                    "cost_px": None,
                    "realized_pnl_est": None,
                    "cost_method": "avg",
                    "cost_basis_status": COST_UNKNOWN,
                    "cost_basis_note": f"no cost lot: {reason}",
                    "note": note_est,
                }
            )
            continue
        avg_px = sum(l["shares"] * l["cost_px"] for l in lots[t]) / sum(l["shares"] for l in lots[t])
        realized.append(
            {
                **base,
                "shares_sold": need,
                "cost_px": avg_px,
                "realized_pnl_est": need * (exit_px - avg_px) if exit_px is not None else None,
                "cost_method": "avg",
                "cost_basis_status": "exact",
                "note": note_est,
            }
        )
    return [lot for q in lots.values() for lot in q], realized
