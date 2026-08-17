#!/usr/bin/env python3
"""Token-spend, thrash, and model-tier audit across coding-agent tools.

Usage:
    token_audit.py claude <path-to-session.jsonl>
    token_audit.py claude <path-to-session.jsonl> --out /tmp/audit.json
    token_audit.py codex  <path-to-rollout.jsonl>
    token_audit.py omp    <path-to-omp-session.jsonl>
    token_audit.py cursor <path-to-agent-transcript.jsonl>
    token_audit.py remotes                 # list configured remote targets (names only)

With --out (claude mode only), write a JSON report of named yes/no flags with
rationales to that path and print a short summary on stdout. Without --out,
print the full prose report (legacy default).

All four tools log locally as JSONL, but only Claude Code, Codex, and OMP
embed per-turn token usage. OMP (~/.omp/agent/sessions/**/*.jsonl) is the
richest of the three: each assistant message carries usage.input/output/
cacheRead/cacheWrite plus an already-computed usage.cost.{input,output,
cacheRead,total} in dollars - no pricing table needed to get real $ figures
out of an OMP session. OMP mode also does real thrash detection (redundant
reads, tool errors), not just cost summation - tool calls are `toolCall`
content blocks (name + arguments) on assistant messages, and results are
separate `toolResult`-role messages carrying `isError`; `read`/`write` name
the file in `arguments.path`, `edit` embeds it in an apple-patch header
inside `arguments.input` (`[/path/to/file.ts#anchor]`) - all verified
against real sessions, not guessed. Cursor's local agent-transcripts (~/.cursor/projects/*/
agent-transcripts/*/*.jsonl) carry no token/usage/model fields at all -
verified by scanning real transcripts, not assumed. So `cursor` mode only
reports thrash (redundant tool calls), never token/cost numbers, and says so.

This script only counts and flags mechanically. It does not judge whether a
flagged item was actually avoidable, and it never SSHes anywhere - `remotes`
just reads target *names* out of ~/.invoker/config.json (if present) so the
reflect Cost lens knows what remote scanning would be possible; actually
running an audit against a remote host is a separate, explicitly-confirmed
step outside this script.
"""
import json, sys, hashlib, os, re
from collections import Counter

# Published per-token list prices, $/MTok (see claude-api skill, cached 2026-06-24).
# Cache-read tokens are billed at ~0.1x the model's own input price.
PRICING = {
    "claude-sonnet-5": {"input": 3.00, "output": 15.00, "cache_read": 0.30},
    "claude-haiku-4-5": {"input": 1.00, "output": 5.00, "cache_read": 0.10},
}


def model_tier_savings(simple_turn_output_tokens, from_model="claude-sonnet-5", to_model="claude-haiku-4-5"):
    """Deterministic backtest: what would it have cost to run the flagged
    lookup-only turns' OUTPUT tokens on a cheaper model instead, at published
    list prices. Input/cache-read tokens for those turns aren't tracked at
    per-turn granularity, so this only prices the output side - a lower bound
    on total savings, not the full figure. Returns (actual_$, cheaper_$, saved_$)."""
    actual = simple_turn_output_tokens * PRICING[from_model]["output"] / 1_000_000
    cheaper = simple_turn_output_tokens * PRICING[to_model]["output"] / 1_000_000
    return actual, cheaper, actual - cheaper

def sig(name, inp):
    s = json.dumps(inp, sort_keys=True)[:2000]
    return hashlib.sha1(s.encode()).hexdigest(), s

# A Bash command matching this counts as "the agent checked its own work" -
# the fast-feedback-loop signal used by the two detectors below. Heuristic
# only: it flags the shape of a verification attempt, not whether the right
# check ran or whether it passed.
VERIFY_RE = re.compile(
    r"\b(pytest|jest|vitest|mocha|rspec|unittest|go\s+(test|vet|build)|"
    r"cargo\s+(test|check|build)|mvn\s+\S*test|gradle\s+\S*test|make\s+test|"
    r"(npm|pnpm|yarn)\s+(run\s+)?test|tsc\b|typecheck|eslint|ruff|flake8|pylint)\b",
    re.I,
)

