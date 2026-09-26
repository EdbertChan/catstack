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
MANIFEST_SUFFIX = ".hook.json"
INSTALLED_REGISTRY = "_dispatch.json"
REGISTRY_HARNESSES = ("cursor",)


def manifest_paths(hook_dir: str, harness: str) -> list[str]:
    """Every manifest file in `hook_dir` that install reads for `harness`.

    A hook's `install_<harness>_hook.py` registers from `<harness>.hook.json`
    and from any `<harness><part>.hook.json` sibling it names -- today
    `claude.prompt.hook.json`, `claude.tool.hook.json` and
    `claude.agent.hook.json`. That is the same `<harness>*.hook.json` set
    scripts/install/mirror_stop_hooks_to_subagent_stop.py and
    scripts/ci/check_install_effective.py walk, so reading the glob rather
    than one fixed name is what keeps the dispatcher and install from
    drifting apart when a hook adds a manifest."""
    pattern = os.path.join(hook_dir, f"{harness}*{MANIFEST_SUFFIX}")
    return [path for path in sorted(glob.glob(pattern)) if os.path.isfile(path)]


def _entry_hooks(entry: object) -> list[dict]:
    """The command objects inside one manifest entry.

    Claude and Codex nest them under `hooks`; Cursor's config puts the
    command on the entry itself, and `wrap_installed._dispatcher_group`
    writes that flat shape back for Cursor, so both are read here."""
    if not isinstance(entry, dict):
        return []
    nested = entry.get("hooks")
    if isinstance(nested, list):
        return [hook for hook in nested if isinstance(hook, dict) and isinstance(hook.get("command"), str)]
    if isinstance(entry.get("command"), str):
        return [entry]
    return []


def load_event_hooks(hooks_root: str, harness: str, event: str) -> tuple[list[dict], list[str]]:
    """Every hook registered for `event`, read live from every manifest
    `manifest_paths` finds for `harness` under `hooks_root` -- or, for a
    harness in `REGISTRY_HARNESSES` whose install left a registry, read from
    that registry instead (`load_installed_registry`).

    For a mirrored event (SubagentStop mirrors Stop, the same way
    scripts/install/mirror_stop_hooks_to_subagent_stop.py mirrors it into
    settings.json at install time) a hook opts out with the same
    `subagent_stop: {inherit: false, reason: ...}` manifest key, and the
    matcher is dropped -- SubagentStop has no per-tool matcher. The opt-out
    is read per manifest, which is how the mirror script reads it too.

    A script registered by two of a hook's manifests for the same event and
    matcher is kept once, so splitting a hook's manifest never doubles what
    the hook did when install registered it alone.

    Second return value: one warning line per manifest that exists but could
    not be read -- a hook silently missing from an event because its
    manifest was corrupt is a check that could not run, not a clean miss."""
    if harness in REGISTRY_HARNESSES:
        registered = load_installed_registry(hooks_root)
        if isinstance(registered, dict):
            return [
                {**record, "matcher": record.get("matcher"), "timeout": record.get("timeout")}
                for record in registered.get(event, [])
            ], []
        if isinstance(registered, str):
            return _load_manifest_hooks(hooks_root, harness, event, [registered])
    return _load_manifest_hooks(hooks_root, harness, event, [])


def registry_path(hooks_root: str) -> str:
    return os.path.join(hooks_root, INSTALLED_REGISTRY)


def valid_record(record: object) -> bool:
    if not isinstance(record, dict):
        return False
    args = record.get("args")
    return (
        isinstance(record.get("hook"), str)
        and isinstance(record.get("script"), str)
        and isinstance(args, list)
        and all(isinstance(arg, str) for arg in args)
    )


def load_installed_registry(hooks_root: str) -> dict[str, list[dict]] | str | None:
    """What install registered per event for a harness whose hooks are not
    all declared in manifest files, as `wrap_installed.py` recorded it when
    it collapsed them into one dispatcher entry.

    Cursor is that harness: most of its hooks are registered by an
    `install_cursor_hook.py` that merges a flat entry built in code straight
    into ~/.cursor/hooks.json, and diu-stop's is seeded from
    `cursor.hooks.json`, so no manifest name covers them.

    None when there is no registry, a warning line when it exists but could
    not be read, else the records by event."""
    path = registry_path(hooks_root)
    if not os.path.isfile(path):
        return None
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return f"catstack-hook-dispatcher: could not read {path}: {exc}\n"
    if not isinstance(data, dict) or not all(
        isinstance(records, list) and all(valid_record(record) for record in records) for records in data.values()
    ):
        return f"catstack-hook-dispatcher: could not read {path}: not an event-to-records map\n"
    return data


def _load_manifest_hooks(
    hooks_root: str, harness: str, event: str, warnings: list[str]
) -> tuple[list[dict], list[str]]:
    source_event = MIRRORED_EVENTS.get(event, event)
    mirrored = source_event != event
    records: list[dict] = []
    for hook_dir in sorted(glob.glob(os.path.join(hooks_root, "*"))):
        name = os.path.basename(hook_dir)
        if name.startswith("_") or not os.path.isdir(hook_dir):
            continue
        seen: set[tuple[str, tuple[str, ...], str]] = set()
        for fragment_path in manifest_paths(hook_dir, harness):
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
                matcher = None
                if not mirrored and isinstance(entry, dict):
                    matcher = entry.get("matcher")
                for hook in _entry_hooks(entry):
                    identity = _parse_command(hook["command"], harness)
                    if identity is None or identity[0] != name:
                        continue
                    _, script, trailing = identity
                    args = tuple(trailing.split()) if trailing else ()
                    key = (script, args, repr(matcher))
                    if key in seen:
                        continue
                    seen.add(key)
                    records.append(
                        {
                            "hook": name,
                            "script": script,
                            "args": list(args),
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


def run_dispatch(
    hooks_root: str, harness: str, event: str, stdin: bytes, budget: float
) -> tuple[int, bytes, bytes, list[dict]]:
    payload = _payload(stdin)
    all_records, warnings = load_event_hooks(hooks_root, harness, event)
    records = [record for record in all_records if _matcher_applies(record["matcher"], payload)]
    warning_bytes = "".join(warnings).encode()
    if not records:
        return 0, b"", warning_bytes, []

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
