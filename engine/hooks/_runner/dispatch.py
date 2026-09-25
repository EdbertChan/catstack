from __future__ import annotations

import argparse
import concurrent.futures
import glob
import json
import os
import re
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import outcome
import run

DEFAULT_BUDGET = 59.5
OPT_OUT_KEY = "subagent_stop"
MIRRORED_EVENTS = {"SubagentStop": "Stop"}
DIRECT_RE = re.compile(r"^python3 \$HOME/\.(claude|cursor|codex)/hooks/([^/\s]+)/([^/\s]+\.py)((?:\s+.*)?)$")
MESSAGE_KEYS = ("reason", "message", "additionalContext", "additional_context", "user_message")


def load_event_hooks(hooks_root: str, harness: str, event: str) -> tuple[list[dict], list[str]]:
    """Every hook registered for `event`, read live from every one of the
    hook's own `<harness>*.hook.json` manifests under `hooks_root`.

    A hook splits its registrations across sibling manifests -- `claude.hook.json`
    beside `claude.prompt.hook.json`, `claude.tool.hook.json` and
    `claude.agent.hook.json` -- and some hooks have no plain
    `<harness>.hook.json` at all. Reading only that one name is what
    scripts/install/mirror_stop_hooks_to_subagent_stop.py and
    scripts/ci/check_install_effective.py already refuse to do, and it would
    drop those hooks out of the event entirely once install collapses their
    settings entries into this dispatcher.

    For a mirrored event (SubagentStop mirrors Stop, the same way
    scripts/install/mirror_stop_hooks_to_subagent_stop.py mirrors it into
    settings.json at install time) a hook opts out with the same
    `subagent_stop: {inherit: false, reason: ...}` manifest key, and the
    matcher is dropped -- SubagentStop has no per-tool matcher.

    Second return value: one warning line per manifest that exists but could
    not be read -- a hook silently missing from an event because its
    manifest was corrupt is a check that could not run, not a clean miss."""
    source_event = MIRRORED_EVENTS.get(event, event)
    mirrored = source_event != event
    records: list[dict] = []
    warnings: list[str] = []
    seen: set[tuple[str, str, str, object]] = set()
    for hook_dir in sorted(glob.glob(os.path.join(hooks_root, "*"))):
        name = os.path.basename(hook_dir)
        if name.startswith("_") or not os.path.isdir(hook_dir):
            continue
        for fragment_path in sorted(glob.glob(os.path.join(hook_dir, f"{harness}*.hook.json"))):
            try:
                with open(fragment_path, encoding="utf-8") as handle:
                    manifest = json.load(handle)
            except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
                warnings.append(f"catstack-hook-dispatcher: could not read {fragment_path}: {exc}\n")
                continue
            entries = manifest.get("hooks", {}).get(source_event) if isinstance(manifest, dict) else None
            if not entries:
                continue
            if mirrored:
                opt_out = manifest.get(OPT_OUT_KEY)
                if isinstance(opt_out, dict) and opt_out.get("inherit") is False:
                    continue
            _collect_entries(entries, name, harness, mirrored, records, seen)
    return records, warnings


def _collect_entries(
    entries: list,
    name: str,
    harness: str,
    mirrored: bool,
    records: list[dict],
    seen: set[tuple[str, str, str, object]],
) -> None:
    for entry in entries:
        if not isinstance(entry, dict) or not isinstance(entry.get("hooks"), list):
            continue
        matcher = None if mirrored else entry.get("matcher")
        for hook in entry["hooks"]:
            if not isinstance(hook, dict) or not isinstance(hook.get("command"), str):
                continue
            identity = _parse_command(hook["command"], harness)
            if identity is None or identity[0] != name:
                continue
            _, script, trailing = identity
            key = (name, script, trailing, matcher)
            if key in seen:
                continue
            seen.add(key)
            records.append(
                {
                    "hook": name,
                    "script": script,
                    "args": trailing.split() if trailing else [],
                    "timeout": hook.get("timeout"),
                    "matcher": matcher,
                }
            )


def _parse_command(command: str, harness: str) -> tuple[str, str, str] | None:
    match = DIRECT_RE.fullmatch(command)
    if not match or match.group(1) != harness:
        return None
    _, hook, script, trailing = match.groups()
    return hook, script, trailing.strip()


def _matcher_applies(matcher: object, payload: dict[str, object]) -> bool:
    if matcher in (None, "", "*"):
        return True
    tool_name = payload.get("tool_name")
    if not isinstance(tool_name, str):
        return False
    try:
        return re.fullmatch(str(matcher), tool_name) is not None
    except re.error:
        return False


