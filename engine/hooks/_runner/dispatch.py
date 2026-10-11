from __future__ import annotations

import argparse
import glob
import importlib.util
import json
import os
import re
import signal
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import outcome
import run

DEFAULT_BUDGET = 59.5
DEFAULT_SUBAGENT_STOP_EVENT_BUDGET = 9.0
DEFAULT_SUBAGENT_STOP_DETECTOR_BUDGET = 4.0
OPT_OUT_KEY = "subagent_stop"
DISPATCH_KEY = "dispatch"
DEFAULT_DISPATCH_ENTRY = "detect:detect"
MIRRORED_EVENTS = {"SubagentStop": "Stop"}
DIRECT_RE = re.compile(r"^python3 \$HOME/\.(claude|cursor|codex)/hooks/([^/\s]+)/([^/\s]+\.py)((?:\s+.*)?)$")
MESSAGE_KEYS = ("reason", "message", "additionalContext", "additional_context", "user_message")
JOINED_TEXT_KEYS = MESSAGE_KEYS + ("agent_message", "permissionDecisionReason", "stopReason", "systemMessage")
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
                dispatch_entry = _dispatch_entry(manifest)
                if dispatch_entry is None:
                    continue
            else:
                dispatch_entry = None
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
                            "dispatch_entry": dispatch_entry,
                        }
                    )
    return records, warnings


def _dispatch_entry(manifest: dict) -> str | None:
    config = manifest.get(OPT_OUT_KEY)
    if not isinstance(config, dict):
        return None
    raw = config.get(DISPATCH_KEY)
    if raw is True:
        return DEFAULT_DISPATCH_ENTRY
    if isinstance(raw, dict):
        entry = raw.get("entry")
        if isinstance(entry, str) and entry.strip():
            return entry.strip()
    return None


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


def _run_one(
    hooks_root: str,
    python: str,
    record: dict,
    stdin: bytes,
    budget: float,
    parsed_event: dict[str, object] | None = None,
) -> dict:
    if record.get("dispatch_entry") and _entrypoint_exists(hooks_root, record["hook"], str(record["dispatch_entry"])):
        return _run_sdk_one(hooks_root, record, stdin, budget, parsed_event)
    return _run_subprocess_one(hooks_root, python, record, stdin, budget, fallback=True)


def _run_subprocess_one(
    hooks_root: str, python: str, record: dict, stdin: bytes, budget: float, fallback: bool = False
) -> dict:
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
    if fallback:
        row["dispatch_path"] = "subprocess_fallback"
    return {
        "hook": hook,
        "script": script,
        "outcome": result_outcome,
        "exit_code": exit_code,
        "stdout": stdout,
        "stderr": stderr + findings_error,
        "row": row,
    }


def _sdk_dirs(hooks_root: str) -> tuple[str, str]:
    engine_hooks = os.path.abspath(hooks_root)
    sdk_dir = os.path.join(engine_hooks, "_sdk")
    return engine_hooks, sdk_dir


def _prefer_import_path(path: str, index: int) -> None:
    try:
        sys.path.remove(path)
    except ValueError:
        pass
    sys.path.insert(index, path)


