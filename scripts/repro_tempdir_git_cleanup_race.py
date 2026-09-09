#!/usr/bin/env python3
"""Stress the exact tempdir+git sequence that flakes in CI and name the writer.

Usage: repro_tempdir_git_cleanup_race.py [iterations] [--fix]
Exit 1 (and dumps the state of .git/objects plus every live git process) as
soon as a TemporaryDirectory cleanup raises."""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

FIX = "--fix" in sys.argv
ARGS = [a for a in sys.argv[1:] if not a.startswith("-")]
ITERATIONS = int(ARGS[0]) if ARGS else 200


def git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), *args], check=True, capture_output=True, text=True
    )
    return result.stdout.strip()


def write(path: Path, text: str = "# x\n") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def init(root: Path) -> None:
    if FIX:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from git_test_repo import init_repo  # noqa: E402

        init_repo(root, "-b", "main")
    else:
        subprocess.run(
            ["git", "init", "-q", "-b", "main", str(root)], check=True, capture_output=True
        )
    git(root, "config", "user.email", "test@example.com")
    git(root, "config", "user.name", "Test")


def build(root: Path) -> str:
    init(root)
    write(root / "engine/skills/reflect/SKILL.md", "---\nname: reflect\n---\n")
    write(root / "engine/skills/reflect/baselines/dora-ai-report.md", "deploy 3\n")
    write(root / "engine/skills/reflect/scripts/tests/test_x.py", "def test_a():\n    assert True\n")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "base")
    base = git(root, "rev-parse", "HEAD")
    write(root / "engine/skills/reflect/baselines/dora-ai-report.md", "deploy 4\n")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "weekly snapshot")
    merge_base = git(root, "merge-base", base, "HEAD")
    git(root, "diff", "--name-only", "--diff-filter=AM", merge_base, "HEAD")
    return base


def dump(root: Path) -> None:
    objects = root / ".git" / "objects"
    print(f"--- leftover under {objects} ---", flush=True)
    for dirpath, dirnames, filenames in os.walk(objects):
        for name in dirnames + filenames:
            full = Path(dirpath) / name
            try:
                st = full.stat()
                print(f"  {full}  size={st.st_size} mtime={st.st_mtime}", flush=True)
            except OSError as err:
                print(f"  {full}  <stat failed: {err}>", flush=True)
    print("--- live git processes ---", flush=True)
    print(subprocess.run(["ps", "-eo", "pid,ppid,lstart,args"], capture_output=True, text=True).stdout, flush=True)


def main() -> int:
    print(f"git: {subprocess.run(['git', '--version'], capture_output=True, text=True).stdout.strip()}", flush=True)
    print(f"python: {sys.version}", flush=True)
    print(f"fix={FIX} iterations={ITERATIONS}", flush=True)
    failures = 0
    for i in range(1, ITERATIONS + 1):
        try:
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                build(root)
                keep = root
        except OSError as err:
            failures += 1
            print(f"ITERATION {i} CLEANUP FAILED: {err!r}", flush=True)
            dump(keep)
            print(f"FAILURES={failures}/{i}", flush=True)
            return 1
    print(f"FAILURES=0/{ITERATIONS}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
