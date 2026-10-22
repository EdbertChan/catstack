#!/usr/bin/env python3
"""The bytes a harness loads for a skill must be the bytes HEAD committed.

A skill file in a checkout can stop being the committed file without git
saying so: a symlink to a private copy outside the repo, a skip-worktree or
assume-unchanged bit that hides that swap from `git status`, or an edit left
in the tree. The harness reads the resolved file, so the rules it loads are
the private copy's, and lines that land on main never reach that machine.
Martin Fowler, "SnowflakeServer" (2012), names the class: a machine
configured by hand drifts from its source and cannot be rebuilt from it.
https://martinfowler.com/bliki/SnowflakeServer.html

For every tracked file under engine/skills, corpus/skills and product/skills
this compares the working-tree file, after following symlinks, with
`git show HEAD:<path>`. Three outcomes per file:

  drift      the bytes differ, or git carries a skip-worktree or
             assume-unchanged bit for the path; reported with the skill,
             the resolved path and the line delta; exit 1
  unchecked  the resolved path or the HEAD blob could not be read; reported
             the same way; exit 1, never counted as clean
  clean      the bytes match; silent

Files that are not tracked, and files outside the three skill roots, are not
compared: there is no committed version to compare against.

Usage:
    python3 scripts/ci/check_skill_install_drift.py              # this checkout
    python3 scripts/ci/check_skill_install_drift.py --repo PATH  # another checkout
"""
from __future__ import annotations

import argparse
import difflib
import os
import subprocess
import sys
import tempfile

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__))))
SKILL_ROOTS = ("engine/skills", "corpus/skills", "product/skills")
SYMLINK_MODE = "120000"
FLAG_MEANING = {
    "S": "skip-worktree",
    "s": "skip-worktree and assume-unchanged",
    "h": "assume-unchanged",
}

PROMISED_CATCH = (
    "symlink-to-private-copy: SKILL.md -> copy with 2 extra lines",
    "skip-worktree: SKILL.md",
    "assume-unchanged: SKILL.md",
    "edited-in-tree: SKILL.md one line changed",
    "dangling-symlink: SKILL.md -> nowhere",
    "deleted-from-tree: SKILL.md",
)
PROMISED_ALLOW = (
    "clean: SKILL.md matches HEAD",
    "symlink-same-bytes: SKILL.md -> copy with identical bytes",
    "untracked-sibling: notes.md added beside the skill",
    "edited-outside-skills: README.md changed",
)


def git(repo: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", repo, *args], capture_output=True, timeout=60)


def tracked_skill_files(repo: str) -> list[tuple[str, str, str]] | None:
    """(ls-files flag, index mode, path) for every tracked file under a skill root."""
    flags = git(repo, "ls-files", "-v", "-z", "--", *SKILL_ROOTS)
    modes = git(repo, "ls-files", "-s", "-z", "--", *SKILL_ROOTS)
    if flags.returncode != 0 or modes.returncode != 0:
        return None
    mode_by_path: dict[str, str] = {}
    for entry in modes.stdout.decode("utf-8", errors="surrogateescape").split("\0"):
        if not entry:
            continue
        meta, _, path = entry.partition("\t")
        mode_by_path[path] = meta.split(" ", 1)[0]
    rows: list[tuple[str, str, str]] = []
    for entry in flags.stdout.decode("utf-8", errors="surrogateescape").split("\0"):
        if not entry:
            continue
        flag, _, path = entry.partition(" ")
        rows.append((flag, mode_by_path.get(path, ""), path))
    return rows


def head_bytes(repo: str, path: str) -> bytes | None:
    shown = git(repo, "show", f"HEAD:{path}")
    return shown.stdout if shown.returncode == 0 else None


def line_delta(committed: bytes, loaded: bytes) -> str:
    before = committed.decode("utf-8", errors="replace").splitlines()
    after = loaded.decode("utf-8", errors="replace").splitlines()
    added = removed = 0
    for line in difflib.unified_diff(before, after, lineterm="", n=0):
        if line.startswith("+") and not line.startswith("+++"):
            added += 1
        elif line.startswith("-") and not line.startswith("---"):
            removed += 1
    return f"+{added}/-{removed} lines"


def skill_name(path: str) -> str:
    for root in SKILL_ROOTS:
        if path.startswith(root + "/"):
            return path[len(root) + 1 :].split("/", 1)[0]
    return path


def check(repo: str) -> list[str]:
    rows = tracked_skill_files(repo)
    if rows is None:
        return [f"unchecked  {repo}: git ls-files failed; nothing was compared"]
    problems: list[str] = []
    for flag, mode, path in rows:
        skill = skill_name(path)
        meaning = FLAG_MEANING.get(flag)
        if meaning:
            problems.append(
                f"drift      {skill}: {path} has {meaning} set (git ls-files -v flag {flag}); "
                f"git status cannot see what replaced it"
            )
        full = os.path.join(repo, path)
        resolved = os.path.realpath(full)
        committed = head_bytes(repo, path)
        if committed is None:
            problems.append(f"unchecked  {skill}: {path} -> {resolved}: HEAD has no readable blob for this path")
            continue
        if mode == SYMLINK_MODE:
            try:
                loaded = os.readlink(full).encode("utf-8", errors="surrogateescape")
            except OSError as exc:
                problems.append(f"unchecked  {skill}: {path}: {type(exc).__name__}: {exc}")
                continue
        else:
            try:
                with open(full, "rb") as handle:
                    loaded = handle.read()
            except OSError as exc:
                problems.append(f"unchecked  {skill}: {path} -> {resolved}: {type(exc).__name__}: {exc}")
                continue
        if loaded != committed:
            problems.append(
                f"drift      {skill}: {path} -> {resolved} differs from HEAD ({line_delta(committed, loaded)})"
            )
    return problems


def _fixture_repo(root: str) -> str:
    env = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}
    subprocess.run(["git", "init", "-q", root], check=True, capture_output=True, env=env)
    for key, value in (
        ("user.email", "gate@example.com"),
        ("user.name", "gate"),
        ("commit.gpgsign", "false"),
        ("gc.auto", "0"),
        ("maintenance.auto", "false"),
    ):
        subprocess.run(["git", "-C", root, "config", key, value], check=True, capture_output=True, env=env)
    skill = os.path.join(root, "corpus", "skills", "demo")
    os.makedirs(skill)
    with open(os.path.join(skill, "SKILL.md"), "w", encoding="utf-8") as handle:
        handle.write("---\nname: demo\n---\n\n# demo\n\n- rule one\n")
    with open(os.path.join(root, "README.md"), "w", encoding="utf-8") as handle:
        handle.write("# readme\n")
    subprocess.run(["git", "-C", root, "add", "-A"], check=True, capture_output=True, env=env)
    subprocess.run(["git", "-C", root, "commit", "-q", "-m", "seed"], check=True, capture_output=True, env=env)
    return os.path.join("corpus", "skills", "demo", "SKILL.md")


