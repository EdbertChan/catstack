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
CRASH_VISIBLE_HOOK = "hook-health"
DIRECT_RE = re.compile(r"^python3 \$HOME/\.(claude|cursor|codex)/hooks/([^/\s]+)/([^/\s]+\.py)((?:\s+.*)?)$")
MESSAGE_KEYS = ("reason", "message", "additionalContext", "additional_context", "user_message")
UPDATED_INPUT_KEY = "updatedInput"


def load_event_hooks(hooks_root: str, harness: str, event: str) -> tuple[list[dict], list[str]]:
    """Every hook registered for `event`, read live from each hook's own
    `<harness>.hook.json` manifest under `hooks_root`.

    For a mirrored event (SubagentStop mirrors Stop, the same way
    scripts/install/mirror_stop_hooks_to_subagent_stop.py mirrors it into
    settings.json at install time) a hook opts out with the same
    `subagent_stop: {inherit: false, reason: ...}` manifest key, and the
    matcher is dropped -- SubagentStop has no per-tool matcher.

    Second return value: one warning line per manifest that exists but could
    not be read -- a hook silently missing from an event because its
    manifest was corrupt is a check that could not run, not a clean miss.

    A hook wires one harness across several sibling fragments --
    `claude.hook.json` plus `claude.prompt.hook.json`,
    `claude.tool.hook.json`, `claude.agent.hook.json` -- so every
    `<harness>*.hook.json` in the hook's directory is read, the same glob
    scripts/install/mirror_stop_hooks_to_subagent_stop.py and
    scripts/ci/check_install_effective.py already use. Reading only
    `<harness>.hook.json` left 16 installed Claude hook scripts (9
    UserPromptSubmit, 4 PreToolUse, 3 PostToolUse) with a settings entry that
    install collapsed into the dispatcher and no dispatcher record to run
    them from."""
    source_event = MIRRORED_EVENTS.get(event, event)
    mirrored = source_event != event
    records: list[dict] = []
    warnings: list[str] = []
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
                    records.append(
                        {
                            "hook": name,
                            "script": script,
                            "args": trailing.split() if trailing else [],
                            "timeout": hook.get("timeout"),
                            "matcher": matcher,
                        }
                    )
    return records, warnings


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


def _run_one(hooks_root: str, python: str, record: dict, stdin: bytes, budget: float) -> dict:
    hook, script = record["hook"], record["script"]
    started = time.monotonic()
    script_path = os.path.join(hooks_root, hook, script)
    findings_path = run._make_findings_file()
    stdout = b""
    stderr = b""
    exit_code = 1
    timed_out = False
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
            try:
                stdout, stderr = proc.communicate(stdin, timeout=budget)
                exit_code = proc.returncode
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.communicate()
                timed_out = True
                stdout = b""
                stderr = f"catstack-hook-runner: {hook}/{script} timed out after {budget}s\n".encode()
                exit_code = 1
        rule_ids, findings_error = run._read_rule_ids(findings_path)
    finally:
        run._delete_findings_file(findings_path)
    result_outcome = outcome.classify(exit_code, stdout, stderr, timed_out)
    row = run._row(hooks_root, hook, script, stdin, result_outcome, exit_code, started, stdout, stderr, rule_ids)
    merged_stdout = stdout
    merged_stderr = stderr + findings_error
    if result_outcome == "crashed" and hook != CRASH_VISIBLE_HOOK:
        merged_stdout = b""
        merged_stderr = findings_error
    return {
        "hook": hook,
        "script": script,
        "outcome": result_outcome,
        "stdout": merged_stdout,
        "stderr": merged_stderr,
        "row": row,
    }


def _unrun_row(
    hooks_root: str, record: dict, stdin: bytes, result_outcome: str, exit_code: int, stderr: bytes
) -> dict:
    """The row `run.py` writes for a hook it never launched.

    `run.py` records a row on every path, launched or not, so hook-health can
    tell a quiet hook from one that never ran. A dispatcher that returned no
    rows at all would read as the whole event having no hook activity."""
    started = time.monotonic()
    return run._row(
        hooks_root, record["hook"], record["script"], stdin, result_outcome, exit_code, started, b"", stderr, []
    )


def _skipped_row(hooks_root: str, record: dict, stdin: bytes, reason: str) -> dict:
    """`run.py` classifies a hook it skipped as `silent` with exit code 0 and
    stamps `skipped` on the row."""
    row = _unrun_row(hooks_root, record, stdin, "silent", 0, b"")
    row["skipped"] = reason
    return row


