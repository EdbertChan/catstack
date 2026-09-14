#!/usr/bin/env python3
"""Per-session spend ledger for Claude Code and Codex, on this machine or a fleet.

Usage:
    spend_ledger.py scan  [--days 30] [--host NAME] [--remote-is-fleet]
    spend_ledger.py fleet [--days 30] [--config ~/.invoker/config.json] [--out ledger.json]

scan prints one JSON document to stdout: every session modified in the window,
priced at published list rates, with who started it (typed / invoker /
scripted / eval), its helper-agent (subagent) share, and how much of it went to
waiting and re-running the same command.

fleet runs scan here, then pipes this same file over ssh to every
remoteTargets entry in the Invoker config and runs it there. Only the per-session
numbers come back; no transcript text leaves a machine. A host that cannot be
reached is recorded as unchecked with the reason, never as zero sessions.

Rules the numbers follow:
- Claude Code writes one JSONL line per content block, all sharing one
  message id and one usage snapshot. Lines are merged per message id before
  pricing and before tool calls are attributed.
- A session's subagents (<session>/subagents/*.jsonl) belong to the parent.
- Codex logs a running token total per session and no per-call model, so a
  Codex session is priced at the last model its log names. Codex dollars are
  estimates; every Codex row carries priced="estimate".
- Everything on a remote host counts as Invoker work when --remote-is-fleet.
- Invoker's own agent logs (~/.invoker/agent-sessions) are read only when no
  Codex rollout with the same id exists, so a run is never counted twice. Their
  events carry tokens but no model, so they are reported as unpriced tokens.
"""
import argparse
import collections
import datetime
import json
import os
import re
import subprocess
import sys
import time

CLAUDE_PRICES = {
    "claude-fable-5-1": (10.0, 50.0, 0.025),
    "claude-fable-5": (10.0, 50.0, 0.1),
    "claude-opus-5": (5.0, 25.0, 0.1),
    "claude-opus-5[1m]": (5.0, 25.0, 0.1),
    "claude-opus-4-8": (5.0, 25.0, 0.1),
    "claude-opus-4-7": (5.0, 25.0, 0.1),
    "claude-opus-4-6": (5.0, 25.0, 0.1),
    "claude-sonnet-5": (2.0, 10.0, 0.1),
    "claude-sonnet-4-6": (3.0, 15.0, 0.1),
    "claude-haiku-4-5": (1.0, 5.0, 0.1),
    "claude-haiku-4-5-20251001": (1.0, 5.0, 0.1),
}
CLAUDE_ALIASES = {"opus": "claude-opus-5", "sonnet": "claude-sonnet-5", "haiku": "claude-haiku-4-5"}
CODEX_PRICES = {
    "gpt-5.6-sol": (4.0, 0.40, 20.0),
    "gpt-5.6-terra": (2.0, 0.20, 12.0),
    "gpt-5.6-luna": (0.20, 0.02, 1.20),
    "gpt-5.5": (5.0, 0.50, 30.0),
    "gpt-5.4": (2.50, 0.25, 15.0),
    "gpt-5.3-codex": (1.75, 0.175, 14.0),
    "gpt-5.3-codex-spark": (1.75, 0.175, 14.0),
}
INVOKER_MARKERS = (".invoker/", ".invoker-", "invoker-worktrees", "invoker-merge-clones", "invoker-repos")
EVAL_MARKERS = ("llm-judge", "/var/folders/", "/private/var/folders/")
WAIT_TOOLS = {"ScheduleWakeup", "Monitor", "TaskOutput"}
WAIT_COMMAND = re.compile(
    r"^(sleep\b|date\b|echo idle|:$|true$|tail\b|gh (pr|run) (view|checks|list|watch)\b"
    r"|gh api \S*(check|status|runs)|ssh\b.*(query|status|tail|queue))"
)
REPEAT_THRESHOLD = 5
NOISE_PREFIXES = ("<task-notification", "[Request interrupted", "<local-command-stdout", "Caveat:")
STRIP = re.compile(r"<system-reminder>.*?</system-reminder>|</?command-[a-z-]+>|</?local-command-[a-z-]+>", re.S)


def normalise_command(command):
    text = re.sub(r"\s+", " ", command.strip())
    text = re.sub(r"\b[0-9a-f]{7,40}\b", "<sha>", text)
    return re.sub(r"\b\d{3,}\b", "<n>", text)[:120]