def apply_scenario(root: str, scenario: str) -> None:
    rel = os.path.join("corpus", "skills", "demo", "SKILL.md")
    full = os.path.join(root, rel)
    with open(full, "rb") as handle:
        original = handle.read()
    private = os.path.join(root, "..", "private-copy", "SKILL.md")
    if scenario == "symlink-to-private-copy":
        os.makedirs(os.path.dirname(private), exist_ok=True)
        with open(private, "wb") as handle:
            handle.write(original + b"- rule two\n- rule three\n")
        os.remove(full)
        os.symlink(os.path.abspath(private), full)
    elif scenario == "symlink-same-bytes":
        os.makedirs(os.path.dirname(private), exist_ok=True)
        with open(private, "wb") as handle:
            handle.write(original)
        os.remove(full)
        os.symlink(os.path.abspath(private), full)
    elif scenario == "skip-worktree":
        subprocess.run(["git", "-C", root, "update-index", "--skip-worktree", rel], check=True, capture_output=True)
    elif scenario == "assume-unchanged":
        subprocess.run(["git", "-C", root, "update-index", "--assume-unchanged", rel], check=True, capture_output=True)
    elif scenario == "edited-in-tree":
        with open(full, "wb") as handle:
            handle.write(original.replace(b"rule one", b"rule won"))
    elif scenario == "dangling-symlink":
        os.remove(full)
        os.symlink(os.path.join(root, "nowhere", "SKILL.md"), full)
    elif scenario == "deleted-from-tree":
        os.remove(full)
    elif scenario == "untracked-sibling":
        with open(os.path.join(os.path.dirname(full), "notes.md"), "w", encoding="utf-8") as handle:
            handle.write("scratch\n")
    elif scenario == "edited-outside-skills":
        with open(os.path.join(root, "README.md"), "a", encoding="utf-8") as handle:
            handle.write("more\n")
    elif scenario != "clean":
        raise ValueError(f"unknown scenario: {scenario}")


def flags_exemplar(exemplar: str) -> bool:
    scenario = exemplar.split(":", 1)[0]
    with tempfile.TemporaryDirectory() as tmp:
        root = os.path.join(tmp, "repo")
        _fixture_repo(root)
        apply_scenario(root, scenario)
        return bool(check(root))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--repo", default=REPO_ROOT, help="checkout to compare (default: this one)")
    args = parser.parse_args(argv)
    repo = os.path.realpath(args.repo)
    problems = check(repo)
    rows = tracked_skill_files(repo) or []
    if problems:
        for line in problems:
            print(line, file=sys.stderr)
        unchecked = sum(1 for line in problems if line.startswith("unchecked"))
        drifted = len(problems) - unchecked
        print(
            f"check_skill_install_drift: FAIL {drifted} drifted, {unchecked} unchecked of {len(rows)} tracked skill file(s) in {repo}",
            file=sys.stderr,
        )
        return 1
    print(f"ok      skill install drift: {len(rows)} tracked skill file(s) load the bytes HEAD committed ({repo})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
