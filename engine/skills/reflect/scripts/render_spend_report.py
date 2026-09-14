#!/usr/bin/env python3
"""Render a spend_ledger.py ledger into one self-contained HTML dashboard page.

Usage:
    render_spend_report.py LEDGER.json --out spend.html [--top 25]

LEDGER.json is the output of `spend_ledger.py fleet --out` or `spend_ledger.py scan`.
The page needs no network beyond Google Fonts, carries its own title, and can be
opened locally or published as an artifact. Hosts that could not be scanned and
tokens that could not be priced are shown on the page, never folded into zero.
"""
import argparse
import collections
import datetime
import html
import json
import statistics
import sys

KIND_LABELS = {"typed": "You typed", "invoker": "Invoker ran it", "scripted": "Scripted one-shot", "eval": "Eval / judge"}
KIND_ORDER = ["typed", "invoker", "scripted", "eval"]
BANDS = [(0, 0.01, "under 1¢"), (0.01, 0.10, "1¢ – 10¢"), (0.10, 1, "10¢ – $1"), (1, 10, "$1 – $10"),
         (10, 50, "$10 – $50"), (50, float("inf"), "over $50")]

STYLE = """
:root{--bg:#eef2f3;--surface:#fff;--surface-2:#f6f8f9;--ink:#14222a;--ink-2:#41565f;--ink-3:#6c828c;--rule:#d6e0e4;
--rule-strong:#b6c6cc;--typed:#d2690a;--invoker:#00a3b4;--scripted:#b0552f;--eval:#6355d8;--hot:#b3261e}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--bg:#0e1619;--surface:#151f24;--surface-2:#1a262c;
--ink:#e7eef1;--ink-2:#b2c3ca;--ink-3:#85999f;--rule:#26353c;--rule-strong:#3a4d55;--typed:#f08a2a;--invoker:#2bc0d0;
--scripted:#d1774c;--eval:#8d81ec;--hot:#f2836f}}
:root[data-theme="dark"]{--bg:#0e1619;--surface:#151f24;--surface-2:#1a262c;--ink:#e7eef1;--ink-2:#b2c3ca;--ink-3:#85999f;
--rule:#26353c;--rule-strong:#3a4d55;--typed:#f08a2a;--invoker:#2bc0d0;--scripted:#d1774c;--eval:#8d81ec;--hot:#f2836f}
*{box-sizing:border-box}
body{background:var(--bg);color:var(--ink);font-family:"IBM Plex Sans",ui-sans-serif,system-ui,sans-serif;font-size:15px;line-height:1.55}
.wrap{max-width:1120px;margin:0 auto;padding-inline:20px;padding-block:36px 64px;display:flex;flex-direction:column;gap:32px}
h1,h2{font-family:Newsreader,Georgia,serif;font-weight:600;margin:0;text-wrap:balance}
h1{font-size:38px;line-height:1.1}h2{font-size:23px}h3{font-size:15px;margin:0;font-weight:600}
p{margin:0;max-width:68ch;color:var(--ink-2)}
.eyebrow{font-family:"IBM Plex Mono",monospace;font-size:11px;letter-spacing:.14em;text-transform:uppercase;color:var(--invoker)}
section{display:flex;flex-direction:column;gap:14px}
.head{border-top:2px solid var(--rule-strong);padding-top:12px}
.num,td.num{font-family:"IBM Plex Mono",monospace;font-variant-numeric:tabular-nums}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:1px;background:var(--rule);border:1px solid var(--rule);border-radius:3px;overflow:hidden}
.tiles div{background:var(--surface);padding:14px 16px;display:flex;flex-direction:column;gap:2px}
.tiles .k{font-size:12px;color:var(--ink-3)}.tiles .v{font-family:"IBM Plex Mono",monospace;font-size:24px}
.tiles .s{font-size:12px;color:var(--ink-3)}
.panel{background:var(--surface);border:1px solid var(--rule);border-radius:3px;padding:18px;display:flex;flex-direction:column;gap:12px}
.two{display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:18px}
.warn{border-left:3px solid var(--hot)}
.scroll{overflow-x:auto}
table{border-collapse:collapse;width:100%;font-size:13px}
th,td{text-align:right;padding:6px 9px;border-bottom:1px solid var(--rule);white-space:nowrap}
th:first-child,td:first-child,td.l,th.l{text-align:left}
thead th{font-size:10.5px;letter-spacing:.07em;text-transform:uppercase;color:var(--ink-3);font-weight:500;border-bottom:1px solid var(--rule-strong)}
.bar{display:inline-block;height:9px;border-radius:0 2px 2px 0;vertical-align:middle;margin-right:6px;min-width:2px}
.days{display:flex;align-items:flex-end;gap:3px;height:160px;border-bottom:1px solid var(--rule-strong)}
.day{flex:1;display:flex;flex-direction:column-reverse;min-width:4px}
.day span{display:block}
.legend{display:flex;flex-wrap:wrap;gap:4px 16px;font-size:12px;color:var(--ink-2)}
.sw{display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:5px;vertical-align:-1px}
.hint{font-size:12px;color:var(--ink-3)}
code{font-family:"IBM Plex Mono",monospace;font-size:12px;background:var(--surface-2);padding:1px 5px;border-radius:2px}
@media (max-width:560px){h1{font-size:30px}}
"""


