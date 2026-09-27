from __future__ import annotations

import argparse
import builtins
import copy
import concurrent.futures
import contextlib
import glob
import importlib.util
import io
import json
import os
import re
import signal
import subprocess
import sys
import time
from collections.abc import Iterator

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import outcome
import run

DEFAULT_BUDGET = 59.5
DEFAULT_DETECTOR_BUDGET = 4.0
OPT_OUT_KEY = "subagent_stop"
DISPATCH_KEY = "dispatch"
MIRRORED_EVENTS = {"SubagentStop": "Stop"}
DIRECT_RE = re.compile(r"^python3 \$HOME/\.(claude|cursor|codex)/hooks/([^/\s]+)/([^/\s]+\.py)((?:\s+.*)?)$")
MESSAGE_KEYS = ("reason", "message", "additionalContext", "additional_context", "user_message")
JOINED_TEXT_KEYS = MESSAGE_KEYS + ("agent_message", "permissionDecisionReason", "stopReason", "systemMessage")
MANIFEST_SUFFIX = ".hook.json"
INSTALLED_REGISTRY = "_dispatch.json"
REGISTRY_HARNESSES = ("cursor",)


class DetectorTimedOut(BaseException):
    pass


class EntrypointUnavailable(Exception):
    pass


class CachedJsonLine(str):
    def __new__(cls, value: str, parsed: object):
        instance = super().__new__(cls, value)
        instance.parsed = parsed
        return instance

    def strip(self, chars: str | None = None) -> "CachedJsonLine":
        return CachedJsonLine(super().strip(chars), self.parsed)

    def lstrip(self, chars: str | None = None) -> "CachedJsonLine":
        return CachedJsonLine(super().lstrip(chars), self.parsed)

    def rstrip(self, chars: str | None = None) -> "CachedJsonLine":
        return CachedJsonLine(super().rstrip(chars), self.parsed)


class CachedTranscriptHandle:
    def __init__(self, lines: tuple[CachedJsonLine, ...]):
        self._lines = lines
        self._index = 0
        self.closed = False

    def __enter__(self) -> "CachedTranscriptHandle":
        return self

    def __exit__(self, _type: object, _value: object, _traceback: object) -> None:
        self.close()

    def __iter__(self) -> "CachedTranscriptHandle":
        return self

    def __next__(self) -> CachedJsonLine:
        line = self.readline()
        if line == "":
            raise StopIteration
        return line

    def readline(self, _size: int = -1) -> CachedJsonLine | str:
        if self._index >= len(self._lines):
            return ""
        line = self._lines[self._index]
        self._index += 1
        return line

    def readlines(self, _hint: int = -1) -> list[CachedJsonLine]:
        lines = list(self._lines[self._index :])
        self._index = len(self._lines)
        return lines

    def read(self, _size: int = -1) -> str:
        lines = self.readlines()
        return "".join(lines)

    def close(self) -> None:
        self.closed = True


class TranscriptCache:
    def __init__(self) -> None:
        self._rows: dict[str, tuple[object, ...]] = {}
        self._lines: dict[str, tuple[CachedJsonLine, ...]] = {}
        self._errors: dict[str, str] = {}

    def read(self, path: str) -> tuple[object, ...]:
        if path in self._rows:
            return self._rows[path]
        rows = []
        lines = []
        try:
            with open(path, encoding="utf-8", errors="replace") as handle:
                for line in handle:
                    stripped = line.strip()
                    if not stripped:
                        lines.append(CachedJsonLine(line, None))
                        continue
                    try:
                        parsed = json.loads(stripped)
                    except json.JSONDecodeError:
                        lines.append(CachedJsonLine(line, None))
                        continue
                    rows.append(parsed)
                    lines.append(CachedJsonLine(line, parsed))
        except OSError as exc:
            self._errors[path] = f"{type(exc).__name__}: {exc}"
        self._rows[path] = tuple(rows)
        self._lines[path] = tuple(lines)
        return self._rows[path]

    def error(self, path: str) -> str | None:
        self.read(path)
        return self._errors.get(path)

    def contains(self, path: object) -> bool:
        return isinstance(path, (str, os.PathLike)) and os.fspath(path) in self._lines

    def handle(self, path: object) -> CachedTranscriptHandle:
        return CachedTranscriptHandle(self._lines[os.fspath(path)])