def _payload(stdin: bytes) -> dict[str, object]:
    try:
        parsed = json.loads(stdin.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _hook_budget(record: dict, budget: float) -> float:
    """The budget this one hook gets, never more than the whole event's.

    The manifest timeout is the harness-facing number; the per-hook runner
    layout hands `run.py` that minus half a second, so one slow hook cannot
    eat the outer timeout. `record["timeout"]` carried that number and
    nothing spent it, which let a hook registered for 5s run for the event's
    whole budget and land a row saying it finished instead of timed out."""
    value = record.get("timeout")
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return budget
    own = float(value) - 0.5
    if own <= 0:
        return budget
    return min(own, budget)


def _run_one(hooks_root: str, python: str, record: dict, stdin: bytes, budget: float) -> dict:
    hook, script = record["hook"], record["script"]
    budget = _hook_budget(record, budget)
    started = time.monotonic()
    script_path = os.path.join(hooks_root, hook, script)
    findings_path = run._make_findings_file()
    stdout = b""
    stderr = b""
    exit_code = 1
    timed_out = False
    hook_ran = False
    try:
        if not os.path.isfile(script_path):
            stderr = f"catstack-hook-runner: no such hook script: {script_path}\n".encode()
        else:
            env = os.environ.copy()
            env["CATSTACK_HOOK_FINDINGS_FILE"] = findings_path
            proc = subprocess.Popen(
                [python, script_path, *record["args"]],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=os.getcwd(),
                env=env,
            )
            hook_ran = True
            try:
                stdout, stderr = proc.communicate(stdin, timeout=budget)
                exit_code = proc.returncode
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.communicate()
                timed_out = True
                stdout = b""
                stderr = (
                    f"catstack-hook-runner: {hook}/{script} timed out after "
                    f"{run._format_timeout(budget)}s\n"
                ).encode()
                exit_code = 1
        rule_ids, findings_error = run._read_rule_ids(findings_path)
    finally:
        run._delete_findings_file(findings_path)
    result_outcome = outcome.classify(exit_code, stdout, stderr, timed_out)
    row = run._row(hooks_root, hook, script, stdin, result_outcome, exit_code, started, stdout, stderr, rule_ids)
    if hook_ran and result_outcome == "crashed" and hook != "hook-health":
        stdout, stderr = b"", b""
    return {
        "hook": hook,
        "script": script,
        "outcome": result_outcome,
        "stdout": stdout,
        "stderr": stderr + findings_error,
        "row": row,
    }


def _merge_stdout(results: list[dict]) -> tuple[bytes, int]:
    blocked = [r for r in results if r["outcome"] == "blocked"]
    spoke = [r for r in results if r["stdout"].strip()]
    if blocked:
        reasons = [note for r in blocked for note in (_note(r),) if note]
        payload: dict[str, object] = {"decision": "block", "continue": False}
        if reasons:
            payload["reason"] = "\n".join(reasons)
        return json.dumps(payload).encode(), 2
    if spoke:
        contexts = [note for r in spoke for note in (_note(r),) if note]
        payload = {"continue": True}
        if contexts:
            payload["additionalContext"] = "\n".join(contexts)
        return json.dumps(payload).encode(), 0
    return b"", 0


def _note(result: dict) -> str:
    parsed = outcome._stdout_json_object(result["stdout"])
    text = None
    if parsed is not None:
        for key in MESSAGE_KEYS:
            value = parsed.get(key)
            if isinstance(value, str) and value:
                text = value
                break
        if text is None:
            hook_output = parsed.get("hookSpecificOutput")
            if isinstance(hook_output, dict):
                for key in ("permissionDecisionReason", "additionalContext"):
                    value = hook_output.get(key)
                    if isinstance(value, str) and value:
                        text = value
                        break
    if text is None:
        text = result["stdout"].decode("utf-8", errors="replace").strip()
    if not text:
        return ""
    return f"[{result['hook']}] {text}"


def _skipped_rows(hooks_root: str, records: list[dict], stdin: bytes, reason: str, started: float) -> list[dict]:
    rows = []
    for record in records:
        row = run._row(
            hooks_root,
            record["hook"],
            record["script"],
            stdin,
            outcome.classify(0, b"", b"", False),
            0,
            started,
            b"",
            b"",
            [],
        )
        row["skipped"] = reason
        rows.append(row)
    return rows


def run_dispatch(
    hooks_root: str, harness: str, event: str, stdin: bytes, budget: float
) -> tuple[int, bytes, bytes, list[dict]]:
    started = time.monotonic()
    payload = _payload(stdin)
    all_records, warnings = load_event_hooks(hooks_root, harness, event)
    records = [record for record in all_records if _matcher_applies(record["matcher"], payload)]
    warning_bytes = "".join(warnings).encode()
    if not records:
        return 0, b"", warning_bytes, []

    skipped = run._skip_reason(stdin)
    if skipped is not None:
        return 0, b"", warning_bytes, _skipped_rows(hooks_root, records, stdin, skipped, started)

    python = run._pick_python(sys.version_info, sys.executable, run._python_dirs(dict(os.environ)), dict(os.environ))
    if python is None:
        stderr = warning_bytes + (
            f"catstack-hook-dispatcher: no Python {run.MIN_PYTHON[0]}.{run.MIN_PYTHON[1]}+ interpreter found "
            f"for event {event}\n"
        ).encode()
        return 1, b"", stderr, []

    results: list[dict] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(records)) as pool:
        futures = [pool.submit(_run_one, hooks_root, python, record, stdin, budget) for record in records]
        for future in futures:
            results.append(future.result())

    stdout, exit_code = _merge_stdout(results)
    stderr_lines = [r["stderr"] for r in results if r["stderr"]]
    stderr = warning_bytes + b"".join(stderr_lines)
    return exit_code, stdout, stderr, [r["row"] for r in results]


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--event", required=True)
    parser.add_argument("--timeout", type=float, default=DEFAULT_BUDGET)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    stdin = sys.stdin.buffer.read()
    hooks_root = run._hooks_root()
    harness = run._harness(hooks_root)
    exit_code, stdout, stderr, rows = run_dispatch(hooks_root, harness, args.event, stdin, args.timeout)
    metrics_path = run._metrics_path()
    metrics_errors = b"".join(run._write_metrics(row, metrics_path) for row in rows)
    sys.stdout.buffer.write(stdout)
    sys.stdout.buffer.flush()
    sys.stderr.buffer.write(stderr)
    sys.stderr.buffer.write(metrics_errors)
    sys.stderr.buffer.flush()
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