# A Bash command directly interpreting/running the just-edited file (no
# test framework involved) also counts as verification for a one-off
# script - e.g. `python3 foo.py`, `node foo.js`, `./foo.sh`. VERIFY_RE alone
# missed this: confirmed against a real session where a 9-edit streak on
# claude_session_cost.py was flagged even though every edit cluster was
# immediately followed by `python3 claude_session_cost.py ...` and the
# agent read its real output before editing again - the feedback loop was
# in use, the detector just didn't recognize the shape. Unlike VERIFY_RE
# (which resets every file's streak on any match), this only counts as
# verification for the specific file(s) actually being run.
DIRECT_RUN_RE = re.compile(
    r"(?:\b(?:python3?|node|ruby|bash|sh|perl)\s+\S*?([\w.-]+\.\w+)\b|"
    r"\./([\w./-]*[\w.-]+\.\w+)\b)"
)


def _direct_run_targets(command):
    """Basenames of any file(s) a Bash command directly executes, e.g.
    'python3 tools/claude_session_cost.py --top 5' -> {'claude_session_cost.py'},
    './run-all.sh' -> {'run-all.sh'}. Two alternatives because a bare `./foo.sh`
    has no space between the `./` prefix and the filename, unlike an
    interpreter invocation - verified against both real shapes, not merged
    into one pattern that silently missed the no-space case."""
    hits = set()
    for m in DIRECT_RUN_RE.finditer(command or ""):
        name = m.group(1) or m.group(2)
        if name:
            hits.add(os.path.basename(name))
    return hits

def read_jsonl(path):
    out = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def _flag(name, value, count, rationale):
    """One named yes/no check with a rationale — same shape as an MLflow judge
    Feedback, without depending on MLflow."""
    return {"name": name, "value": value, "count": count, "rationale": rationale}


