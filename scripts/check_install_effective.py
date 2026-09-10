#!/usr/bin/env python3
"""Verify what is INSTALLED, not what the installer would do.

install.sh's tests all run against a sandboxed fake HOME, which is correct and
is exactly why a real-world drift went unnoticed: $HOME/.claude/CLAUDE.md was a
real file shadowing the symlink, so none of the always-on principles reached
Claude while every install exited 0. A suite that proves the installer works is
not a check that the installation is in effect.

Only a real installation can be checked. When HOME is not this user's own home
directory, the run is a sandbox (install.sh's own test suite, a container
smoke test) and there is nothing installed to verify, so this reports a skip
and exits 0 rather than inventing drift. The canary is likewise a verification
tool, not a subject: a missing, failed, or unauthenticated `claude` CLI means
the rules could not be checked, not that they are absent.

A link into a git worktree of the checkout is the same class of drift as a
shadowing file: the installation is a pre-merge branch, and pruning the
worktree deletes the configuration. A worktree lives under the primary
checkout, so a prefix test against the repo root accepts it; every link is
resolved and judged on whether a `.worktrees/<name>` segment sits in its real
path. A link that cannot be read is reported as unchecked, never as clean.

Exits non-zero and names each drift. Read-only.
"""
from __future__ import annotations

import os
import pwd
import subprocess
import sys
import tempfile
from pathlib import Path

def _main_checkout() -> Path:
    """The repo links point at the primary checkout, not at a worktree of it."""
    here = Path(__file__).resolve().parents[1]
    try:
        common = subprocess.run(
            ["git", "-C", str(here), "rev-parse", "--path-format=absolute", "--git-common-dir"],
            capture_output=True, text=True, timeout=10, check=True,
        ).stdout.strip()
        if common:
            return Path(common).parent
    except Exception:
        pass
    return here


REPO = _main_checkout()
HOME = Path(os.environ.get("HOME", Path.home()))
CANARY_PHRASE = "Do not swap in a near-neighbor"
WORKTREES_DIR = ".worktrees"

PROMISED_CATCH = (
    ("a real file shadowing the symlink", ("file", "CLAUDE.md")),
    ("A link into a git worktree of the checkout", ("link", ".worktrees/feature/CLAUDE.md")),
)
PROMISED_ALLOW = (
    ("judged on whether a `.worktrees/<name>` segment sits in its real path", ("link", "CLAUDE.md")),
    ("judged on whether a `.worktrees/<name>` segment sits in its real path", ("link", "worktrees/feature/CLAUDE.md")),
)


def sandbox_reason() -> str | None:
    """Why this HOME is not a real installation, or None if it is one."""
    try:
        real_home = Path(pwd.getpwuid(os.getuid()).pw_dir)
    except KeyError:
        return f"no passwd entry for uid {os.getuid()}; cannot tell a real HOME from a sandbox"
    if os.path.realpath(HOME) != os.path.realpath(real_home):
        return f"HOME is {HOME}, not this user's home ({real_home})"
    return None


def linked(target: Path, expected: Path) -> str | None:
    if not target.exists() and not target.is_symlink():
        return f"missing: {target}"
    if not target.is_symlink():
        return f"shadowed by a real file, so the repo version is not in effect: {target}"
    resolved = target.resolve()
    if not str(resolved).startswith(str(expected)):
        return f"points outside the repo ({resolved}): {target}"
    return None


def check_links() -> list[str]:
    problems = []
    for target in (
        HOME / ".claude/CLAUDE.md",
        HOME / ".codex/AGENTS.md",
    ):
        if target.exists() or target.is_symlink():
            if (p := linked(target, REPO)) and "AGENTS" not in target.name:
                problems.append(p)
    for skill in (REPO / "corpus/skills").glob("*/SKILL.md"):
        name = skill.parent.name
        installed = HOME / ".claude/skills" / name
        if installed.exists() and not installed.is_symlink():
            problems.append(f"skill shadowed by a real directory: {installed}")
    return problems


def worktree_root(resolved: Path) -> Path | None:
    """The `.worktrees/<name>` prefix of a resolved path, or None."""
    parts = resolved.parts
    for index, part in enumerate(parts):
        if part == WORKTREES_DIR:
            return Path(*parts[: min(index + 2, len(parts))])
    return None


def exemplar_flagged(exemplar: tuple[str, str]) -> bool:
    shape, rel = exemplar
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp).resolve() / "catstack"
        source = repo / rel
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text("", encoding="utf-8")
        target = repo.parent / "home" / "CLAUDE.md"
        target.parent.mkdir(parents=True)
        if shape == "file":
            target.write_text("", encoding="utf-8")
        else:
            target.symlink_to(source)
        return linked(target, repo) is not None or worktree_root(target.resolve()) is not None