@contextlib.contextmanager
def _cached_transcript_reads(cache: TranscriptCache) -> Iterator[None]:
    original_builtin_open = builtins.open
    original_io_open = io.open
    original_loads = json.loads

    def cached_open(file: object, mode: str = "r", *args: object, **kwargs: object) -> object:
        if "r" in mode and "b" not in mode and cache.contains(file):
            return cache.handle(file)
        return original_builtin_open(file, mode, *args, **kwargs)

    def cached_io_open(file: object, mode: str = "r", *args: object, **kwargs: object) -> object:
        if "r" in mode and "b" not in mode and cache.contains(file):
            return cache.handle(file)
        return original_io_open(file, mode, *args, **kwargs)

    def cached_loads(value: object, *args: object, **kwargs: object) -> object:
        if isinstance(value, CachedJsonLine) and value.parsed is not None:
            return copy.deepcopy(value.parsed)
        return original_loads(value, *args, **kwargs)

    builtins.open = cached_open
    io.open = cached_io_open
    json.loads = cached_loads
    try:
        yield
    finally:
        json.loads = original_loads
        io.open = original_io_open
        builtins.open = original_builtin_open


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
                dispatch = manifest.get(DISPATCH_KEY)
                dispatch_event = dispatch.get(event) if isinstance(dispatch, dict) else None
                if dispatch_event is not True and not isinstance(dispatch_event, str):
                    continue
            else:
                dispatch_event = None
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
                            "entrypoint": (
                                dispatch_event
                                if isinstance(dispatch_event, str)
                                else "detect.py:detect"
                                if mirrored and os.path.isfile(os.path.join(hook_dir, "detect.py"))
                                else None
                            ),
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


def _event_with_transcripts(payload: dict[str, object], cache: TranscriptCache) -> dict[str, object]:
    event = dict(payload)
    transcripts = {}
    for key in ("agent_transcript_path", "transcript_path", "transcriptPath"):
        path = event.get(key)
        if isinstance(path, str) and path and path not in transcripts:
            transcripts[path] = cache.read(path)
    event["_catstack_transcript_cache"] = cache
    event["_catstack_transcripts"] = transcripts
    return event


def _alarm_handler(_signum: int, _frame: object) -> None:
    raise DetectorTimedOut()


@contextlib.contextmanager
def _alarm(seconds: float) -> Iterator[None]:
    previous_handler = signal.getsignal(signal.SIGALRM)
    previous_timer = signal.getitimer(signal.ITIMER_REAL)
    signal.signal(signal.SIGALRM, _alarm_handler)
    signal.setitimer(signal.ITIMER_REAL, max(0.001, seconds))
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, *previous_timer)
        signal.signal(signal.SIGALRM, previous_handler)


def _module_in(path: object, root: str) -> bool:
    if not isinstance(path, str):
        return False
    try:
        return os.path.commonpath((os.path.realpath(path), os.path.realpath(root))) == os.path.realpath(root)
    except ValueError:
        return False