def _load_entrypoint(hooks_root: str, hook: str, entry: str):
    module_name, sep, function_name = entry.partition(":")
    if not sep or not module_name or not function_name:
        raise ValueError(f"dispatch entry must be MODULE:FUNCTION, got {entry!r}")
    module_path = _entrypoint_path(hooks_root, hook, module_name)
    if not os.path.isfile(module_path):
        raise FileNotFoundError(module_path)
    _engine_hooks, sdk_dir = _sdk_dirs(hooks_root)
    _prefer_import_path(sdk_dir, 0)
    _prefer_import_path(os.path.dirname(module_path), 1)
    unique_name = f"_catstack_dispatch_{hook.replace('-', '_')}_{abs(hash(module_path))}"
    spec = importlib.util.spec_from_file_location(unique_name, module_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"could not load {module_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    target = getattr(module, function_name)
    if not callable(target):
        raise TypeError(f"{entry!r} did not resolve to a callable")
    return target


def _entrypoint_path(hooks_root: str, hook: str, module_name: str) -> str:
    return os.path.join(hooks_root, hook, *module_name.split(".")) + ".py"


def _entrypoint_exists(hooks_root: str, hook: str, entry: str) -> bool:
    module_name, sep, function_name = entry.partition(":")
    return bool(sep and module_name and function_name and os.path.isfile(_entrypoint_path(hooks_root, hook, module_name)))


def _event(stdin: bytes, harness: str, event_name: str) -> dict[str, object]:
    raw = stdin.decode("utf-8", errors="replace")
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        parsed = {
            "_raw_payload": raw,
            "_payload_error": f"the hook payload is not JSON ({exc})",
            "_payload_error_type": type(exc).__name__,
            "_payload_error_detail": str(exc),
        }
    if not isinstance(parsed, dict):
        parsed = {"_raw_payload": raw, "_payload_error": "the hook payload is not a JSON object"}
    parsed.setdefault("_raw_payload", raw)
    parsed.setdefault("_catstack_harness", harness)
    parsed.setdefault("hook_event_name", event_name)
    return parsed


def _render_findings(hooks_root: str, hook: str, harness: str, event_name: str, event: dict[str, object], findings: list):
    _engine_hooks, sdk_dir = _sdk_dirs(hooks_root)
    _prefer_import_path(sdk_dir, 0)
    from modes import effective_finding_modes
    from render import render
    from runtime import _renderable_findings

    mode, _mode_source, finding_modes = effective_finding_modes(hook, event, findings)
    rendered_mode, rendered_findings = _renderable_findings(finding_modes, findings, mode)
    stdout_text, stderr_text, exit_code = render(harness, event_name, rendered_mode, rendered_findings)
    return stdout_text.encode(), stderr_text.encode(), exit_code, [finding.rule_id for finding in findings]


def _run_sdk_one(
    hooks_root: str,
    record: dict,
    stdin: bytes,
    budget: float,
    parsed_event: dict[str, object] | None = None,
) -> dict:
    hook, script = record["hook"], record["script"]
    started = time.monotonic()
    stdout = b""
    stderr = b""
    exit_code = 0
    timed_out = False
    rule_ids: list[str] = []
    harness = run._harness(hooks_root)
    payload = dict(parsed_event) if parsed_event is not None else _event(stdin, harness, "SubagentStop")
    previous_handler = None
    try:
        detect = _load_entrypoint(hooks_root, hook, str(record["dispatch_entry"]))
        if hasattr(signal, "SIGALRM"):
            previous_handler = signal.getsignal(signal.SIGALRM)

            def _timeout(_signum, _frame):
                raise TimeoutError(f"{hook}/{record['dispatch_entry']} timed out after {budget}s")

            signal.signal(signal.SIGALRM, _timeout)
            signal.setitimer(signal.ITIMER_REAL, budget)
        findings = detect(payload)
        if not isinstance(findings, list):
            raise TypeError("detect(event) must return a list")
        stdout, stderr, exit_code, rule_ids = _render_findings(hooks_root, hook, harness, "SubagentStop", payload, findings)
        lines = payload.get("_catstack_stderr_lines")
        if isinstance(lines, list):
            stderr += "".join(f"{line}\n" for line in lines if isinstance(line, str) and line).encode()
    except TimeoutError:
        timed_out = True
        exit_code = 1
        stdout = b""
        stderr = f"catstack-hook-runner: {hook}/{script} timed out after {budget}s\n".encode()
    except BaseException as exc:
        if isinstance(exc, KeyboardInterrupt):
            raise
        if isinstance(exc, SystemExit):
            exit_code = exc.code if isinstance(exc.code, int) else 1
        else:
            exit_code = 0
        stdout = b""
        stderr = f"catstack-hook-error {hook}: {type(exc).__name__}: {exc}\n".encode()
    finally:
        if hasattr(signal, "SIGALRM"):
            signal.setitimer(signal.ITIMER_REAL, 0)
            if previous_handler is not None:
                signal.signal(signal.SIGALRM, previous_handler)
    result_outcome = outcome.classify(exit_code, stdout, stderr, timed_out)
    row = run._row(hooks_root, hook, script, stdin, result_outcome, exit_code, started, stdout, stderr, rule_ids)
    row["dispatch_path"] = "sdk" if not timed_out and not stderr.startswith(b"catstack-hook-error ") else "sdk_error"
    return {
        "hook": hook,
        "script": script,
        "outcome": result_outcome,
        "exit_code": exit_code,
        "stdout": stdout,
        "stderr": stderr,
        "row": row,
    }


def _merge_stdout(results: list[dict]) -> tuple[bytes, bytes, int]:
    blocked = [r for r in results if r["outcome"] == "blocked"]
    spoke = [r for r in results if r["stdout"].strip()]
    if blocked:
        return _merge_blocks(blocked)
    if spoke:
        if len(spoke) == 1:
            return spoke[0]["stdout"], b"", spoke[0]["exit_code"]
        contexts = [note for r in spoke for note in (_note(r),) if note]
        payload: dict[str, object] = {"continue": True}
        if contexts:
            payload["additionalContext"] = "\n".join(contexts)
        return json.dumps(payload).encode(), b"", 0
    return b"", b"", 0


def _merge_blocks(blocked: list[dict]) -> tuple[bytes, bytes, int]:
    if any(r["exit_code"] == 2 for r in blocked):
        notes = [note for r in blocked if r["exit_code"] != 2 for note in (_note(r),) if note]
        return b"", "".join(f"{note}\n" for note in notes).encode(), 2
    if len(blocked) == 1:
        return blocked[0]["stdout"], b"", 0
    objects = [outcome._stdout_json_object(r["stdout"]) for r in blocked]
    return json.dumps(_merge_objects([o for o in objects if o is not None])).encode(), b"", 0


def _merge_objects(objects: list[dict]) -> dict:
    merged: dict[str, object] = {}
    for obj in objects:
        for key, value in obj.items():
            current = merged.get(key)
            if key not in merged:
                merged[key] = value
            elif isinstance(current, dict) and isinstance(value, dict):
                merged[key] = _merge_objects([current, value])
            elif key in JOINED_TEXT_KEYS and isinstance(current, str) and isinstance(value, str) and value:
                merged[key] = f"{current}\n{value}" if current else value
    return merged


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

    detector_budget = min(budget, DEFAULT_SUBAGENT_STOP_DETECTOR_BUDGET) if event == "SubagentStop" else budget
    parsed_event = _event(stdin, harness, event) if event == "SubagentStop" else None
    results = [_run_one(hooks_root, python, record, stdin, detector_budget, parsed_event) for record in records]

    stdout, block_notes, exit_code = _merge_stdout(results)
    stderr_lines = [r["stderr"] for r in results if r["stderr"]]
    stderr = warning_bytes + b"".join(stderr_lines) + block_notes
    return exit_code, stdout, stderr, [r["row"] for r in results]


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--event", required=True)
    parser.add_argument("--timeout", type=float)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    stdin = sys.stdin.buffer.read()
    hooks_root = run._hooks_root()
    harness = run._harness(hooks_root)
    budget = args.timeout
    if budget is None:
        budget = DEFAULT_SUBAGENT_STOP_EVENT_BUDGET if args.event == "SubagentStop" else DEFAULT_BUDGET
    exit_code, stdout, stderr, rows = run_dispatch(hooks_root, harness, args.event, stdin, budget)
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