def parse_time(value, status):
    if not value:
        return None
    try:
        return datetime.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as err:
        status["bad_timestamp"] += 1
        print(f"spend_ledger: unreadable timestamp {value!r}: {err}", file=sys.stderr)
        return None


def recent_jsonl(root, cutoff, status):
    if not os.path.isdir(root):
        status[f"root_missing:{root}"] += 1
        return
    for dirpath, _dirs, files in os.walk(root):
        for name in files:
            if not name.endswith(".jsonl"):
                status["skipped_not_jsonl"] += 1
                continue
            path = os.path.join(dirpath, name)
            try:
                modified = os.path.getmtime(path)
            except OSError as err:
                status["unchecked_file"] += 1
                print(f"spend_ledger: cannot stat {path}: {err}", file=sys.stderr)
                continue
            if modified < cutoff:
                status["skipped_outside_window"] += 1
                continue
            yield path


def read_json_lines(path, status):
    try:
        handle = open(path, encoding="utf-8", errors="replace")
    except OSError as err:
        status["unchecked_file"] += 1
        print(f"spend_ledger: cannot open {path}: {err}", file=sys.stderr)
        return
    skipped = 0
    with handle:
        for line in handle:
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                skipped += 1
                continue
            if not isinstance(entry, dict):
                skipped += 1
                continue
            yield entry
    if skipped:
        status["non_object_lines"] += skipped
        status["files_with_non_object_lines"] += 1


def human_text(entry):
    content = (entry.get("message") or {}).get("content")
    if isinstance(content, str):
        text = content
    elif isinstance(content, list):
        if any(isinstance(b, dict) and b.get("type") == "tool_result" for b in content):
            return ""
        text = " ".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text")
    else:
        return ""
    text = re.sub(r"\s+", " ", STRIP.sub(" ", text)).strip()
    if not text or text.startswith(NOISE_PREFIXES):
        return ""
    return text


def classify(tool, cwd, originator, prompts, remote_is_fleet):
    lowered = (cwd or "").lower()
    if remote_is_fleet:
        return "invoker"
    if any(marker in lowered for marker in INVOKER_MARKERS):
        return "invoker"
    if tool == "codex":
        return "invoker" if originator == "codex_exec" else "typed"
    if any(marker in lowered for marker in EVAL_MARKERS):
        return "eval"
    return "typed" if prompts >= 2 else "scripted"


def claude_call_cost(model, usage):
    model = CLAUDE_ALIASES.get(model, model)
    price = CLAUDE_PRICES.get(model)
    if price is None:
        return None
    rate_in, rate_out, read_multiplier = price
    creation = usage.get("cache_creation") or {}
    write_hour = creation.get("ephemeral_1h_input_tokens", 0) or 0
    write_five = creation.get("ephemeral_5m_input_tokens", 0) or 0
    if write_hour + write_five == 0:
        write_five = usage.get("cache_creation_input_tokens", 0) or 0
    read = (usage.get("cache_read_input_tokens", 0) or 0) * rate_in * read_multiplier / 1e6
    write = (write_five * rate_in * 1.25 + write_hour * rate_in * 2.0) / 1e6
    output = (usage.get("output_tokens", 0) or 0) * rate_out / 1e6
    fresh = (usage.get("input_tokens", 0) or 0) * rate_in / 1e6
    return {"read": read, "write": write, "output": output, "input": fresh}


def scan_claude(home, cutoff, status):
    sessions = {}
    roots = [os.path.join(home, ".claude", "projects"), os.path.join(home, ".invoker", "claude-worker", "projects")]
    for root in roots:
        for path in recent_jsonl(root, cutoff, status):
            parts = path.split(os.sep)
            is_sub = "subagents" in parts
            owner = parts[parts.index("subagents") - 1] if is_sub else os.path.basename(path)[:-6]
            session = sessions.setdefault(owner, {
                "calls": [], "cwd": "", "prompts": 0, "first": None, "last": None, "unpriced_models": set(),
            })
            messages = collections.OrderedDict()
            for entry in read_json_lines(path, status):
                if entry.get("cwd") and not session["cwd"] and not is_sub:
                    session["cwd"] = entry["cwd"]
                kind = entry.get("type")
                if kind == "user" and not is_sub and not entry.get("isMeta") and not entry.get("isSidechain"):
                    if human_text(entry):
                        session["prompts"] += 1
                    continue
                if kind != "assistant":
                    continue
                message = entry.get("message") or {}
                usage = message.get("usage")
                if not isinstance(usage, dict):
                    status["assistant_line_without_usage"] += 1
                    continue
                key = (message.get("id"), entry.get("requestId"))
                if key not in messages:
                    messages[key] = {"model": message.get("model") or "", "usage": usage, "tools": [],
                                     "when": entry.get("timestamp"), "sub": is_sub or bool(entry.get("isSidechain"))}
                for block in message.get("content") or []:
                    if isinstance(block, dict) and block.get("type") == "tool_use":
                        messages[key]["tools"].append(block)
            for call in messages.values():
                session["calls"].append(call)
    return sessions


