#!/usr/bin/env python3
"""Render a spend ledger as a deterministic interactive session-mining report.

Usage:
    spend_ledger_report.py LEDGER.json --out spend-ledger-report.html

The input is the output of `spend_ledger.py scan` or `spend_ledger.py fleet`.
The output is one self-contained HTML file: inline CSS, inline JavaScript, and
an embedded copy of the normalized ledger data. Unchecked hosts, missing token
checkpoints, and absent timestamps are represented as explicit states instead
of being folded into zeros.
"""
import argparse
import datetime
import html
import json
import sys

TOKEN_FIELDS = ("input", "cache_write", "cache_read", "output")
MISSING = "missing"

STYLE = """
:root{--bg:#f4f1ea;--panel:#fffdf8;--ink:#172026;--muted:#52646b;--quiet:#7b8a8f;--line:#d8d1c4;
--line-strong:#aeb9b8;--accent:#0f766e;--accent-2:#8a4f15;--hot:#b42318;--cool:#2454a6;--chip:#edf7f5}
*{box-sizing:border-box}
html{background:var(--bg);color:var(--ink);font-family:Arial,Helvetica,sans-serif;font-size:15px;line-height:1.45}
body{margin:0}
.wrap{max-width:1240px;margin:0 auto;padding:28px 18px 56px;display:grid;gap:18px}
header{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:14px;align-items:end;border-bottom:2px solid var(--line-strong);padding-bottom:14px}
h1,h2,h3,p{margin:0}
h1{font-size:32px;line-height:1.1;font-weight:700}
h2{font-size:18px}h3{font-size:15px}
.sub{color:var(--muted);max-width:76ch}.meta{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;color:var(--muted);font-size:12px;text-align:right}
.summary{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:1px;border:1px solid var(--line);background:var(--line)}
.tile{background:var(--panel);padding:12px}.tile b{display:block;font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:22px}.tile span{color:var(--muted);font-size:12px}
.grid{display:grid;grid-template-columns:360px minmax(0,1fr);gap:18px;align-items:start}
.panel{background:var(--panel);border:1px solid var(--line);border-radius:6px;padding:14px;display:grid;gap:12px}
.toolbar{display:grid;gap:8px}.toolbar input,.toolbar select{width:100%;border:1px solid var(--line-strong);background:white;color:var(--ink);border-radius:4px;padding:8px;font:inherit}
.top-list{display:grid;gap:6px}.top-button{display:grid;grid-template-columns:34px 1fr auto;gap:8px;align-items:center;width:100%;border:1px solid var(--line);background:white;color:var(--ink);border-radius:4px;padding:8px;text-align:left;cursor:pointer}
.top-button:hover,.top-button.active{border-color:var(--accent);background:var(--chip)}
.rank{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;color:var(--accent);font-weight:700}.money{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-variant-numeric:tabular-nums}.small{font-size:12px;color:var(--muted)}
.session-list{max-height:430px;overflow:auto;border:1px solid var(--line);background:white}.session-row{display:grid;grid-template-columns:1fr auto;gap:8px;border:0;border-bottom:1px solid var(--line);background:white;color:var(--ink);width:100%;padding:8px;text-align:left;cursor:pointer}
.session-row:hover{background:var(--chip)}.session-row[hidden]{display:none}
.detail-head{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:12px;align-items:start}.badges{display:flex;gap:6px;flex-wrap:wrap;justify-content:flex-end}.badge{border:1px solid var(--line-strong);border-radius:999px;padding:2px 8px;font-size:12px;background:white}.badge.hot{color:var(--hot);border-color:#efaaa3}.badge.cool{color:var(--cool);border-color:#a7bce5}
.facts{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:1px;border:1px solid var(--line);background:var(--line)}.fact{background:white;padding:9px}.fact span{display:block;color:var(--quiet);font-size:11px;text-transform:uppercase}.fact b{font-family:ui-monospace,SFMono-Regular,Menlo,monospace}
.scroll{overflow:auto}table{width:100%;border-collapse:collapse;background:white}th,td{border-bottom:1px solid var(--line);padding:7px 8px;text-align:left;vertical-align:top}th{font-size:11px;color:var(--muted);text-transform:uppercase;font-weight:700;background:#faf8f2}td.num,th.num{text-align:right;font-family:ui-monospace,SFMono-Regular,Menlo,monospace}
.state-ok{color:var(--accent)}.state-missing{color:var(--hot)}.state-note{color:var(--muted)}
.unchecked{border-left:4px solid var(--hot)}code{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;background:#f1ede3;padding:1px 4px;border-radius:3px}
@media (max-width:860px){header,.grid,.detail-head{grid-template-columns:1fr}.meta{text-align:left}.badges{justify-content:flex-start}}
@media print{html{background:white}.wrap{max-width:none;padding:0}.panel,.summary{break-inside:avoid}thead{position:static}.grid{display:block}.panel{margin-bottom:14px}.toolbar,.top-button,.session-row{break-inside:avoid}}
"""

