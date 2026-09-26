#!/usr/bin/env python3
"""Watch a remote host that cannot push, one status read per tick.

The remote part lives in its own file and travels as `ssh HOST 'bash -s' < FILE`,
so nothing in it is expanded by the local shell. Every reading gets one of three
outcomes: a status, a terminal status, or `unread`. An empty, unparseable, or
failed reading is `unread`; it never counts toward a stall and never ends the
wait as clean. A new watcher given the same --pidfile stops the older one first.

Exit codes: 0 terminal (or a readable --once reading), 3 stalled, 4 unread
(--once, or --max-unread consecutive unread readings), 2 bad arguments.
"""
from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time

def emit(record: dict) -> None:
    sys.stdout.write(json.dumps(record, sort_keys=True) + "\n")
    sys.stdout.flush()


def take_reading(ssh_bin: str, host: str, remote_script: str, timeout: float) -> tuple[str, str]:
    with open(remote_script, "rb") as script:
        try:
            proc = subprocess.run(
                [ssh_bin, host, "bash -s"], stdin=script, capture_output=True, timeout=timeout
            )
        except subprocess.TimeoutExpired:
            return "timeout", ""
    if proc.returncode != 0:
        sys.stderr.write(proc.stderr.decode("utf-8", "replace"))
        return "remote_exit", ""
    return "", proc.stdout.decode("utf-8", "replace")


def classify(failure: str, text: str, status_field: str, terminal: set[str]) -> dict:
    if failure:
        return {"record": "reading", "verdict": "unread", "reason": failure}
    if not text.strip():
        return {"record": "reading", "verdict": "unread", "reason": "empty"}
    try:
        data = json.loads(text.strip().splitlines()[-1])
    except json.JSONDecodeError:
        return {"record": "reading", "verdict": "unread", "reason": "not_json"}
    status = data.get(status_field) if isinstance(data, dict) else None
    if not isinstance(status, str) or not status:
        return {"record": "reading", "verdict": "unread", "reason": "missing_field"}
    verdict = "terminal" if status in terminal else "running"
    return {"record": "reading", "verdict": verdict, "status": status}


def start_stamp(pid: int) -> str:
    proc = subprocess.run(["ps", "-p", str(pid), "-o", "lstart="], capture_output=True, text=True)
    return proc.stdout.strip() if proc.returncode == 0 else ""


def stop_older_watcher(pidfile: str) -> None:
    try:
        with open(pidfile, encoding="utf-8") as handle:
            recorded = json.load(handle)
        old_pid = int(recorded["pid"])
        old_stamp = str(recorded["started"])
    except FileNotFoundError:
        emit({"record": "older_watcher", "state": "none"})
        return
    except (ValueError, KeyError, TypeError) as exc:
        emit({"record": "older_watcher", "state": "unreadable_pidfile", "error": type(exc).__name__})
        return
    if old_pid == os.getpid() or not old_stamp or start_stamp(old_pid) != old_stamp:
        emit({"record": "older_watcher", "state": "not_running", "pid": old_pid})
        return
    os.kill(old_pid, signal.SIGTERM)
    end = time.monotonic() + 10
    while time.monotonic() < end and start_stamp(old_pid) == old_stamp:
        time.sleep(0.05)
    state = "stopped" if start_stamp(old_pid) != old_stamp else "still_running"
    emit({"record": "older_watcher", "state": state, "pid": old_pid})


def claim_pidfile(pidfile: str) -> None:
    stop_older_watcher(pidfile)
    tmp = f"{pidfile}.{os.getpid()}"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump({"pid": os.getpid(), "started": start_stamp(os.getpid())}, handle)
    os.replace(tmp, pidfile)


def release_pidfile(pidfile: str) -> None:
    try:
        with open(pidfile, encoding="utf-8") as handle:
            owner = json.load(handle).get("pid")
    except (FileNotFoundError, ValueError) as exc:
        sys.stderr.write(f"remote_watch: pidfile {pidfile} not released: {type(exc).__name__}\n")
        return
    if owner == os.getpid():
        os.unlink(pidfile)


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--host", required=True)
    ap.add_argument("--remote-script", required=True)
    ap.add_argument("--status-field", required=True)
    ap.add_argument("--terminal", action="append", default=[])
    ap.add_argument("--idle", action="append", default=[])
    ap.add_argument("--stall-seconds", type=float, default=600.0)
    ap.add_argument("--interval", type=float, default=60.0)
    ap.add_argument("--max-unread", type=int, default=10)
    ap.add_argument("--read-timeout", type=float, default=60.0)
    ap.add_argument("--ssh-bin", default="ssh")
    ap.add_argument("--pidfile")
    ap.add_argument("--once", action="store_true")
    args = ap.parse_args(argv)
    if not os.path.isfile(args.remote_script):
        ap.error(f"--remote-script not found: {args.remote_script}")
    return args


def run(args: argparse.Namespace) -> int:
    terminal = set(args.terminal)
    idle = set(args.idle)
    idle_since: float | None = None
    unread_streak = 0
    while True:
        failure, text = take_reading(args.ssh_bin, args.host, args.remote_script, args.read_timeout)
        reading = classify(failure, text, args.status_field, terminal)
        emit(reading)
        if args.once:
            return 4 if reading["verdict"] == "unread" else 0
        if reading["verdict"] == "unread":
            unread_streak += 1
            if unread_streak >= args.max_unread:
                emit({"record": "result", "verdict": "unread", "reason": reading["reason"],
                      "consecutive_unread": unread_streak})
                return 4
        else:
            unread_streak = 0
            status = reading["status"]
            if reading["verdict"] == "terminal":
                emit({"record": "result", "verdict": "terminal", "status": status})
                return 0
            if status in idle:
                idle_since = idle_since if idle_since is not None else time.monotonic()
                if time.monotonic() - idle_since >= args.stall_seconds:
                    emit({"record": "result", "verdict": "stalled", "status": status,
                          "idle_seconds": round(time.monotonic() - idle_since, 3)})
                    return 3
            else:
                idle_since = None
        time.sleep(args.interval)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(143))
    if args.pidfile:
        claim_pidfile(args.pidfile)
    try:
        return run(args)
    finally:
        if args.pidfile:
            release_pidfile(args.pidfile)


if __name__ == "__main__":
    sys.exit(main())