def summarise_claude(owner, session, host, remote_is_fleet, status):
    calls = session["calls"]
    if not calls:
        status["claude_session_without_calls"] += 1
        return None
    repeats = collections.Counter()
    for call in calls:
        for tool in call["tools"]:
            if tool.get("name") == "Bash":
                repeats[normalise_command((tool.get("input") or {}).get("command", ""))] += 1
    cost = collections.Counter()
    tokens = collections.Counter()
    polling = collections.Counter()
    models = collections.Counter()
    sub_cost = 0.0
    sub_calls = 0
    peak = 0
    times = []
    unpriced = 0
    for call in calls:
        usage = call["usage"]
        priced = claude_call_cost(call["model"], usage)
        models[call["model"]] += 1
        history = (usage.get("cache_read_input_tokens", 0) or 0) + (usage.get("cache_creation_input_tokens", 0) or 0)
        peak = max(peak, history)
        tokens["input"] += usage.get("input_tokens", 0) or 0
        tokens["cache_write"] += usage.get("cache_creation_input_tokens", 0) or 0
        tokens["cache_read"] += usage.get("cache_read_input_tokens", 0) or 0
        tokens["output"] += usage.get("output_tokens", 0) or 0
        stamp = parse_time(call["when"], status)
        if stamp:
            times.append(stamp)
        if priced is None:
            if call["model"] and call["model"] != "<synthetic>":
                unpriced += 1
            continue
        total = sum(priced.values())
        for part, value in priced.items():
            cost[part] += value
        if call["sub"]:
            sub_cost += total
            sub_calls += 1
        label = ""
        for tool in call["tools"]:
            name = tool.get("name")
            command = normalise_command((tool.get("input") or {}).get("command", "")) if name == "Bash" else ""
            if name in WAIT_TOOLS or (command and WAIT_COMMAND.match(command)):
                label = "waiting"
                break
            if command and repeats[command] >= REPEAT_THRESHOLD:
                label = "repeat"
        if label:
            polling[label] += total
    if unpriced:
        status["claude_calls_unpriced_model"] += unpriced
    total_cost = sum(cost.values())
    times.sort()
    cwd = session["cwd"]
    return {
        "tool": "claude", "host": host, "session": owner,
        "repo": os.path.basename(cwd.rstrip("/")) if cwd else "",
        "kind": classify("claude", cwd, "", session["prompts"], remote_is_fleet),
        "model": models.most_common(1)[0][0] if models else "",
        "originator": "", "priced": "list",
        "first": times[0].isoformat() if times else None,
        "last": times[-1].isoformat() if times else None,
        "hours": round((times[-1] - times[0]).total_seconds() / 3600, 2) if len(times) > 1 else 0.0,
        "calls": len(calls), "sub_calls": sub_calls, "prompts": session["prompts"],
        "tokens": dict(tokens), "peak_history": peak,
        "cost": {k: round(v, 4) for k, v in cost.items()}, "cost_total": round(total_cost, 4),
        "sub_cost": round(sub_cost, 4),
        "polling": {"waiting": round(polling["waiting"], 4), "repeat": round(polling["repeat"], 4)},
        "unpriced_calls": unpriced,
    }


