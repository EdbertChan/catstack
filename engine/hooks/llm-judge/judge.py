#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import traceback
import uuid

TIMEOUT_SECONDS = 60
INVESTIGATE_TIMEOUT_CAP = 600
KILL_GRACE_SECONDS = 5
REASON_LIMIT = 300
PROMPT_SLOT = "{prompt}"
CHILD_ENV = "CATSTACK_LLM_JUDGE_CHILD"
RUNNERS_ENV = "CATSTACK_LLM_JUDGE_RUNNERS"
STATE_ENV = "CATSTACK_LLM_JUDGE_STATE_DIR"
DEFAULT_RUNNERS = (
    ("codex", ["codex", "exec", "--skip-git-repo-check", "-m", "gpt-5.3-codex-spark", "--sandbox", "read-only", "-c", "notify=[]", PROMPT_SLOT]),
    ("claude", ["claude", "-p", "--model", "haiku", "--settings", '{"disableAllHooks": true}', PROMPT_SLOT]),
    ("cursor", ["cursor-agent", "-p", "--output-format", "text", PROMPT_SLOT]),
)
INVESTIGATE_RUNNERS = (
    ("codex", ["codex", "exec", "--skip-git-repo-check", "--sandbox", "read-only", "-c", "notify=[]", PROMPT_SLOT]),
    ("claude", ["claude", "-p", "--model", "haiku", "--settings", '{"disableAllHooks": true}', "--allowedTools", "Read", "Grep", "Glob", "--disallowedTools", "Write", "Edit", "NotebookEdit", "Bash", "--", PROMPT_SLOT]),
)


def state_root() -> str:
    return os.environ.get(STATE_ENV) or os.path.join(os.path.expanduser("~"), ".cache", "catstack-llm-judge")


def log(message: str) -> None:
    root = state_root()
    os.makedirs(root, exist_ok=True)
    with open(os.path.join(root, "judge.log"), "a", encoding="utf-8") as handle:
        handle.write(f"{time.strftime('%Y-%m-%dT%H:%M:%S')} {message}\n")


def valid_runner(entry: object) -> bool:
    return (
        isinstance(entry, list)
        and len(entry) == 2
        and isinstance(entry[0], str)
        and isinstance(entry[1], list)
        and bool(entry[1])
        and all(isinstance(item, str) for item in entry[1])
    )


def runners(mode: object = None) -> list[tuple[str, list[str]]]:
    default = INVESTIGATE_RUNNERS if mode == "investigate" else DEFAULT_RUNNERS
    raw = os.environ.get(RUNNERS_ENV)
    if not raw:
        return [(name, list(argv)) for name, argv in default]
    try:
        parsed = json.loads(raw)
    except ValueError as exc:
        raise ValueError(f"{RUNNERS_ENV} is not valid JSON: {exc}") from exc
    if not isinstance(parsed, list) or not all(valid_runner(entry) for entry in parsed):
        raise ValueError(f"{RUNNERS_ENV} must be a JSON list of [name, [argv...]] pairs")
    return [(entry[0], list(entry[1])) for entry in parsed]


def clip(label: str, detail: str) -> str:
    detail = (detail or "").strip()
    room = REASON_LIMIT - len(label) - 2
    if not detail or room <= 0:
        return label[:REASON_LIMIT]
    return f"{label}: {detail[-room:]}"


def last_json_object(text: str) -> dict | None:
    found = None
    for line in text.splitlines():
        try:
            value = json.loads(line)
        except ValueError:
            continue
        if isinstance(value, dict):
            found = value
    return found


def failed(name: str, reason: str) -> dict:
    return {"runner": name, "ok": False, "reason": reason}


def stop_group(proc: subprocess.Popen) -> str:
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except OSError as exc:
        log(f"runner pid {proc.pid}: could not kill its process group ({exc}); killing the runner alone")
        proc.kill()
    _, stderr = proc.communicate(timeout=KILL_GRACE_SECONDS)
    return stderr or ""


def bounded_timeout(timeout_seconds: object) -> int | float:
    if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, (int, float)):
        timeout_seconds = TIMEOUT_SECONDS
    return min(timeout_seconds, INVESTIGATE_TIMEOUT_CAP)


def run_runner(name: str, argv: list[str], prompt: str, timeout_seconds: object = TIMEOUT_SECONDS, cwd: object = None) -> tuple[dict, dict | None]:
    if shutil.which(argv[0]) is None:
        return failed(name, "not installed"), None
    command = [prompt if item == PROMPT_SLOT else item for item in argv]
    env = dict(os.environ)
    env[CHILD_ENV] = "1"
    timeout = bounded_timeout(timeout_seconds)
    with tempfile.TemporaryDirectory(prefix="llm-judge-") as temp_cwd:
        runner_cwd = temp_cwd
        if cwd is not None:
            if isinstance(cwd, str) and os.path.isabs(cwd) and os.path.isdir(cwd):
                runner_cwd = cwd
            else:
                log(f"runner {name}: refused cwd {cwd!r}")
        try:
            proc = subprocess.Popen(
                command,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                cwd=runner_cwd,
                env=env,
                start_new_session=True,
            )
        except OSError as exc:
            return failed(name, clip(type(exc).__name__, str(exc))), None
        try:
            stdout, stderr = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            return failed(name, clip(f"timed out after {timeout}s", stop_group(proc))), None
    if proc.returncode != 0:
        return failed(name, clip(f"exit {proc.returncode}", stderr)), None
    answer = last_json_object(stdout)
    if answer is None:
        return failed(name, clip("no JSON object line in stdout", stderr or stdout)), None
    return {"runner": name, "ok": True, "reason": "answered"}, answer