SCRIPT = """
const data = JSON.parse(document.getElementById("ledger-data").textContent);
const byKey = new Map(data.sessions.map((session) => [session.key, session]));
const select = document.getElementById("session-select");
const search = document.getElementById("session-search");
const rows = Array.from(document.querySelectorAll(".session-row"));
function esc(value){const map = {"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"};return String(value ?? "").replace(/[&<>"']/g, (ch) => map[ch]);}
function tokenCell(tokens){if(!tokens){return "<span class='state-missing'>missing</span>";}return data.token_fields.map((field) => `${field}:${Number(tokens[field] || 0).toLocaleString()}`).join("<br>");}
function stateCell(event){const missing = event.missing || [];if(missing.length){return `<span class='state-missing'>missing: ${esc(missing.join(", "))}</span>`;}return `<span class='state-ok'>${esc(event.cost_status || "ok")}</span>`;}
function detail(session){
  const activity = session.activity.map((event) => `<tr><td><code>${esc(event.timestamp_utc || "missing")}</code></td><td>${esc(event.label || event.kind)}</td><td>${esc(event.source || "")}</td><td>${tokenCell(event.token_delta)}</td><td>${tokenCell(event.cumulative_tokens)}</td><td class='num'>${event.cost_delta == null ? "<span class='state-note'>n/a</span>" : "$" + Number(event.cost_delta).toFixed(4)}</td><td>${stateCell(event)}</td></tr>`).join("");
  document.getElementById("session-detail").innerHTML = `<div class='detail-head'><div><h2>${esc(session.title)}</h2><p class='sub'>${esc(session.subtitle)}</p></div><div class='badges'>${session.badges.map((badge) => `<span class='badge ${badge.kind}'>${esc(badge.text)}</span>`).join("")}</div></div><div class='facts'>${session.facts.map((fact) => `<div class='fact'><span>${esc(fact.label)}</span><b>${esc(fact.value)}</b></div>`).join("")}</div><div class='scroll'><table><thead><tr><th>Raw UTC</th><th>Activity</th><th>Source</th><th>Token Delta</th><th>Checkpoint</th><th class='num'>Cost Delta</th><th>State</th></tr></thead><tbody>${activity}</tbody></table></div>`;
  select.value = session.key;
  document.querySelectorAll(".top-button").forEach((button) => button.classList.toggle("active", button.dataset.key === session.key));
}
function choose(key){const session = byKey.get(key);if(session){detail(session);}}
function filterSessions(){const needle = search.value.trim().toLowerCase();rows.forEach((row) => {row.hidden = needle && !row.dataset.search.includes(needle);});}
select.addEventListener("change", () => choose(select.value));
search.addEventListener("input", filterSessions);
document.querySelectorAll("[data-key]").forEach((node) => node.addEventListener("click", () => choose(node.dataset.key)));
choose(data.default_session_key);
"""


def esc(value):
    return html.escape(str(value if value is not None else ""))


def money(value):
    if value is None:
        return MISSING
    if abs(value) >= 100:
        return f"${value:,.0f}"
    return f"${value:,.2f}"


def count(value):
    if value is None:
        return MISSING
    return f"{value:,}" if isinstance(value, int) else str(value)


def token_total(tokens):
    tokens = tokens or {}
    return sum(tokens.get(field, 0) or 0 for field in TOKEN_FIELDS)


def parse_utc(value):
    if not value:
        return None
    try:
        return datetime.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def sort_activity(events):
    def key(event):
        stamp = parse_utc(event.get("timestamp_utc"))
        return (stamp is None, stamp or datetime.datetime.max.replace(tzinfo=datetime.timezone.utc),
                event.get("kind") or "", event.get("label") or "")
    return sorted(events, key=key)


def load_ledger(path):
    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)
    if "hosts" not in data:
        data = {"generated_at": data.get("scanned_at"), "days": data.get("days"),
                "hosts": [{"name": data.get("host", "local"), "state": "checked", "reason": "",
                           "status": data.get("status", {}), "sessions": len(data.get("sessions", []))}],
                "sessions": data.get("sessions", [])}
    return data


def missing_activity():
    return [{"timestamp_utc": None, "kind": "activity_missing", "label": "no activity timeline was recorded",
             "source": "", "model": "", "tools": [], "tokens": None, "token_delta": None,
             "cumulative_tokens": None, "cost_delta": None, "cost_status": "missing",
             "missing": ["activity"]}]