def money(value):
    if value is None:
        return "—"
    if abs(value) >= 100:
        return f"${value:,.0f}"
    return f"${value:,.2f}"


def esc(value):
    return html.escape(str(value if value is not None else ""))


def load_ledger(path):
    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)
    if "hosts" not in data:
        data = {"generated_at": data.get("scanned_at"), "days": data.get("days"),
                "hosts": [{"name": data.get("host", "local"), "state": "checked", "reason": "",
                           "status": data.get("status", {}), "sessions": len(data.get("sessions", []))}],
                "sessions": data.get("sessions", [])}
    return data


def kind_table(rows):
    body = []
    for tool in ("claude", "codex"):
        subset = [r for r in rows if r["tool"] == tool]
        total = sum(r["cost_total"] for r in subset) or 1
        for kind in KIND_ORDER:
            group = [r["cost_total"] for r in subset if r["kind"] == kind]
            if not group:
                continue
            spend = sum(group)
            body.append(
                f"<tr><td>{'Claude' if tool == 'claude' else 'Codex (estimate)'}</td><td class='l'>"
                f"<span class='sw' style='background:var(--{kind})'></span>{KIND_LABELS[kind]}</td>"
                f"<td class='num'>{len(group):,}</td><td class='num'>{money(spend)}</td>"
                f"<td class='num'>{spend / total * 100:.0f}%</td><td class='num'>{money(statistics.median(group))}</td>"
                f"<td class='num'>{money(spend / len(group))}</td></tr>")
    return ("<table><thead><tr><th>Agent</th><th class='l'>Who started it</th><th>Sessions</th><th>Spend</th>"
            "<th>Share</th><th>Median</th><th>Average</th></tr></thead><tbody>" + "".join(body) + "</tbody></table>")


def host_table(ledger, rows):
    spend = collections.defaultdict(lambda: {"claude": 0.0, "codex": 0.0, "unpriced": 0})
    for r in rows:
        bucket = spend[r["host"]]
        if r["tool"] in ("claude", "codex"):
            bucket[r["tool"]] += r["cost_total"]
        if r["priced"] == "unpriced":
            bucket["unpriced"] += sum((r.get("tokens") or {}).values())
    body = []
    for host in ledger["hosts"]:
        name = host["name"]
        if host["state"] != "checked":
            body.append(f"<tr><td>{esc(name)}</td><td class='l' style='color:var(--hot)'>Not scanned: {esc(host['reason'])}"
                        f"</td><td class='num'>—</td><td class='num'>—</td><td class='num'>—</td></tr>")
            continue
        s = spend[name]
        unpriced = f"{s['unpriced'] / 1e9:.2f}B tokens" if s["unpriced"] else "—"
        body.append(f"<tr><td>{esc(name)}</td><td class='l'>{host['sessions']:,} sessions</td>"
                    f"<td class='num'>{money(s['claude'])}</td><td class='num'>{money(s['codex'])}</td>"
                    f"<td class='num'>{unpriced}</td></tr>")
    return ("<table><thead><tr><th>Machine</th><th class='l'>Scan</th><th>Claude</th><th>Codex (est.)</th>"
            "<th>Unpriced</th></tr></thead><tbody>" + "".join(body) + "</tbody></table>")


def band_table(rows):
    claude = [r for r in rows if r["tool"] == "claude"]
    body = []
    for low, high, label in BANDS:
        group = [r for r in claude if low <= r["cost_total"] < high]
        counts = collections.Counter(r["kind"] for r in group)
        body.append(f"<tr><td>{label}</td><td class='num'>{len(group):,}</td>"
                    f"<td class='num'>{money(sum(r['cost_total'] for r in group))}</td>"
                    + "".join(f"<td class='num'>{counts[k]:,}</td>" for k in KIND_ORDER) + "</tr>")
    return ("<table><thead><tr><th>Claude session cost</th><th>Sessions</th><th>Spend</th>"
            + "".join(f"<th>{KIND_LABELS[k]}</th>" for k in KIND_ORDER) + "</tr></thead><tbody>"
            + "".join(body) + "</tbody></table>")