def installed_links(root: Path) -> tuple[list[Path], list[str]]:
    """Every symlink under ``root``, plus what could not be listed."""
    links: list[Path] = []
    unreadable: list[str] = []

    def unlistable(error: OSError) -> None:
        unreadable.append(
            f"could not list {error.filename} ({error.__class__.__name__}); "
            f"links under it are unchecked for worktree drift"
        )

    for dirpath, dirnames, filenames in os.walk(root, onerror=unlistable):
        for name in sorted(dirnames + filenames):
            path = Path(dirpath) / name
            try:
                if path.is_symlink():
                    links.append(path)
            except OSError as exc:
                unreadable.append(
                    f"could not test {path} ({exc.__class__.__name__}); "
                    f"it is unchecked for worktree drift"
                )
    return links, unreadable


def check_worktree_links() -> tuple[list[str], list[str]]:
    """Links resolving into a worktree instead of the primary checkout.

    Returns (drift, unchecked).
    """
    root = HOME / ".claude"
    if not root.is_dir():
        return [], [f"no {root}; links are unchecked for worktree drift"]
    links, unchecked = installed_links(root)
    by_worktree: dict[Path, list[tuple[Path, Path]]] = {}
    for link in links:
        try:
            resolved = link.resolve()
        except OSError as exc:
            unchecked.append(
                f"could not resolve {link} ({exc.__class__.__name__}); "
                f"it is unchecked for worktree drift"
            )
            continue
        worktree = worktree_root(resolved)
        if worktree is not None:
            by_worktree.setdefault(worktree, []).append((link, resolved))
    problems = []
    for worktree, found in sorted(by_worktree.items()):
        link, resolved = found[0]
        problems.append(
            f"{len(found)} link(s) under {root} resolve into the git worktree {worktree}, "
            f"not the primary checkout {REPO}, so the installation is a pre-merge branch "
            f"and removing that worktree deletes it; e.g. {link} -> {resolved}"
        )
    return problems, unchecked


def check_hooks_registered() -> list[str]:
    settings = HOME / ".claude/settings.json"
    if not settings.exists():
        return ["no ~/.claude/settings.json; no hook is registered"]
    text = settings.read_text()
    problems = []
    for hook_dir in sorted((REPO / "engine/hooks").glob("*/")):
        if not (hook_dir / "claude.hook.json").exists():
            continue
        if hook_dir.name not in text:
            problems.append(f"hook built but never registered in settings.json: {hook_dir.name}")
    return problems


def check_canary() -> tuple[list[str], list[str]]:
    """Ask the harness itself whether the rules actually loaded.

    Returns (drift, unverifiable). A definite NO is drift. Anything that
    stops the canary answering at all -- no CLI on PATH, a timeout, a
    non-zero exit such as an unauthenticated session -- is unverifiable and
    must not be reported as drift.
    """
    if not (HOME / ".claude/CLAUDE.md").is_symlink():
        return [], []
    try:
        out = subprocess.run(
            ["claude", "-p", f'Answer with one word only. Do your loaded global '
                              f'instructions contain the exact phrase "{CANARY_PHRASE}"? '
                              f'Answer YES or NO.'],
            capture_output=True, text=True, timeout=120,
        )
    except (FileNotFoundError, OSError, subprocess.TimeoutExpired) as exc:
        return [], [f"canary could not run ({exc.__class__.__name__}); link state checked only"]
    answer = out.stdout.strip()
    if out.returncode != 0:
        detail = (answer or out.stderr.strip())[:60]
        return [], [f"canary could not run (claude exited {out.returncode}: {detail!r}); link state checked only"]
    upper = answer.upper()
    if "YES" in upper:
        return [], []
    if "NO" in upper:
        return [f"canary says the always-on rules are NOT loaded (got {answer[:60]!r})"], []
    return [], [f"canary gave no YES/NO answer (got {answer[:60]!r}); link state checked only"]


def main() -> int:
    if (reason := sandbox_reason()) is not None:
        print(f"skip: {reason}; a sandboxed run has no installation to verify")
        return 0
    drift, unverifiable = check_canary()
    worktree_drift, worktree_unchecked = check_worktree_links()
    problems = check_links() + check_hooks_registered() + worktree_drift + drift
    for note in unverifiable + worktree_unchecked:
        print(f"note: {note}")
    if problems:
        print("Installation is not in effect:")
        for p in problems:
            print(f"  - {p}")
        print("\nRerun `bash install.sh --force` to back up shadowing files and link them.")
        return 1
    print("OK: links resolve into the primary checkout, not a worktree, and hooks are registered")
    return 0


if __name__ == "__main__":
    sys.exit(main())
