from collections import defaultdict, deque


def build_lots_and_realized(rows, period_price, share_delta, note_est):
    lots = defaultdict(deque)
    realized = []
    for row in rows:
        t = row.get("investee_ticker")
        delta = share_delta(row)
        px = period_price(row)
        pe = str(row.get("period_end") or "")
        if delta > 0 and px is not None:
            lots[t].append({"shares": float(delta), "cost_px": float(px), "open_period": pe})
            continue
        if delta >= 0 or px is None:
            continue
        need = -float(delta)
        exit_px = float(px)
        if need <= 1e-12:
            continue
        if not lots[t]:
            if "lookback_truncated=1" in str(row.get("note") or ""):
                realized.append(
                    {
                        "period_end": pe,
                        "investee_ticker": t,
                        "shares_sold": need,
                        "cost_px": None,
                        "exit_px": exit_px,
                        "realized_pnl_est": None,
                        "cost_method": "avg",
                        "note": f"{note_est}; cost_basis=unknown_truncated",
                    }
                )
            continue
        avg_px = sum(l["shares"] * l["cost_px"] for l in lots[t]) / sum(l["shares"] for l in lots[t])
        realized.append(
            {
                "period_end": pe,
                "investee_ticker": t,
                "shares_sold": need,
                "cost_px": avg_px,
                "exit_px": exit_px,
                "realized_pnl_est": need * (exit_px - avg_px),
                "cost_method": "avg",
                "note": note_est,
            }
        )
    return [lot for q in lots.values() for lot in q], realized