@contextlib.contextmanager
def _sdk_detector(hooks_root: str, record: dict) -> Iterator[tuple[object, object]]:
    hook_dir = os.path.join(hooks_root, record["hook"])
    sdk_dir = os.path.join(hooks_root, "_sdk")
    module_name, symbol = str(record["entrypoint"]).split(":", 1)
    module_path = os.path.join(hook_dir, module_name)
    if not os.path.isfile(module_path):
        raise EntrypointUnavailable(f"entry point module does not exist: {module_path}")
    before = set(sys.modules)
    old_path = list(sys.path)
    unique = f"_catstack_dispatch_{re.sub(r'[^A-Za-z0-9_]', '_', record['hook'])}_{time.time_ns()}"
    try:
        sys.path[:0] = [hook_dir, sdk_dir]
        import runtime as sdk_runtime

        spec = importlib.util.spec_from_file_location(unique, module_path)
        if spec is None or spec.loader is None:
            raise EntrypointUnavailable(f"could not load entry point module: {module_path}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[unique] = module
        spec.loader.exec_module(module)
        detect = getattr(module, symbol, None)
        if not callable(detect):
            raise EntrypointUnavailable(f"entry point is not callable: {record['entrypoint']}")
        yield sdk_runtime, detect
    finally:
        sys.path[:] = old_path
        for name in set(sys.modules) - before:
            module = sys.modules.get(name)
            if name == unique or _module_in(getattr(module, "__file__", None), hook_dir):
                sys.modules.pop(name, None)


def _row(
    hooks_root: str,
    hook: str,
    script: str,
    stdin: bytes,
    result_outcome: str,
    exit_code: int,
    started: float,
    stdout: bytes,
    stderr: bytes,
    rule_ids: list[str],
    dispatch_mode: str,
    payload: dict[str, object],
) -> dict:
    event = payload.get("hook_event_name")
    session_id = payload.get("session_id", payload.get("conversation_id"))
    row = run._row(
        hooks_root,
        hook,
        script,
        stdin,
        result_outcome,
        exit_code,
        started,
        stdout,
        stderr,
        rule_ids,
        stdin_fields=(event if isinstance(event, str) else None, session_id if isinstance(session_id, str) else None),
    )
    row["dispatch_mode"] = dispatch_mode
    return row


def _run_one(
    hooks_root: str,
    python: str,
    record: dict,
    stdin: bytes,
    payload: dict[str, object],
    budget: float,
) -> dict:
    hook, script = record["hook"], record["script"]
    started = time.monotonic()
    script_path = os.path.join(hooks_root, hook, script)
    findings_path = run._make_findings_file()
    stdout = b""
    stderr = b""
    exit_code = 1
    timed_out = False
    findings_error = b""
    rule_ids: list[str] = []
    try:
        if not os.path.isfile(script_path):
            stderr = f"catstack-hook-runner: no such hook script: {script_path}\n".encode()
        else:
            env = os.environ.copy()
            env["CATSTACK_HOOK_FINDINGS_FILE"] = findings_path
            try:
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
            except OSError as exc:
                stderr = f"catstack-hook-runner: could not start {hook}/{script}: {type(exc).__name__}: {exc}\n".encode()
        rule_ids, findings_error = run._read_rule_ids(findings_path)
    finally:
        run._delete_findings_file(findings_path)
    result_outcome = outcome.classify(exit_code, stdout, stderr, timed_out)
    row = _row(
        hooks_root,
        hook,
        script,
        stdin,
        result_outcome,
        exit_code,
        started,
        stdout,
        stderr,
        rule_ids,
        "subprocess_fallback",
        payload,
    )
    return {
        "hook": hook,
        "script": script,
        "outcome": result_outcome,
        "exit_code": exit_code,
        "stdout": stdout,
        "stderr": stderr + findings_error,
        "row": row,
    }


def _run_sdk(
    hooks_root: str,
    record: dict,
    stdin: bytes,
    payload: dict[str, object],
    cache: TranscriptCache,
    budget: float,
) -> dict:
    hook, script = record["hook"], record["script"]
    started = time.monotonic()
    stdout = b""
    stderr = b""
    exit_code = 0
    timed_out = False
    crashed = False
    rule_ids: list[str] = []
    try:
        with _alarm(budget):
            event = _event_with_transcripts(payload, cache)
            with _sdk_detector(hooks_root, record) as (sdk_runtime, detect), _cached_transcript_reads(cache):
                evaluated = sdk_runtime.evaluate_hook(
                    hook,
                    "claude",
                    detect,
                    event,
                    started=started,
                )
        stdout = evaluated.stdout.encode()
        stderr = evaluated.stderr.encode()
        exit_code = evaluated.exit_code
        rule_ids = [finding.rule_id for finding in evaluated.findings]
        crashed = evaluated.crashed
    except DetectorTimedOut:
        timed_out = True
        exit_code = 1
        stderr = f"catstack-hook-dispatcher: {hook}/{script} timed out after {budget:g}s\n".encode()
    except EntrypointUnavailable:
        raise
    except BaseException as exc:
        exit_code = 1
        crashed = True
        stderr = f"catstack-hook-dispatcher: {hook}/{script} crashed: {type(exc).__name__}: {exc}\n".encode()
    result_outcome = "crashed" if crashed else outcome.classify(exit_code, stdout, stderr, timed_out)
    row = _row(
        hooks_root,
        hook,
        script,
        stdin,
        result_outcome,
        exit_code,
        started,
        stdout,
        stderr,
        rule_ids,
        "in_process",
        payload,
    )
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
    hooks_root: str,
    harness: str,
    event: str,
    stdin: bytes,
    budget: float,
    detector_budget: float = DEFAULT_DETECTOR_BUDGET,
    only: str | None = None,
) -> tuple[int, bytes, bytes, list[dict]]:
    payload = _payload(stdin)
    all_records, warnings = load_event_hooks(hooks_root, harness, event)
    records = [record for record in all_records if _matcher_applies(record["matcher"], payload)]
    if only is not None:
        records = [record for record in records if record["hook"] == only]
    warning_bytes = "".join(warnings).encode()
    if not records:
        if only is None:
            return 0, b"", warning_bytes, []
        return 1, b"", warning_bytes + f"catstack-hook-dispatcher: no selected detector named {only}\n".encode(), []

    python = run._pick_python(sys.version_info, sys.executable, run._python_dirs(dict(os.environ)), dict(os.environ))
    if python is None:
        stderr = warning_bytes + (
            f"catstack-hook-dispatcher: no Python {run.MIN_PYTHON[0]}.{run.MIN_PYTHON[1]}+ interpreter found "
            f"for event {event}\n"
        ).encode()
        return 1, b"", stderr, []

    results: list[dict] = []
    if event == "SubagentStop":
        deadline = time.monotonic() + budget
        cache = TranscriptCache()
        for record in records:
            remaining = deadline - time.monotonic()
            allowed = min(detector_budget, remaining)
            if allowed <= 0:
                started = time.monotonic()
                message = f"catstack-hook-dispatcher: event budget exhausted before {record['hook']}/{record['script']}\n".encode()
                row = _row(
                    hooks_root,
                    record["hook"],
                    record["script"],
                    stdin,
                    "timed_out",
                    1,
                    started,
                    b"",
                    message,
                    [],
                    "in_process" if record.get("entrypoint") else "subprocess_fallback",
                    payload,
                )
                results.append(
                    {
                        "hook": record["hook"],
                        "script": record["script"],
                        "outcome": "timed_out",
                        "exit_code": 1,
                        "stdout": b"",
                        "stderr": message,
                        "row": row,
                    }
                )
            elif record.get("entrypoint"):
                try:
                    results.append(_run_sdk(hooks_root, record, stdin, payload, cache, allowed))
                except EntrypointUnavailable:
                    results.append(_run_one(hooks_root, python, record, stdin, payload, allowed))
            else:
                results.append(_run_one(hooks_root, python, record, stdin, payload, allowed))
    else:
        with concurrent.futures.ThreadPoolExecutor(max_workers=len(records)) as pool:
            futures = [pool.submit(_run_one, hooks_root, python, record, stdin, payload, budget) for record in records]
            for future in futures:
                results.append(future.result())

    if only is not None and len(results) == 1:
        result = results[0]
        return result["exit_code"], result["stdout"], warning_bytes + result["stderr"], [result["row"]]

    stdout, block_notes, exit_code = _merge_stdout(results)
    stderr_lines = [r["stderr"] for r in results if r["stderr"]]
    stderr = warning_bytes + b"".join(stderr_lines) + block_notes
    return exit_code, stdout, stderr, [r["row"] for r in results]


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--event", required=True)
    parser.add_argument("--timeout", type=float, default=DEFAULT_BUDGET)
    parser.add_argument("--detector-timeout", type=float, default=DEFAULT_DETECTOR_BUDGET)
    parser.add_argument("--only")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    stdin = sys.stdin.buffer.read()
    hooks_root = run._hooks_root()
    harness = run._harness(hooks_root)
    exit_code, stdout, stderr, rows = run_dispatch(
        hooks_root,
        harness,
        args.event,
        stdin,
        args.timeout,
        detector_budget=args.detector_timeout,
        only=args.only,
    )
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