def day_chart(rows):
    days = collections.defaultdict(collections.Counter)
    for r in rows:
        if r["tool"] != "claude" or not r.get("last"):
            continue
        days[r["last"][:10]][r["kind"]] += r["cost_total"]
    if not days:
        return "<p class='hint'>No dated Claude sessions in this ledger.</p>"
    ordered = sorted(days)
    peak = max(sum(days[d].values()) for d in ordered) or 1
    columns = []
    for day in ordered:
        segments = "".join(
            f"<span style='height:{days[day][k] / peak * 150:.1f}px;background:var(--{k})' "
            f"title='{day} {KIND_LABELS[k]} {money(days[day][k])}'></span>" for k in KIND_ORDER if days[day][k] > 0)
        columns.append(f"<div class='day' title='{day}: {money(sum(days[day].values()))}'>{segments}</div>")
    legend = "".join(f"<span><span class='sw' style='background:var(--{k})'></span>{KIND_LABELS[k]}</span>" for k in KIND_ORDER)
    return (f"<div class='legend'>{legend}</div><div class='days'>{''.join(columns)}</div>"
            f"<p class='hint'>{ordered[0]} to {ordered[-1]} · tallest day {money(peak)} · hover a column for exact figures.</p>")


def session_table(rows, top, key, heading):
    ranked = sorted(rows, key=key, reverse=True)[:top]
    body = []
    for rank, r in enumerate(ranked, 1):
        polling = r.get("polling") or {}
        waiting = (polling.get("waiting") or 0) + (polling.get("repeat") or 0)
        body.append(
            f"<tr><td class='num'>{rank}</td><td class='l'>{esc((r.get('first') or '')[:10])}</td><td class='l'>{esc(r['host'])}</td>"
            f"<td class='l'>{esc(r['repo'] or '—')}</td><td class='l'><span class='sw' style='background:var(--{r['kind']})'></span>"
            f"{KIND_LABELS[r['kind']]}</td><td class='l'>{esc((r.get('model') or '').replace('claude-', ''))}</td>"
            f"<td class='num'>{r.get('hours') or 0:.1f}</td><td class='num'>{r['calls'] if r['calls'] is not None else '—'}</td>"
            f"<td class='num'>{r['prompts'] if r['prompts'] is not None else '—'}</td>"
            f"<td class='num'>{(r['peak_history'] or 0) // 1000}k</td><td class='num'>{money(r['cost_total'])}</td>"
            f"<td class='num'>{money(r.get('sub_cost'))}</td><td class='num'>{money(waiting)}</td></tr>")
    return (f"<h3>{heading}</h3><div class='scroll'><table><thead><tr><th>#</th><th class='l'>Started</th><th class='l'>Machine</th>"
            "<th class='l'>Repo</th><th class='l'>Who</th><th class='l'>Model</th><th>Hours</th><th>Calls</th><th>Prompts</th>"
            "<th>Peak history</th><th>Cost</th><th>Helpers</th><th>Waiting + repeats</th></tr></thead><tbody>"
            + "".join(body) + "</tbody></table></div>")