def audit_claude(path, out_path=None):
    # Claude Code writes one JSONL line per content block (thinking/text/tool_use),
    # but every block belonging to the same message.id carries the SAME usage
    # snapshot for that whole message. Summing every line triple/quadruple-counts
    # tokens - verified against real transcripts, where 299 raw assistant lines
    # turned out to be only 141 unique messages. Dedupe by message.id before
    # adding to any token total; still walk every line for tool_use extraction,
    # since each line's content block is genuinely distinct.
    lines = read_jsonl(path)
    total_input = total_output = total_cache_read = total_cache_creation = 0
    n_assistant = 0
    counted_msg_ids = set()
    models = Counter()
    tool_use = {}
    tool_calls_seq = []
    errors_detail = []  # (seq, tool_name, error_text) - for recurring-failure detection
    cache_points = []
    seq = 0
    simple_turns = 0  # turns whose only tool calls are Read/Grep/Glob - cheap-model candidates
    simple_turn_output_tokens = 0
    # Accumulate tool names per message.id across the multi-line Claude Code
    # layout (one JSONL line per content block). Judging simple_only per line
    # falsely flags a Read+Edit turn as lookup-only when Read and Edit land on
    # different lines of the same message — found by e2e sample fixtures.
    msg_tool_names = {}  # mid -> [tool name, ...]
    msg_output_tokens = {}  # mid -> output_tokens (from first line of that message)

    for d in lines:
        if d.get("type") == "assistant":
            msg = d.get("message", {})
            mid = msg.get("id")
            u = msg.get("usage", {})
            is_new_msg = mid not in counted_msg_ids
            if is_new_msg:
                counted_msg_ids.add(mid)
                total_input += u.get("input_tokens", 0)
                total_output += u.get("output_tokens", 0)
                total_cache_read += u.get("cache_read_input_tokens", 0)
                total_cache_creation += u.get("cache_creation_input_tokens", 0)
                n_assistant += 1
                models[msg.get("model", "?")] += 1
                cache_points.append((seq, u.get("cache_creation_input_tokens", 0), u.get("cache_read_input_tokens", 0)))
                msg_output_tokens[mid] = u.get("output_tokens", 0)
            for block in msg.get("content", []) or []:
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    seq += 1
                    name = block.get("name")
                    msg_tool_names.setdefault(mid, []).append(name)
                    tool_use[block.get("id")] = (name, block.get("input"), seq)
                    tool_calls_seq.append((seq, name, block.get("input"), block.get("id")))
        elif d.get("type") == "user":
            content = d.get("message", {}).get("content")
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "tool_result" and block.get("is_error"):
                        tid = block.get("tool_use_id")
                        name, inp, s = tool_use.get(tid, ("?", {}, None))
                        tool_calls_seq.append((s, "__ERROR__:" + str(name), inp, tid))
                        err_content = block.get("content")
                        if isinstance(err_content, list):
                            err_text = " ".join(b.get("text", "") for b in err_content if isinstance(b, dict))
                        else:
                            err_text = str(err_content or "")
                        errors_detail.append((s, name, err_text))

    LOOKUP_TOOLS = ("Read", "Grep", "Glob")
    for mid, names in msg_tool_names.items():
        if names and all(n in LOOKUP_TOOLS for n in names):
            simple_turns += 1
            simple_turn_output_tokens += msg_output_tokens.get(mid, 0)

    grand = total_input + total_output + total_cache_read + total_cache_creation
    from_model = models.most_common(1)[0][0] if models else "claude-sonnet-5"
    tier_backtest = None
    if from_model in PRICING and simple_turn_output_tokens:
        actual, cheaper, saved = model_tier_savings(simple_turn_output_tokens, from_model=from_model)
        tier_backtest = {"actual": actual, "cheaper": cheaper, "saved": saved, "from_model": from_model}

    # Verified against 3 independent real-session audits: comparing file_path alone
    # flags windowed paging of a large file (different offset/limit each call) as
    # "redundant" when it's normal incremental exploration - one session had 64/67
    # flagged pairs turn out to be different windows of the same file. Only a call
    # with the IDENTICAL (offset, limit) as a prior read of the same file, unedited
    # since, is a genuine duplicate.
    last_read_seq, edited_since, redundant = {}, set(), []
    for s, name, inp, ident in sorted(tool_calls_seq, key=lambda x: x[0] or 0):
        if name in ("Edit", "Write") and isinstance(inp, dict):
            edited_since.add(inp.get("file_path"))
        elif name == "Read" and isinstance(inp, dict):
            fp = inp.get("file_path")
            window = (inp.get("offset"), inp.get("limit"))
            key = (fp, window)
            if key in last_read_seq and fp not in edited_since:
                redundant.append((fp, window, last_read_seq[key], s))
            last_read_seq[key] = s
            edited_since.discard(fp)

    errors = [(s, name, inp) for s, name, inp, ident in tool_calls_seq if isinstance(name, str) and name.startswith("__ERROR__:")]
    tool_error_counts = Counter(name[len("__ERROR__:"):] for s, name, inp in errors)
    file_error_counts = Counter(
        inp.get("file_path") for s, name, inp in errors if isinstance(inp, dict) and inp.get("file_path")
    )

    # Same-problem-thrash detectors
    sig_groups = {}
    for s, name, text in errors_detail:
        if "doesn't want to proceed" in text:
            continue  # user rejection, not a stuck-on-the-same-problem signal
        norm = re.sub(r"\d+", "#", text.strip())[:120]
        sig_groups.setdefault((name, norm), []).append(s)
    recurring = {k: v for k, v in sig_groups.items() if len(v) > 1}

    edits_since_verify, file_streak_max = {}, {}
    global_streak = global_streak_max = verify_count = direct_run_verify_count = 0
    THRESH = 3
    for s, name, inp, ident in sorted(tool_calls_seq, key=lambda x: x[0] or 0):
        if name == "Bash" and isinstance(inp, dict) and VERIFY_RE.search(inp.get("command") or ""):
            verify_count += 1
            edits_since_verify.clear()
            global_streak = 0
        elif name == "Bash" and isinstance(inp, dict):
            targets = _direct_run_targets(inp.get("command") or "")
            edited_basenames = {os.path.basename(fp) for fp in edits_since_verify if fp}
            hit = targets & edited_basenames
            if hit:
                direct_run_verify_count += 1
                edits_since_verify.clear()
                global_streak = 0
        elif name in ("Edit", "Write") and isinstance(inp, dict):
            fp = inp.get("file_path")
            edits_since_verify[fp] = edits_since_verify.get(fp, 0) + 1
            file_streak_max[fp] = max(file_streak_max.get(fp, 0), edits_since_verify[fp])
            global_streak += 1
            global_streak_max = max(global_streak_max, global_streak)
    flagged_files = {fp: n for fp, n in file_streak_max.items() if n >= THRESH}

    creations = sorted(c for _, c, r in cache_points if c > 0)
    spikes = []
    median = 0
    if creations:
        median = creations[len(creations)//2]
        threshold = max(50_000, median * 5)
        seen = set()
        for s, c, r in cache_points:
            if c >= threshold and c not in seen:
                seen.add(c)
                spikes.append((s, c, r))

    flags = [
        _flag(
            "model-tier-candidates",
            "yes" if simple_turns else "no",
            simple_turns,
            (
                f"{simple_turns}/{n_assistant} turns called only Read/Grep/Glob "
                f"({simple_turn_output_tokens:,} output tokens on those turns)"
                + (
                    f"; output-side backtest ${tier_backtest['actual']:.4f} at "
                    f"{tier_backtest['from_model']} vs ${tier_backtest['cheaper']:.4f} at "
                    f"claude-haiku-4-5 -> ${tier_backtest['saved']:.4f} saved (lower bound)"
                    if tier_backtest else ""
                )
            ),
        ),
        _flag(
            "redundant-reads",
            "yes" if redundant else "no",
            len(redundant),
            f"{len(redundant)} redundant re-read(s) of an identical file+offset/limit window with no edit in between",
        ),
        _flag(
            "recurring-failure-signatures",
            "yes" if recurring else "no",
            len(recurring),
            f"{len(recurring)} recurring failure signature(s) (same error shape repeating across attempts)",
        ),
        _flag(
            "no-verify-edit-streak",
            "yes" if flagged_files or global_streak_max >= THRESH else "no",
            global_streak_max,
            (
                f"longest edit streak with zero verification: {global_streak_max}; "
                f"{len(flagged_files)} file(s) at or above threshold {THRESH}; "
                f"verify Bash calls={verify_count}, direct-run verifies={direct_run_verify_count}"
            ),
        ),
        _flag(
            "cache-creation-spikes",
            "yes" if spikes else "no",
            len(spikes),
            (
                f"{len(spikes)} cache-creation spike(s) at/above max(50k, 5x median={median:,})"
                if creations else "no cache-creation events in session"
            ),
        ),
    ]

    result = {
        "input": total_input,
        "output": total_output,
        "cache_read": total_cache_read,
        "cache_creation": total_cache_creation,
        "total": grand,
        "n_assistant": n_assistant,
        "models": dict(models),
        "n_errors": len(errors),
        "n_recurring_failures": len(recurring),
        "longest_edit_streak_no_verify": global_streak_max,
        "direct_run_verify_count": direct_run_verify_count,
        "flags": flags,
    }

    if out_path:
        report = {
            "path": path,
            "basename": os.path.basename(path),
            "totals": {
                "input": total_input,
                "output": total_output,
                "cache_read": total_cache_read,
                "cache_creation": total_cache_creation,
                "total": grand,
                "n_assistant": n_assistant,
                "models": dict(models),
                "cache_read_share": (total_cache_read / grand) if grand else 0,
                "n_errors": len(errors),
            },
            "flags": flags,
        }
        with open(out_path, "w") as f:
            json.dump(report, f, indent=2)
            f.write("\n")
        print(f"=== CLAUDE CODE token audit: {os.path.basename(path)} ===")
        print(f"report: {out_path}")
        print(f"total={grand:,} turns={n_assistant} errors={len(errors)}")
        for fl in flags:
            print(f"  {fl['name']}: {fl['value']} (count={fl['count']})")
        return result

    print(f"=== CLAUDE CODE token audit: {os.path.basename(path)} ===")
    print(f"assistant turns: {n_assistant}, models used: {dict(models)}")
    print(f"input={total_input:,} output={total_output:,} cache_read={total_cache_read:,} "
          f"cache_creation={total_cache_creation:,} total={grand:,}")
    if grand:
        print(f"cache_read share: {total_cache_read/grand:.1%}")

    print(f"-- model-tier candidates: {simple_turns}/{n_assistant} turns called only "
          f"Read/Grep/Glob ({simple_turn_output_tokens:,} output tokens on those turns) --")
    print("   (lookup-only turns like these are the ones worth checking against a cheaper")
    print("    model or a delegated subagent - this script only flags the shape, a human")
    print("    or the Cost lens still has to judge whether the turn needed full-model reasoning)")
    if tier_backtest:
        print(f"   backtest: those turns' OUTPUT tokens cost ${tier_backtest['actual']:.4f} at "
              f"{tier_backtest['from_model']} rates, ${tier_backtest['cheaper']:.4f} at claude-haiku-4-5 "
              f"rates -> ${tier_backtest['saved']:.4f} saved (output side only; "
              f"input/cache-read tokens for those turns aren't tracked per-turn, so this is a lower bound)")

    print("-- redundant reads (same file, same offset/limit window, no edit in between) --")
    for fp, window, s1, s2 in redundant:
        print(f"  {fp} offset/limit={window} (seq {s1} -> {s2})")
    print(f"redundant re-reads (identical window): {len(redundant)}")

    print(f"-- tool errors: {len(errors)} --")
    for s, name, inp in errors:
        print(f"  seq {s}: {name[len('__ERROR__:'):]} failed")

    if errors:
        print("-- tool errors by tool --")
        for tool, cnt in tool_error_counts.most_common():
            print(f"  {tool}: {cnt}")
        if file_error_counts:
            print("-- tool errors by file --")
            for fp, cnt in file_error_counts.most_common():
                print(f"  {fp}: {cnt}")

    print("-- feedback-loop check: recurring failure signatures (same error shape repeating) --")
    print("   (same-shaped failure recurring suggests the fix attempt didn't address the root")
    print("    cause, or wasn't verified before the next attempt - a slow feedback loop, not")
    print("    necessarily a broken one)")
    for (name, norm), seqs in sorted(recurring.items(), key=lambda x: -len(x[1])):
        print(f"  x{len(seqs)}  {name}: {norm!r} (seq {seqs})")
    print(f"recurring failure signatures: {len(recurring)}")

    print("-- feedback-loop check: edits without a verification run in between --")
    print("   (a Bash call matching test/build/lint/typecheck keywords counts as verification;")
    print("    heuristic only - doesn't confirm the right check ran or that it passed)")
    for fp, n in sorted(flagged_files.items(), key=lambda x: -x[1]):
        print(f"  {fp}: {n} edits in a row with no verification call in between")
    print(f"verification calls found (test/build/lint/typecheck-shaped Bash commands): {verify_count}")
    print(f"verification calls found (direct execution of the just-edited file, e.g. "
          f"`python3 foo.py`): {direct_run_verify_count}")
    print(f"longest edit streak with zero verification in between: {global_streak_max}")

    print("-- cache-creation spikes (fresh write, not cache read - expensive path) --")
    for s, c, r in spikes:
        print(f"  seq~{s}: cache_creation={c:,} cache_read={r:,} (session median creation={median:,})")

    return result


def audit_codex(path):
    lines = read_jsonl(path)
    models = Counter()
    last_usage = None
    turn_ends = []
    for d in lines:
        if d.get("type") == "session_meta":
            pass
        if d.get("type") == "turn_context":
            m = d.get("payload", {}).get("model")
            if m:
                models[m] += 1
        if d.get("type") == "event_msg":
            payload = d.get("payload", {})
            if payload.get("type") == "token_count":
                info = payload.get("info") or {}
                last_usage = info.get("total_token_usage")
                lu = info.get("last_token_usage")
                if lu:
                    turn_ends.append(lu)

    print(f"=== CODEX token audit: {os.path.basename(path)} ===")
    print(f"models used: {dict(models) if models else 'unknown (no turn_context in this file)'}")
    if last_usage:
        print(f"cumulative session usage: {last_usage}")
    if turn_ends:
        cached_share = sum(t.get("cached_input_tokens", 0) for t in turn_ends) / max(1, sum(t.get("input_tokens", 0) for t in turn_ends))
        print(f"per-turn cache hit rate (cached/input averaged over {len(turn_ends)} turns): {cached_share:.1%}")
        biggest = sorted(turn_ends, key=lambda t: -t.get("total_tokens", 0))[:5]
        print("-- most expensive individual turns --")
        for t in biggest:
            print(f"  {t}")
    else:
        print("no token_count events found in this file")

    print("-- per-turn growth (last_total_tokens per turn) --")
    for i, t in enumerate(turn_ends):
        print(f"  turn {i}: {t.get('total_tokens', 0):,}")


_OMP_EDIT_PATH_RE = re.compile(r"\[([^\]#]+)")


def _omp_tool_call_path(name, arguments):
    """OMP's three file-touching tools name the path differently, verified
    against real sessions: read/write take a plain `path` argument; edit
    takes an `input` field in apple-patch format with the path embedded as
    the first bracketed header line (`[/path/to/file.ts#E3AC]`)."""
    if name in ("read", "write"):
        return arguments.get("path")
    if name == "edit":
        m = _OMP_EDIT_PATH_RE.search(arguments.get("input", "") or "")
        return m.group(1) if m else None
    return None


def audit_omp(path):
    lines = read_jsonl(path)
    models = Counter()
    turns = []
    tool_calls = []  # (seq, name, path, call_id)
    call_id_to_name = {}
    seq = 0
    for d in lines:
        if d.get("type") == "model_change":
            m = d.get("model")
            if m:
                models[m] += 1
        if d.get("type") == "message":
            msg = d.get("message", {})
            if msg.get("role") == "assistant" and msg.get("usage"):
                turns.append((msg.get("model"), msg.get("usage")))
            if msg.get("role") == "assistant":
                for b in msg.get("content", []) or []:
                    if isinstance(b, dict) and b.get("type") == "toolCall":
                        seq += 1
                        name = b.get("name")
                        call_id = b.get("id")
                        fp = _omp_tool_call_path(name, b.get("arguments", {}) or {})
                        call_id_to_name[call_id] = name
                        tool_calls.append((seq, name, fp, call_id))

    print(f"=== OMP token audit: {os.path.basename(path)} ===")
    print(f"model_change events: {dict(models) if models else 'none'}")
    print(f"assistant turns with usage: {len(turns)}")
    total_input = sum(u.get("input", 0) for _, u in turns)
    total_output = sum(u.get("output", 0) for _, u in turns)
    total_cache_read = sum(u.get("cacheRead", 0) for _, u in turns)
    total_cache_write = sum(u.get("cacheWrite", 0) for _, u in turns)
    total_cost = sum((u.get("cost") or {}).get("total", 0) for _, u in turns)
    grand = total_input + total_output + total_cache_read + total_cache_write
    print(f"input={total_input:,} output={total_output:,} cacheRead={total_cache_read:,} "
          f"cacheWrite={total_cache_write:,} total={grand:,}")
    print(f"OMP-reported dollar cost for this session: ${total_cost:.4f}")
    turn_models = Counter(m for m, u in turns)
    print(f"per-turn model mix: {dict(turn_models)}")
    biggest = sorted(turns, key=lambda t: -(t[1].get("totalTokens", 0)))[:5]
    print("-- most expensive individual turns --")
    for m, u in biggest:
        print(f"  model={m} totalTokens={u.get('totalTokens'):,} cost=${(u.get('cost') or {}).get('total', 0):.4f}")

    print("-- redundant reads (same file via `read`, no `edit`/`write` in between) --")
    last_read_seq, edited_since, redundant = {}, set(), []
    for s, name, fp, call_id in tool_calls:
        if name in ("edit", "write") and fp:
            edited_since.add(fp)
        elif name == "read" and fp:
            if fp in last_read_seq and fp not in edited_since:
                redundant.append((fp, last_read_seq[fp], s))
            last_read_seq[fp] = s
            edited_since.discard(fp)
    for fp, s1, s2 in redundant:
        print(f"  {fp} (seq {s1} -> {s2})")
    print(f"redundant re-reads: {len(redundant)}")

    print("-- tool errors --")
    n_errors = 0
    for d in lines:
        if d.get("type") != "message":
            continue
        msg = d.get("message", {})
        if msg.get("role") == "toolResult" and msg.get("isError"):
            n_errors += 1
            name = call_id_to_name.get(msg.get("toolCallId"), msg.get("toolName", "?"))
            print(f"  {name} failed")
    print(f"tool errors: {n_errors}")


def audit_cursor(path):
    lines = read_jsonl(path)
    print(f"=== CURSOR thrash audit: {os.path.basename(path)} ===")
    print("NOTE: Cursor's local agent-transcripts carry no token/usage/model fields")
    print("(verified by scanning real transcripts) - no cost numbers are possible from")
    print("this file. Thrash (redundant tool calls) is still detectable:")
    tool_calls = []
    for d in lines:
        msg = d.get("message") if isinstance(d, dict) else None
        if not msg:
            continue
        for block in msg.get("content", []) or []:
            if isinstance(block, dict) and block.get("type") == "tool_use":
                tool_calls.append((block.get("name"), block.get("input")))
    counts = Counter()
    for name, inp in tool_calls:
        h, s = sig(name, inp)
        counts[(name, h)] += 1
    dupes = [(k, v) for k, v in counts.items() if v > 1]
    dupes.sort(key=lambda x: -x[1])
    print(f"distinct tool calls: {len(counts)}, calls with exact repeats: {len(dupes)}")
    for (name, h), cnt in dupes[:10]:
        print(f"  x{cnt}  {name}")


def list_remotes():
    cfg_path = os.path.expanduser("~/.invoker/config.json")
    if not os.path.exists(cfg_path):
        print(f"no invoker config at {cfg_path} - skipping remote scan capability")
        return
    with open(cfg_path) as f:
        cfg = json.load(f)
    targets = list((cfg.get("remoteTargets") or {}).keys())
    print(f"remote targets found in {cfg_path} (names only, no hosts printed):")
    for t in targets:
        print(f"  - {t}")
    print(f"{len(targets)} remote machine(s) could be scanned for ~/.claude, ~/.codex, ~/.cursor")
    print("session data over SSH, using the sshKeyPath/host/user already in that config.")
    print("This script does not do that scan itself - it requires an explicit, confirmed")
    print("SSH step per target, since that touches remote/shared infrastructure.")


def _parse_argv(argv):
    """Parse `mode [path] [--out path]`. Unknown flags exit non-zero."""
    if len(argv) < 2:
        return None, None, None
    mode = argv[1]
    out_path = None
    path = None
    i = 2
    while i < len(argv):
        if argv[i] == "--out":
            if i + 1 >= len(argv):
                print("--out requires a path", file=sys.stderr)
                sys.exit(1)
            out_path = argv[i + 1]
            i += 2
        elif argv[i].startswith("-"):
            print(f"unknown flag: {argv[i]}", file=sys.stderr)
            sys.exit(1)
        else:
            if path is not None:
                print(f"unexpected argument: {argv[i]}", file=sys.stderr)
                sys.exit(1)
            path = argv[i]
            i += 1
    return mode, path, out_path


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__, file=sys.stderr)
        sys.exit(1)
    mode, path, out_path = _parse_argv(sys.argv)
    if mode == "remotes":
        if out_path:
            print("--out is only supported for claude mode", file=sys.stderr)
            sys.exit(1)
        list_remotes()
    elif mode == "claude":
        if not path:
            print("claude mode requires a session path", file=sys.stderr)
            sys.exit(1)
        audit_claude(path, out_path=out_path)
    elif mode in ("codex", "omp", "cursor"):
        if out_path:
            print("--out is only supported for claude mode", file=sys.stderr)
            sys.exit(1)
        if not path:
            print(f"{mode} mode requires a session path", file=sys.stderr)
            sys.exit(1)
        {"codex": audit_codex, "omp": audit_omp, "cursor": audit_cursor}[mode](path)
    else:
        print(f"unknown mode: {mode}", file=sys.stderr)
        sys.exit(1)