def ask(prompt: str, mode: object = None, timeout_seconds: object = None, cwd: object = None) -> dict:
    if timeout_seconds is None:
        timeout_seconds = TIMEOUT_SECONDS
    attempts = []
    for name, argv in runners(mode):
        attempt, answer = run_runner(name, argv, prompt, timeout_seconds=timeout_seconds, cwd=cwd)
        attempts.append(attempt)
        if answer is not None:
            return {"outcome": "answered", "runner": name, "answer": answer, "attempts": attempts}
    return {"outcome": "unchecked", "runner": None, "answer": None, "attempts": attempts}


def verdict(job: dict, result: dict) -> dict:
    answer = result.get("answer") if result.get("outcome") == "answered" else None
    attempts = result.get("attempts") or []
    if isinstance(answer, dict):
        keys = list(job.get("hit_if_all_true") or [])
        not_true = [key for key in keys if answer.get(key) is not True]
        outcome = "clean" if not_true else "hit"
        reason = f"not true: {', '.join(not_true)}" if not_true else f"all true: {', '.join(keys)}"
    else:
        answer = None
        outcome = "unchecked"
        tried = "; ".join(f"{a.get('runner')}: {a.get('reason')}" for a in attempts)
        reason = clip("no runner answered", tried)
    return {
        "id": job.get("id"),
        "hook": job.get("hook"),
        "transcript": job.get("transcript"),
        "outcome": outcome,
        "on_hit": job.get("on_hit"),
        "reason": reason,
        "runner": result.get("runner") if answer is not None else None,
        "answer": answer,
        "attempts": attempts,
        "finished_at": time.time(),
    }


def write_json_atomic(path: str, data: dict) -> None:
    folder = os.path.dirname(path)
    os.makedirs(folder, exist_ok=True)
    fd, temp = tempfile.mkstemp(dir=folder, prefix=".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle)
        os.replace(temp, path)
    except BaseException:
        os.unlink(temp)
        raise


def verdict_dir(transcript: str) -> str:
    digest = hashlib.sha1(transcript.encode("utf-8")).hexdigest()[:16]
    return os.path.join(state_root(), "verdicts", digest)


def enqueue(job: dict) -> str | None:
    if CHILD_ENV in os.environ:
        return None
    job = dict(job)
    job_id = str(job.get("id") or uuid.uuid4().hex)
    if os.path.basename(job_id) != job_id or job_id.startswith("."):
        raise ValueError(f"job id {job_id!r} is not a plain file name")
    job["id"] = job_id
    root = state_root()
    job_path = os.path.join(root, "jobs", f"{job_id}.json")
    write_json_atomic(job_path, job)
    with open(os.path.join(root, "judge.log"), "a", encoding="utf-8") as log_handle:
        subprocess.Popen(
            [sys.executable or "python3", os.path.abspath(__file__), "run", job_path],
            start_new_session=True,
            stdin=subprocess.DEVNULL,
            stdout=log_handle,
            stderr=log_handle,
            cwd=root,
        )
    return job_id


def run_job(path: str) -> dict:
    stem = os.path.splitext(os.path.basename(path))[0]
    job: dict = {"id": stem}
    try:
        with open(path, encoding="utf-8") as handle:
            loaded = json.load(handle)
        if not isinstance(loaded, dict):
            raise ValueError(f"job file holds a JSON {type(loaded).__name__}, not an object")
        job = dict(loaded)
        job.setdefault("id", stem)
        result = verdict(job, ask(str(job["prompt"]), mode=job.get("mode"), timeout_seconds=job.get("timeout_seconds", TIMEOUT_SECONDS), cwd=job.get("cwd")))
    except Exception as exc:
        print(f"catstack-hook-error llm-judge: {type(exc).__name__}: {exc}", file=sys.stderr)
        log(f"job {job.get('id')} failed: {type(exc).__name__}: {exc}\n{traceback.format_exc()}")
        result = verdict(job, {"outcome": "unchecked", "attempts": []})
        result["reason"] = clip(f"judge error {type(exc).__name__}", str(exc))
    write_json_atomic(os.path.join(verdict_dir(str(job.get("transcript") or "")), f"{stem}.json"), result)
    try:
        os.remove(path)
    except OSError as exc:
        log(f"job {job.get('id')}: verdict written but the job file could not be deleted: {exc}")
    return result


def drain(transcript: str) -> list[dict]:
    folder = verdict_dir(transcript)
    if not os.path.isdir(folder):
        return []
    claimed = []
    for name in sorted(os.listdir(folder)):
        if name.startswith(".") or not name.endswith(".json"):
            continue
        taken = os.path.join(folder, f".{name}.{os.getpid()}.drain")
        try:
            os.rename(os.path.join(folder, name), taken)
        except FileNotFoundError as exc:
            log(f"drain: verdict {name} for {transcript} was claimed by another drain: {exc}")
            continue
        claimed.append((os.stat(taken).st_mtime_ns, name, taken))
    verdicts = []
    for _, name, taken in sorted(claimed):
        try:
            with open(taken, encoding="utf-8") as handle:
                loaded = json.load(handle)
            if not isinstance(loaded, dict):
                raise ValueError(f"verdict file holds a JSON {type(loaded).__name__}, not an object")
            verdicts.append(loaded)
        except (OSError, ValueError) as exc:
            log(f"drain: unreadable verdict {name} for {transcript}: {exc}")
            verdicts.append({
                "id": name[: -len(".json")],
                "transcript": transcript,
                "outcome": "unchecked",
                "reason": clip("unreadable verdict file", str(exc)),
            })
        os.remove(taken)
    return verdicts


def main(argv: list[str]) -> int:
    if len(argv) == 2 and argv[0] == "run":
        run_job(argv[1])
        return 0
    print("usage: judge.py run <job path>", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