def render(ledger, top):
    rows = ledger["sessions"]
    claude = [r for r in rows if r["tool"] == "claude"]
    codex = [r for r in rows if r["tool"] == "codex"]
    claude_total = sum(r["cost_total"] for r in claude)
    codex_total = sum(r["cost_total"] for r in codex)
    typed = sum(r["cost_total"] for r in rows if r["kind"] == "typed")
    fleet = sum(r["cost_total"] for r in rows if r["kind"] == "invoker")
    waiting = sum((r["polling"].get("waiting") or 0) for r in claude)
    repeats = sum((r["polling"].get("repeat") or 0) for r in claude)
    helpers = sum(r.get("sub_cost") or 0 for r in claude)
    unchecked = [h for h in ledger["hosts"] if h["state"] != "checked"]
    unpriced_tokens = sum(sum((r.get("tokens") or {}).values()) for r in rows if r["priced"] == "unpriced")
    generated = ledger.get("generated_at") or datetime.datetime.now(datetime.timezone.utc).isoformat()
    warnings = []
    if unchecked:
        warnings.append("<p><b>Not every machine was scanned.</b> " + "; ".join(
            f"{esc(h['name'])}: {esc(h['reason'])}" for h in unchecked) + ". Their sessions are missing from every number below.</p>")
    if unpriced_tokens:
        warnings.append(f"<p><b>{unpriced_tokens / 1e9:.2f}B tokens have no price.</b> They come from logs that record tokens "
                        "but not the model, and are left out of the dollar totals.</p>")
    if not rows:
        warnings.append("<p><b>No sessions found in this window.</b></p>")
    warning_html = f"<div class='panel warn'>{''.join(warnings)}</div>" if warnings else ""
    polling_share = (waiting + repeats) / claude_total * 100 if claude_total else 0
    checked = sum(1 for h in ledger["hosts"] if h["state"] == "checked")
    return f"""<title>Agent Spend Dashboard</title>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Newsreader:opsz,wght@6..72,600&family=IBM+Plex+Sans:wght@400;600&family=IBM+Plex+Mono&display=swap">
<style>{STYLE}</style>
<div class="wrap">
<header><div class="eyebrow">last {esc(ledger.get('days'))} days · {checked} of {len(ledger['hosts'])} machines scanned · generated {esc(generated[:16].replace('T', ' '))} UTC</div>
<h1>Agent spend, session by session</h1>
<p>Every Claude Code and Codex session in the window, priced at published list rates. Claude figures are list price; Codex figures are estimates.</p></header>
<div class="tiles">
<div><span class="k">Claude</span><span class="v">{money(claude_total)}</span><span class="s">{len(claude):,} sessions</span></div>
<div><span class="k">Codex (estimate)</span><span class="v">{money(codex_total)}</span><span class="s">{len(codex):,} sessions</span></div>
<div><span class="k">You typed</span><span class="v">{money(typed)}</span><span class="s">both agents</span></div>
<div><span class="k">Invoker ran it</span><span class="v">{money(fleet)}</span><span class="s">both agents</span></div>
<div><span class="k">Waiting + repeats</span><span class="v">{money(waiting + repeats)}</span><span class="s">{polling_share:.0f}% of Claude</span></div>
</div>
{warning_html}
<section><div class="head"><h2>Who started the work</h2></div><div class="panel scroll">{kind_table(rows)}</div></section>
<section><div class="head"><h2>Machines</h2></div><div class="panel scroll">{host_table(ledger, rows)}</div></section>
<section><div class="head"><h2>Where the money pools</h2></div><div class="two">
<div class="panel scroll">{band_table(rows)}</div>
<div class="panel"><h3>Claude spend by day</h3>{day_chart(rows)}</div></div></section>
<section><div class="head"><h2>Polling and helpers</h2></div><div class="panel">
<p>Calls that only waited ({money(waiting)}) or re-ran a command already run {esc(5)}+ times ({money(repeats)}) are priced directly.
Each one also lengthens the conversation every later call re-reads, so this is the floor, not the ceiling. Helper agents inside
those sessions cost {money(helpers)}.</p>
{session_table(claude, 10, lambda r: (r['polling'].get('waiting') or 0) + (r['polling'].get('repeat') or 0), 'Sessions that spent most on waiting and repeats')}
</div></section>
<section><div class="head"><h2>Most expensive sessions</h2></div><div class="panel">
{session_table(rows, top, lambda r: r['cost_total'], f'Top {top} by cost')}</div></section>
<section><div class="head"><h2>How this was counted</h2></div><div class="panel"><p class="hint">Built by <code>spend_ledger.py</code> and
<code>render_spend_report.py</code>. Claude lines sharing a message id are priced once; helper-agent transcripts count toward their
parent session. Remote sessions count as Invoker work. Codex is priced at the last model named in its log.</p></div></section>
</div>
"""


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("ledger")
    parser.add_argument("--out", required=True)
    parser.add_argument("--top", type=int, default=25)
    args = parser.parse_args(argv)
    try:
        ledger = load_ledger(args.ledger)
    except (OSError, ValueError) as err:
        print(f"render_spend_report: cannot read ledger {args.ledger}: {err}", file=sys.stderr)
        return 2
    page = render(ledger, args.top)
    with open(args.out, "w", encoding="utf-8") as handle:
        handle.write(page)
    unchecked = [h["name"] for h in ledger["hosts"] if h["state"] != "checked"]
    print(f"wrote {args.out}: {len(ledger['sessions'])} sessions; unchecked hosts: {', '.join(unchecked) or 'none'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