def normalize_activity(row):
    events = row.get("activity") or missing_activity()
    normalized = []
    for event in sort_activity(events):
        item = dict(event)
        item.setdefault("timestamp_utc", None)
        item.setdefault("kind", "unknown")
        item.setdefault("label", item["kind"])
        item.setdefault("source", "")
        item.setdefault("model", "")
        item.setdefault("tools", [])
        item.setdefault("tokens", None)
        item.setdefault("token_delta", None)
        item.setdefault("cumulative_tokens", None)
        item.setdefault("cost_delta", None)
        item.setdefault("cost_status", "not_applicable")
        item["missing"] = sorted(set(item.get("missing") or []))
        if not item["timestamp_utc"] and "timestamp" not in item["missing"]:
            item["missing"].append("timestamp")
        normalized.append(item)
    return normalized


def field_state(row, field):
    return MISSING if row.get(field) is None else row.get(field)


def normalize_session(row, rank):
    key = f"{row.get('host', '')}::{row.get('tool', '')}::{row.get('session', '')}"
    title = f"#{rank} {row.get('session') or MISSING}"
    subtitle = f"{row.get('tool') or MISSING} on {row.get('host') or MISSING} - {row.get('repo') or 'repo missing'}"
    missing_fields = [field for field in ("first", "last", "calls", "prompts", "peak_history")
                      if row.get(field) is None]
    priced = row.get("priced") or MISSING
    badges = [
        {"text": money(row.get("cost_total")), "kind": "cool"},
        {"text": priced, "kind": "hot" if priced == "unpriced" else ""},
    ]
    if missing_fields:
        badges.append({"text": "missing: " + ", ".join(missing_fields), "kind": "hot"})
    activity = normalize_activity(row)
    facts = [
        {"label": "rank", "value": f"#{rank}"},
        {"label": "cost", "value": money(row.get("cost_total"))},
        {"label": "tokens", "value": count(token_total(row.get("tokens")))},
        {"label": "first UTC", "value": field_state(row, "first")},
        {"label": "last UTC", "value": field_state(row, "last")},
        {"label": "calls", "value": count(row.get("calls"))},
        {"label": "prompts", "value": count(row.get("prompts"))},
        {"label": "model", "value": row.get("model") or MISSING},
    ]
    search = " ".join(str(row.get(field) or "") for field in
                      ("session", "host", "tool", "repo", "kind", "model", "priced")).lower()
    return {
        "key": key, "rank": rank, "title": title, "subtitle": subtitle, "search": search,
        "badges": badges, "facts": facts, "activity": activity,
        "cost_total": row.get("cost_total") or 0.0,
        "session": row.get("session") or MISSING,
        "host": row.get("host") or MISSING,
        "tool": row.get("tool") or MISSING,
        "kind": row.get("kind") or MISSING,
        "priced": priced,
    }


def prepare_report_data(ledger):
    rows = sorted(ledger.get("sessions", []),
                  key=lambda row: (-(row.get("cost_total") or 0.0), row.get("host") or "", row.get("session") or ""))
    sessions = [normalize_session(row, index + 1) for index, row in enumerate(rows)]
    top_sessions = sessions[:10]
    checked = [host for host in ledger.get("hosts", []) if host.get("state") == "checked"]
    unchecked = [host for host in ledger.get("hosts", []) if host.get("state") != "checked"]
    total_cost = sum(session["cost_total"] for session in sessions)
    unpriced = [session for session in sessions if session["priced"] == "unpriced"]
    return {
        "generated_at": ledger.get("generated_at") or ledger.get("scanned_at") or MISSING,
        "days": ledger.get("days"),
        "token_fields": list(TOKEN_FIELDS),
        "sessions": sessions,
        "top_sessions": top_sessions,
        "default_session_key": top_sessions[0]["key"] if top_sessions else "",
        "hosts": ledger.get("hosts", []),
        "unchecked_hosts": unchecked,
        "summary": {
            "sessions": len(sessions),
            "top_count": len(top_sessions),
            "checked_hosts": len(checked),
            "host_count": len(ledger.get("hosts", [])),
            "total_cost": total_cost,
            "unpriced_sessions": len(unpriced),
        },
    }


def render_top_buttons(top_sessions):
    return "\n".join(
        f"<button class='top-button' data-key='{esc(session['key'])}'><span class='rank'>#{session['rank']}</span>"
        f"<span>{esc(session['session'])}<br><span class='small'>{esc(session['host'])} - {esc(session['tool'])}</span></span>"
        f"<span class='money'>{esc(money(session['cost_total']))}</span></button>"
        for session in top_sessions
    ) or "<p class='small'>No scanned sessions.</p>"


def render_session_options(sessions):
    return "\n".join(
        f"<option value='{esc(session['key'])}'>#{session['rank']} {esc(session['session'])} - "
        f"{esc(money(session['cost_total']))}</option>" for session in sessions
    )


