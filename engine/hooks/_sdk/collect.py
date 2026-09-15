from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
from pathlib import Path
import re
import subprocess
import sys
from typing import Callable, Sequence


DEFAULT_FLEET_DIR = Path.home() / ".cache" / "catstack-hook-metrics" / "fleet"
DEFAULT_CONFIG = Path.home() / ".invoker" / "config.json"
REMOTE_EVENTS_GLOB = "~/.cache/catstack-hook-metrics/events-*.jsonl"
CONNECT_TIMEOUT_SECONDS = 10


@dataclass(frozen=True)
class Target:
    target_id: str
    host: str | None
    user: str | None


Runner = Callable[[list[str]], object]


def _safe_target_id(target_id: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", target_id).strip("._")
    return safe or "target"


def load_targets(config_path: Path) -> list[Target]:
    with config_path.expanduser().open("r", encoding="utf-8") as handle:
        config = json.load(handle)

    remote_targets = config.get("remoteTargets", {}) if isinstance(config, dict) else {}
    if not isinstance(remote_targets, dict):
        raise ValueError("remoteTargets must be an object")

    targets: list[Target] = []
    for target_id, raw in remote_targets.items():
        if not isinstance(raw, dict):
            continue
        host = raw.get("host")
        user = raw.get("user")
        targets.append(
            Target(
                _safe_target_id(str(target_id)),
                host if isinstance(host, str) and host else None,
                user if isinstance(user, str) and user else None,
            )
        )
    return targets


def _copy_command(target: Target, machine_dir: Path, connect_timeout: int) -> list[str]:
    return [
        "scp",
        "-o",
        "BatchMode=yes",
        "-o",
        f"ConnectTimeout={connect_timeout}",
        f"{target.user}@{target.host}:{REMOTE_EVENTS_GLOB}",
        str(machine_dir) + "/",
    ]


def _runner_error(exc: BaseException) -> str:
    if isinstance(exc, subprocess.CalledProcessError):
        stderr = exc.stderr.decode("utf-8", errors="replace") if isinstance(exc.stderr, bytes) else exc.stderr
        stdout = exc.stdout.decode("utf-8", errors="replace") if isinstance(exc.stdout, bytes) else exc.stdout
        detail = (stderr or stdout or "").strip()
        if detail:
            return detail
        return f"copy failed with exit code {exc.returncode}"
    return f"{type(exc).__name__}: {exc}"


def default_runner(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, check=True, capture_output=True, text=True)


def collect(
    targets: Sequence[Target],
    runner: Runner,
    dest: Path,
    *,
    connect_timeout: int = CONNECT_TIMEOUT_SECONDS,
) -> dict[str, dict[str, str]]:
    dest = dest.expanduser()
    dest.mkdir(parents=True, exist_ok=True)

    status: dict[str, dict[str, str]] = {}
    for target in targets:
        machine_dir = dest / target.target_id
        machine_dir.mkdir(parents=True, exist_ok=True)
        if not target.host or not target.user:
            status[target.target_id] = {
                "status": "unchecked",
                "error": "missing host or user",
            }
            continue
        try:
            runner(_copy_command(target, machine_dir, connect_timeout))
            status[target.target_id] = {"status": "ok"}
        except Exception as exc:
            status[target.target_id] = {
                "status": "unchecked",
                "error": _runner_error(exc),
            }

    status_path = dest / "status.json"
    with status_path.open("w", encoding="utf-8") as handle:
        json.dump(status, handle, indent=2, sort_keys=True)
        handle.write("\n")
    return status


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Collect catstack hook metrics from Invoker remote targets.")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG), help="Invoker config path")
    parser.add_argument("--dest", default=str(DEFAULT_FLEET_DIR), help="local fleet metrics directory")
    parser.add_argument("--connect-timeout", type=int, default=CONNECT_TIMEOUT_SECONDS)
    args = parser.parse_args(argv)

    try:
        targets = load_targets(Path(args.config))
        status = collect(
            targets,
            default_runner,
            Path(args.dest),
            connect_timeout=args.connect_timeout,
        )
    except Exception as exc:
        print(f"catstack-hook-error collect: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    return 1 if any(record.get("status") == "unchecked" for record in status.values()) else 0


if __name__ == "__main__":
    sys.exit(main())
