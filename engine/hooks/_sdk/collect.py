from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


DEFAULT_CONFIG = Path.home() / ".invoker" / "config.json"
DEFAULT_DEST = Path.home() / ".cache" / "catstack-hook-metrics" / "fleet"
REMOTE_EVENTS_GLOB = "~/.cache/catstack-hook-metrics/events-*.jsonl"
CONNECT_TIMEOUT_SECONDS = 8
COPY_TIMEOUT_SECONDS = 60


@dataclass(frozen=True)
class Target:
    id: str
    host: str
    user: str


class Runner(Protocol):
    def __call__(self, command: list[str], timeout: int) -> subprocess.CompletedProcess[str]:
        ...


def collect(targets: list[Target], runner: Runner, dest: Path) -> dict[str, dict[str, object]]:
    dest.mkdir(parents=True, exist_ok=True)
    statuses: dict[str, dict[str, object]] = {}
    for target in targets:
        target_dir = dest / _safe_target_id(target.id)
        target_dir.mkdir(parents=True, exist_ok=True)
        command = _copy_command(target, target_dir)
        try:
            result = runner(command, COPY_TIMEOUT_SECONDS)
        except (OSError, subprocess.TimeoutExpired, ValueError) as exc:
            statuses[target.id] = {"status": "unchecked", "error": f"{type(exc).__name__}: {exc}"}
            continue
        if result.returncode == 0:
            statuses[target.id] = {"status": "ok"}
        else:
            statuses[target.id] = {"status": "unchecked", "error": _runner_error(result)}

    _write_status(dest / "status.json", statuses)
    return statuses


def load_targets(config: Path) -> list[Target]:
    with config.expanduser().open(encoding="utf-8") as handle:
        data = json.load(handle)
    remote_targets = data.get("remoteTargets", {})
    if not isinstance(remote_targets, dict):
        return []
    targets: list[Target] = []
    for target_id, raw in remote_targets.items():
        if not isinstance(raw, dict):
            continue
        host = raw.get("host")
        user = raw.get("user")
        if isinstance(target_id, str) and isinstance(host, str) and isinstance(user, str):
            targets.append(Target(target_id, host, user))
    return targets


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    try:
        targets = load_targets(args.config)
        statuses = collect(targets, _subprocess_runner, args.dest)
    except Exception as exc:
        print(f"catstack-hook-error collect: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    for target in targets:
        status = statuses.get(target.id, {"status": "unchecked", "error": "missing status"})
        line = f"{target.id}: {status['status']}"
        if status.get("error"):
            line += f": {status['error']}"
        print(line, file=sys.stderr)
    return 1 if any(status.get("status") == "unchecked" for status in statuses.values()) else 0


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Collect catstack hook event files from Invoker remote targets.")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--dest", type=Path, default=DEFAULT_DEST)
    return parser.parse_args(argv)


def _copy_command(target: Target, target_dir: Path) -> list[str]:
    destination = str(target_dir) + "/"
    return [
        "scp",
        "-q",
        "-o",
        f"ConnectTimeout={CONNECT_TIMEOUT_SECONDS}",
        "-o",
        "BatchMode=yes",
        f"{target.user}@{target.host}:{REMOTE_EVENTS_GLOB}",
        destination,
    ]


def _runner_error(result: subprocess.CompletedProcess[str]) -> str:
    for stream in (result.stderr, result.stdout):
        text = stream.strip() if isinstance(stream, str) else ""
        if text:
            return text
    return f"copy exited {result.returncode}"


def _write_status(path: Path, statuses: dict[str, dict[str, object]]) -> None:
    payload = {"targets": statuses}
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _safe_target_id(target_id: str) -> str:
    clean = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in target_id)
    return clean or "target"


def _subprocess_runner(command: list[str], timeout: int) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, capture_output=True, text=True, timeout=timeout, check=False)


if __name__ == "__main__":
    raise SystemExit(main())