def scan_codex(home, cutoff, host, remote_is_fleet, status):
    rows = []
    seen_ids = set()
    for root in [os.path.join(home, ".codex", "sessions")]:
        for path in recent_jsonl(root, cutoff, status):
            seen_ids.add(os.path.basename(path)[-42:-6])
            cwd, originator, model, totals, first, last = "", "", "", None, None, None
            for entry in read_json_lines(path, status):
                payload = entry.get("payload") or {}
                stamp = entry.get("timestamp")
                if stamp:
                    first = first or stamp
                    last = stamp
                if entry.get("type") == "session_meta":
                    cwd = payload.get("cwd") or cwd
                    originator = payload.get("originator") or originator
                elif entry.get("type") == "turn_context":
                    model = payload.get("model") or model
                elif payload.get("type") == "token_count" and isinstance(payload.get("info"), dict):
                    totals = payload["info"].get("total_token_usage") or totals
            if totals is None:
                status["codex_file_without_token_totals"] += 1
                continue
            fresh_all = totals.get("input_tokens", 0) or 0
            cached = min(totals.get("cached_input_tokens", 0) or 0, fresh_all)
            output = totals.get("output_tokens", 0) or 0
            price = CODEX_PRICES.get(model)
            cost = {"read": 0.0, "write": 0.0, "output": 0.0, "input": 0.0}
            if price is None:
                status["codex_session_unpriced_model"] += 1
            else:
                rate_in, rate_cached, rate_out = price
                cost = {"read": cached * rate_cached / 1e6, "write": 0.0,
                        "output": output * rate_out / 1e6, "input": (fresh_all - cached) * rate_in / 1e6}
            start, end = parse_time(first, status), parse_time(last, status)
            rows.append({
                "tool": "codex", "host": host, "session": os.path.basename(path)[:-6],
                "repo": os.path.basename(cwd.rstrip("/")) if cwd else "",
                "kind": classify("codex", cwd, originator, 0, remote_is_fleet),
                "model": model, "originator": originator, "priced": "estimate" if price else "unpriced",
                "first": start.isoformat() if start else None, "last": end.isoformat() if end else None,
                "hours": round((end - start).total_seconds() / 3600, 2) if start and end else 0.0,
                "calls": None, "sub_calls": None, "prompts": None,
                "tokens": {"input": fresh_all - cached, "cache_write": 0, "cache_read": cached, "output": output},
                "peak_history": None,
                "cost": {k: round(v, 4) for k, v in cost.items()}, "cost_total": round(sum(cost.values()), 4),
                "sub_cost": 0.0, "polling": {"waiting": None, "repeat": None}, "unpriced_calls": 0,
            })
    rows.extend(scan_invoker_agent_logs(home, cutoff, host, seen_ids, status))
    return rows


def scan_invoker_agent_logs(home, cutoff, host, rollout_ids, status):
    rows = []
    for path in recent_jsonl(os.path.join(home, ".invoker", "agent-sessions"), cutoff, status):
        session_id = os.path.basename(path)[:-6]
        if session_id in rollout_ids:
            status["agent_log_already_in_codex_rollouts"] += 1
            continue
        tokens = collections.Counter()
        model, first, last, turns = "", None, None, 0
        for entry in read_json_lines(path, status):
            stamp = entry.get("timestamp")
            if stamp:
                first = first or stamp
                last = stamp
            model = entry.get("model") or model
            usage = entry.get("usage")
            if entry.get("type") == "turn.completed" and isinstance(usage, dict):
                turns += 1
                for key in ("input_tokens", "cached_input_tokens", "output_tokens"):
                    tokens[key] += usage.get(key, 0) or 0
        if not turns:
            status["agent_log_without_usage"] += 1
            continue
        status["agent_log_unpriced_session"] += 1
        cached = min(tokens["cached_input_tokens"], tokens["input_tokens"])
        start, end = parse_time(first, status), parse_time(last, status)
        rows.append({
            "tool": "invoker-agent-log", "host": host, "session": session_id, "repo": "",
            "kind": "invoker", "model": model, "originator": "invoker", "priced": "unpriced",
            "first": start.isoformat() if start else None, "last": end.isoformat() if end else None,
            "hours": round((end - start).total_seconds() / 3600, 2) if start and end else 0.0,
            "calls": turns, "sub_calls": None, "prompts": None,
            "tokens": {"input": tokens["input_tokens"] - cached, "cache_write": 0, "cache_read": cached,
                       "output": tokens["output_tokens"]},
            "peak_history": None, "cost": {"read": 0.0, "write": 0.0, "output": 0.0, "input": 0.0},
            "cost_total": 0.0, "sub_cost": 0.0, "polling": {"waiting": None, "repeat": None}, "unpriced_calls": turns,
        })
    return rows