def _updated_input_present(stdout: bytes) -> bool:
    parsed = outcome._stdout_json_object(stdout)
    if parsed is None:
        return False
    if parsed.get(UPDATED_INPUT_KEY) is not None:
        return True
    hook_output = parsed.get("hookSpecificOutput")
    return isinstance(hook_output, dict) and hook_output.get(UPDATED_INPUT_KEY) is not None


def _merge_stdout(results: list[dict]) -> tuple[bytes, int, bytes]:
    """One harness reply for the whole event. Any block wins.

    One speaking hook and no block is today's layout exactly -- one harness
    entry, one reply -- so that reply is handed back byte for byte instead of
    being rebuilt. Rebuilding it drops every field the merge has no slot for,
    `updatedInput` above all: a PreToolUse hook that rewrites the tool's input
    had its rewrite replaced by a copy of its own JSON pasted into
    `additionalContext`.

    A blocking hook does not swallow what its siblings said: under today's
    layout the harness reads every entry's stdout, so a speaking sibling's
    message is appended to the block reason instead of being dropped.

    Third return value: stderr lines for replies the merge could not carry.
    Two hooks both rewriting one tool call cannot be expressed as one reply,
    and dropping the second silently would be a contract change nobody sees."""
    blocked = [r for r in results if r["outcome"] == "blocked"]
    spoke = [r for r in results if r["outcome"] != "blocked" and r["stdout"].strip()]
    if not blocked and len(spoke) == 1:
        return spoke[0]["stdout"], 0, b""
    uncarried = b"".join(
        (
            f"catstack-hook-dispatcher: {r['hook']}/{r['script']} returned {UPDATED_INPUT_KEY}, "
            f"which one merged reply for {len(spoke)} speaking hooks cannot carry\n"
        ).encode()
        for r in spoke
        if _updated_input_present(r["stdout"])
    )
    notes = [note for r in blocked + spoke for note in (_note(r),) if note]
    if blocked:
        payload: dict[str, object] = {"decision": "block", "continue": False}
        if notes:
            payload["reason"] = "\n".join(notes)
        return json.dumps(payload).encode(), 2, uncarried
    if spoke:
        payload = {"continue": True}
        if notes:
            payload["additionalContext"] = "\n".join(notes)
        return json.dumps(payload).encode(), 0, uncarried
    return b"", 0, uncarried


def _note(result: dict) -> str:
    """The one line this hook contributes to a merged reply, or "".

    A JSON reply carrying no message field says nothing to the user -- an
    allow-only `{"continue": true}` is the common case -- and echoing its raw
    JSON back as context, which is what the raw-stdout fallback did, injects
    machine noise into every event. The fallback is for a hook that printed
    prose, not for one that printed a verdict with no message in it."""
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
    if text is None and parsed is not None:
        return ""
    if text is None:
        text = result["stdout"].decode("utf-8", errors="replace").strip()
    if not text:
        return ""
    return f"[{result['hook']}] {text}"


def run_dispatch(
    hooks_root: str, harness: str, event: str, stdin: bytes, budget: float
) -> tuple[int, bytes, bytes, list[dict]]:
    payload = _payload(stdin)
    all_records, warnings = load_event_hooks(hooks_root, harness, event)
    records = [record for record in all_records if _matcher_applies(record["matcher"], payload)]
    warning_bytes = "".join(warnings).encode()
    if not records:
        return 0, b"", warning_bytes, []

    skipped = run._skip_reason(stdin)
    if skipped is not None:
        return 0, b"", warning_bytes, [_skipped_row(hooks_root, record, stdin, skipped) for record in records]

    python = run._pick_python(sys.version_info, sys.executable, run._python_dirs(dict(os.environ)), dict(os.environ))
    if python is None:
        message = (
            f"catstack-hook-dispatcher: no Python {run.MIN_PYTHON[0]}.{run.MIN_PYTHON[1]}+ interpreter found "
            f"for event {event}\n"
        ).encode()
        rows = [_unrun_row(hooks_root, record, stdin, "crashed", 1, message) for record in records]
        return 1, b"", warning_bytes + message, rows

    results: list[dict] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(records)) as pool:
        futures = [pool.submit(_run_one, hooks_root, python, record, stdin, budget) for record in records]
        for future in futures:
            results.append(future.result())

    stdout, exit_code, uncarried = _merge_stdout(results)
    stderr_lines = [r["stderr"] for r in results if r["stderr"]]
    stderr = warning_bytes + b"".join(stderr_lines) + uncarried
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