def render_session_rows(sessions):
    return "\n".join(
        f"<button class='session-row' data-key='{esc(session['key'])}' data-search='{esc(session['search'])}'>"
        f"<span>#{session['rank']} {esc(session['session'])}<br><span class='small'>{esc(session['host'])} - "
        f"{esc(session['tool'])} - {esc(session['priced'])}</span></span><span class='money'>"
        f"{esc(money(session['cost_total']))}</span></button>" for session in sessions
    ) or "<p class='small'>No sessions in this ledger.</p>"


def render_unchecked(hosts):
    if not hosts:
        return "<p class='small'>All configured hosts in this ledger were scanned.</p>"
    rows = "".join(
        f"<tr><td>{esc(host.get('name'))}</td><td class='state-missing'>unscanned</td>"
        f"<td>{esc(host.get('reason') or MISSING)}</td></tr>" for host in hosts
    )
    return f"<div class='scroll'><table><thead><tr><th>Host</th><th>State</th><th>Reason</th></tr></thead><tbody>{rows}</tbody></table></div>"


def render_missing_sessions(sessions):
    rows = []
    for session in sessions:
        missing = []
        for event in session["activity"]:
            if event.get("missing"):
                missing.append(f"{', '.join(event['missing'])} ({event.get('label') or event.get('kind')})")
        if missing:
            rows.append(f"<tr><td>{esc(session['session'])}</td><td>{esc(session['host'])}</td>"
                        f"<td class='state-missing'>missing: {esc('; '.join(missing))}</td></tr>")
    if not rows:
        return "<p class='small'>No session-level missing-data states were recorded.</p>"
    return ("<div class='scroll'><table><thead><tr><th>Session</th><th>Host</th><th>State</th></tr></thead><tbody>"
            + "".join(rows) + "</tbody></table></div>")


def render_html(ledger):
    data = prepare_report_data(ledger)
    embedded = json.dumps(data, sort_keys=True, separators=(",", ":")).replace("<", "\\u003c")
    summary = data["summary"]
    return f"""<!doctype html>
<meta charset="utf-8">
<title>Spend Ledger Session Mining</title>
<style>{STYLE}</style>
<div class="wrap">
  <header>
    <div>
      <h1>Spend Ledger Session Mining</h1>
      <p class="sub">Top spend is ranked first, and every scanned session is searchable and selectable with raw UTC activity, token deltas, checkpoints, and explicit missing-data states.</p>
    </div>
    <div class="meta">generated {esc(data['generated_at'])}<br>window {esc(data['days'])} days</div>
  </header>
  <section class="summary" aria-label="ledger summary">
    <div class="tile"><span>Scanned sessions</span><b>{summary['sessions']:,}</b></div>
    <div class="tile"><span>Top spend list</span><b>{summary['top_count']}</b></div>
    <div class="tile"><span>Total priced spend</span><b>{esc(money(summary['total_cost']))}</b></div>
    <div class="tile"><span>Hosts scanned</span><b>{summary['checked_hosts']}/{summary['host_count']}</b></div>
    <div class="tile"><span>Unpriced sessions</span><b>{summary['unpriced_sessions']:,}</b></div>
  </section>
  <main class="grid">
    <aside class="panel">
      <h2>Top 10 Spend Sessions</h2>
      <div class="top-list">{render_top_buttons(data['top_sessions'])}</div>
      <div class="toolbar">
        <h2>All Scanned Sessions</h2>
        <input id="session-search" type="search" placeholder="Search session, host, tool, model, state">
        <select id="session-select">{render_session_options(data['sessions'])}</select>
      </div>
      <div class="session-list">{render_session_rows(data['sessions'])}</div>
    </aside>
    <section class="panel" id="session-detail" aria-live="polite"></section>
  </main>
  <section class="panel unchecked">
    <h2>Missing Or Unscanned Data</h2>
    {render_unchecked(data['unchecked_hosts'])}
    {render_missing_sessions(data['sessions'])}
  </section>
</div>
<script type="application/json" id="ledger-data">{embedded}</script>
<script>{SCRIPT}</script>
"""


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("ledger")
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    try:
        ledger = load_ledger(args.ledger)
    except (OSError, ValueError) as err:
        print(f"spend_ledger_report: cannot read ledger {args.ledger}: {err}", file=sys.stderr)
        return 2
    page = render_html(ledger)
    try:
        with open(args.out, "w", encoding="utf-8") as handle:
            handle.write(page)
    except OSError as err:
        print(f"spend_ledger_report: cannot write report {args.out}: {err}", file=sys.stderr)
        return 2
    data = prepare_report_data(ledger)
    unchecked = [host.get("name", "") for host in data["unchecked_hosts"]]
    print(f"wrote {args.out}: {len(data['sessions'])} sessions; top 10 entries: {len(data['top_sessions'])}; "
          f"unchecked hosts: {', '.join(unchecked) or 'none'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