def run_scan(days, host, remote_is_fleet, home=None):
    home = home or os.path.expanduser("~")
    cutoff = time.time() - days * 86400
    status = collections.Counter()
    rows = []
    for owner, session in scan_claude(home, cutoff, status).items():
        row = summarise_claude(owner, session, host, remote_is_fleet, status)
        if row is None:
            continue
        rows.append(row)
    rows.extend(scan_codex(home, cutoff, host, remote_is_fleet, status))
    return {
        "host": host, "days": days, "remote_is_fleet": remote_is_fleet,
        "scanned_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "status": dict(status), "sessions": rows,
    }


def remote_targets(config_path):
    try:
        with open(config_path, encoding="utf-8") as handle:
            config = json.load(handle)
    except (OSError, ValueError) as err:
        print(f"spend_ledger: cannot read {config_path}: {err}", file=sys.stderr)
        return None
    targets = []
    for name, target in (config.get("remoteTargets") or {}).items():
        if target.get("host"):
            targets.append((name, f"{target.get('user') or 'root'}@{target['host']}"))
    return targets


def scan_remote(name, address, days, ssh_command, timeout):
    command = ssh_command + [address, "python3", "-", "scan", "--days", str(days), "--host", name, "--remote-is-fleet"]
    try:
        with open(os.path.abspath(__file__), "rb") as source:
            result = subprocess.run(command, stdin=source, capture_output=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return None, f"timed out after {timeout}s"
    except OSError as err:
        return None, f"could not start ssh: {err}"
    if result.returncode != 0:
        tail = result.stderr.decode(errors="replace").strip().splitlines()[-1:] or [""]
        return None, f"exit {result.returncode}: {tail[0][:200]}"
    try:
        return json.loads(result.stdout.decode(errors="replace")), None
    except ValueError as err:
        return None, f"unreadable output: {err}"


def run_fleet(days, config_path, ssh_command, timeout, local_name):
    ledger = {"generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(), "days": days,
              "hosts": [], "sessions": []}
    local = run_scan(days, local_name, False)
    ledger["hosts"].append({"name": local_name, "state": "checked", "reason": "", "status": local["status"],
                            "sessions": len(local["sessions"])})
    ledger["sessions"].extend(local["sessions"])
    targets = remote_targets(config_path)
    if targets is None:
        ledger["hosts"].append({"name": "remote targets", "state": "unchecked",
                                "reason": f"config unreadable: {config_path}", "status": {}, "sessions": 0})
        return ledger
    for name, address in targets:
        report, reason = scan_remote(name, address, days, ssh_command, timeout)
        if report is None:
            print(f"spend_ledger: {name} unchecked: {reason}", file=sys.stderr)
            ledger["hosts"].append({"name": name, "state": "unchecked", "reason": reason, "status": {}, "sessions": 0})
            continue
        ledger["hosts"].append({"name": name, "state": "checked", "reason": "", "status": report["status"],
                                "sessions": len(report["sessions"])})
        ledger["sessions"].extend(report["sessions"])
    return ledger


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="mode", required=True)
    scan = sub.add_parser("scan")
    scan.add_argument("--days", type=int, default=30)
    scan.add_argument("--host", default="local")
    scan.add_argument("--remote-is-fleet", action="store_true")
    fleet = sub.add_parser("fleet")
    fleet.add_argument("--days", type=int, default=30)
    fleet.add_argument("--config", default=os.path.expanduser("~/.invoker/config.json"))
    fleet.add_argument("--out", default="")
    fleet.add_argument("--local-name", default="local")
    fleet.add_argument("--timeout", type=int, default=900)
    fleet.add_argument("--ssh", default="ssh -o BatchMode=yes -o ConnectTimeout=10")
    args = parser.parse_args(argv)
    if args.mode == "scan":
        json.dump(run_scan(args.days, args.host, args.remote_is_fleet), sys.stdout)
        return 0
    ledger = run_fleet(args.days, args.config, args.ssh.split(), args.timeout, args.local_name)
    text = json.dumps(ledger)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as handle:
            handle.write(text)
        unchecked = [h["name"] for h in ledger["hosts"] if h["state"] != "checked"]
        print(f"wrote {args.out}: {len(ledger['sessions'])} sessions from {len(ledger['hosts'])} hosts; "
              f"unchecked: {', '.join(unchecked) or 'none'}")
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
