from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time

RUNNER_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_DIR = os.path.dirname(os.path.dirname(os.path.dirname(RUNNER_DIR)))
sys.path.insert(0, RUNNER_DIR)
sys.path.insert(0, os.path.join(REPO_DIR, "engine", "hooks", "_flags"))

import wrap_installed  # noqa: E402

INSTALL_SH = os.path.join(REPO_DIR, "install.sh")
LAUNCH_TIMEOUT = "5"


def _real_install(fake_home: str) -> None:
    env = {
        **os.environ,
        "HOME": fake_home,
        "CATSTACK_REFLECT_RULE_FILE": os.path.join(fake_home, "reflect-enforcement.local.md"),
    }
    result = subprocess.run(["bash", INSTALL_SH], env=env, capture_output=True, text=True, timeout=180)
    if result.returncode != 0:
        raise RuntimeError(f"install.sh exited {result.returncode}\n{result.stdout}\n{result.stderr}")


def _load(path: str) -> object:
    if not os.path.isfile(path):
        return {}
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def _entry_counts(data: object) -> dict[str, int]:
    hooks = data.get("hooks") if isinstance(data, dict) else None
    counts: dict[str, int] = {}
    if not isinstance(hooks, dict):
        return counts
    for event, groups in hooks.items():
        total = 0
        for group in groups if isinstance(groups, list) else []:
            if not isinstance(group, dict):
                continue
            nested = group.get("hooks")
            if isinstance(nested, list):
                total += len(nested)
            elif isinstance(group.get("command"), str):
                total += 1
        counts[event] = total
    return counts


def _write_fixture_hooks(hooks_root: str, harness: str, event: str, count: int) -> list[str]:
    names = [f"bench-fixture-{index}" for index in range(count)]
    for name in names:
        hook_dir = os.path.join(hooks_root, name)
        os.makedirs(hook_dir, exist_ok=True)
        with open(os.path.join(hook_dir, "hook.py"), "w", encoding="utf-8") as handle:
            handle.write("")
        manifest = {
            "hooks": {
                event: [
                    {"hooks": [{"type": "command", "command": f"python3 $HOME/.{harness}/hooks/{name}/hook.py"}]}
                ]
            }
        }
        with open(os.path.join(hook_dir, f"{harness}.hook.json"), "w", encoding="utf-8") as handle:
            json.dump(manifest, handle)
    return names


def _stdin(event: str) -> bytes:
    payload = {"hook_event_name": event, "session_id": "bench", "tool_name": "Bash"}
    return json.dumps(payload).encode()


def _time_per_hook_launches(runner_dir: str, home: str, names: list[str]) -> float:
    env = os.environ.copy()
    env["HOME"] = home
    started = time.monotonic()
    for name in names:
        subprocess.run(
            [sys.executable, os.path.join(runner_dir, "run.py"), "--timeout", LAUNCH_TIMEOUT, f"{name}/hook.py"],
            input=_stdin("bench"),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=env,
        )
    return time.monotonic() - started


def _time_dispatch_launch(runner_dir: str, home: str, event: str) -> float:
    env = os.environ.copy()
    env["HOME"] = home
    started = time.monotonic()
    subprocess.run(
        [sys.executable, os.path.join(runner_dir, "dispatch.py"), "--event", event, "--timeout", LAUNCH_TIMEOUT],
        input=_stdin(event),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env=env,
    )
    return time.monotonic() - started


def bench_harness(harness: str, relative: str, off_home: str) -> list[dict[str, object]]:
    off_data = _load(os.path.join(off_home, relative))
    off_counts = _entry_counts(off_data)
    off_hooks_root = os.path.join(off_home, f".{harness}", "hooks")
    on_data, _, warnings = wrap_installed.collapse_dispatcher(
        off_data, harness, sys.executable, off_hooks_root
    )
    for warning in warnings:
        sys.stderr.write(warning)
    on_counts = _entry_counts(on_data)

    rows: list[dict[str, object]] = []
    for event in sorted(off_counts):
        before = off_counts[event]
        if before == 0:
            continue
        after = on_counts.get(event, before)

        with tempfile.TemporaryDirectory() as bench_home:
            hooks_root = os.path.join(bench_home, f".{harness}", "hooks")
            runner_dir = os.path.join(hooks_root, "_runner")
            os.makedirs(runner_dir)
            for filename in ("run.py", "outcome.py", "dispatch.py"):
                with open(os.path.join(RUNNER_DIR, filename), encoding="utf-8") as src:
                    body = src.read()
                with open(os.path.join(runner_dir, filename), "w", encoding="utf-8") as dst:
                    dst.write(body)
            names = _write_fixture_hooks(hooks_root, harness, event, before)
            wall_off = _time_per_hook_launches(runner_dir, bench_home, names)
            wall_on = _time_dispatch_launch(runner_dir, bench_home, event)

        rows.append(
            {
                "harness": harness,
                "event": event,
                "entries_off": before,
                "entries_on": after,
                "processes_off": before * 2,
                "processes_on": before + 1,
                "wall_off_s": round(wall_off, 3),
                "wall_on_s": round(wall_on, 3),
            }
        )
    return rows


def main() -> int:
    print(
        "bench_dispatch: entries_off/entries_on come from the real repo's install.sh output "
        "(flag off vs collapse_dispatcher applied in-process); wall_off_s/wall_on_s time equivalent "
        "no-op fixture hooks at the same per-event count, not the real hook bodies -- real hook logic "
        "(network calls, LLM judges) is not safe or deterministic to benchmark blindly."
    )
    with tempfile.TemporaryDirectory() as off_home:
        _real_install(off_home)
        rows: list[dict[str, object]] = []
        for harness, relative in wrap_installed.CONFIGS:
            rows.extend(bench_harness(harness, relative, off_home))

    header = f"{'harness':<8} {'event':<20} {'entries_off':>11} {'entries_on':>10} {'proc_off':>9} {'proc_on':>8} {'wall_off_s':>10} {'wall_on_s':>9}"
    print(header)
    for row in rows:
        print(
            f"{row['harness']:<8} {row['event']:<20} {row['entries_off']:>11} {row['entries_on']:>10} "
            f"{row['processes_off']:>9} {row['processes_on']:>8} {row['wall_off_s']:>10} {row['wall_on_s']:>9}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
