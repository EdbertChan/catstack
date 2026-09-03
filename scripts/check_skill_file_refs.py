#!/usr/bin/env python3
"""Fail closed when skill markdown names a catstack path that does not exist.

Invariant: skill prose MUST NOT reference files/dirs that claim to live in
this repo or in that skill package but are missing. Slash commands, home
paths, npm packages, globs, and consumer/runtime contract filenames are out
of scope (or allowlisted).

Usage:
    python3 scripts/check_skill_file_refs.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SKILL_BUCKETS = ("engine/skills", "corpus/skills", "product/skills")

PATH_TICK_RE = re.compile(r"`([^`\n]+)`")
# Relative markdown links: [text](../other-skill/SKILL.md). Previously
# only backticked paths were checked, so three principle-* skills linked to
# skills that never existed (principle-prove-it-works, boundary-discipline)
# and CI stayed green.
MD_LINK_RE = re.compile(r"\[[^\]\n]*\]\((?!https?://|mailto:|#)([^)\s]+)\)")

# Repo-rooted or skill-package paths we enforce.
REPO_PREFIXES = (
    "engine/",
    "corpus/",
    "product/",
    "scripts/",
    "docs/",
    "hooks/",
    "always-on/",
    "cursor/",
    "tests/",
    "skills/",  # legacy install layout; must resolve under a bucket
    "install.sh",
)
SKILL_LOCAL_PREFIXES = ("references/", "domains/", "playbooks/", "scripts/")

# Single-segment layout names (optional dirs) — not existence-checked alone.
CONVENTION_DIRS = frozenset(
    {
        "domains/",
        "references/",
        "playbooks/",
        "scripts/",
        "stack/",
        "fixtures/",
    }
)

# Consumer / runtime paths that intentionally live outside catstack.
CONSUMER_OR_RUNTIME_ALLOWLIST = frozenset(
    {
        ".cursor/judge-swarm-bindings.json",
        ".cursor/skills/wipe-bad-pr",
        "drafter.config.json",
        ".env",
        "decisions.tsv",
        "package.json",
        "pyproject.toml",
        "AGENTS.md",
        "CLAUDE.md",
    }
)


def _should_check(ref: str) -> bool:
    s = ref.strip()
    if not s or " " in s or "\t" in s:
        return False
    if s in CONSUMER_OR_RUNTIME_ALLOWLIST:
        return False
    if s in CONVENTION_DIRS:
        return False
    if "<" in s or ">" in s:
        return False
    if "*" in s:
        return False
    if s.startswith("http://") or s.startswith("https://"):
        return False
    if s.startswith("~") or s.startswith("$"):
        return False
    if s.startswith("@"):
        return False  # npm scopes
    if s.startswith("/"):
        return False  # slash commands + absolute runtime paths
    if ":" in s:
        return False  # file:line examples
    if s == "install.sh" or s.startswith(REPO_PREFIXES):
        return True
    if s.startswith(SKILL_LOCAL_PREFIXES):
        return True
    if s.startswith(".cursor/"):
        return True  # non-allowlisted .cursor paths must exist or be allowlisted
    return False


def _extract_paths(markdown: str) -> list[str]:
    out: list[str] = []
    for match in PATH_TICK_RE.finditer(markdown):
        inner = match.group(1).strip()
        if _should_check(inner):
            out.append(inner)
    for match in MD_LINK_RE.finditer(markdown):
        out.append("link:" + match.group(1).strip())
    return out


def _legacy_skills_candidates(repo: Path, ref: str) -> list[Path]:
    """Map skills/<name>/... → engine|corpus|product/skills/<name>/..."""
    if not ref.startswith("skills/"):
        return []
    rest = ref[len("skills/") :]
    return [repo / bucket / rest for bucket in ("engine/skills", "corpus/skills", "product/skills")]


def _exists_for_skill(repo: Path, skill_dir: Path, ref: str, md: Path | None = None) -> bool:
    if ref in CONSUMER_OR_RUNTIME_ALLOWLIST:
        return True
    if ref.startswith("link:"):
        # Markdown link target, resolved relative to the linking file.
        target = ref[len("link:"):].split("#", 1)[0]
        if not target:
            return True
        base = md.parent if md is not None else skill_dir
        cand = (base / target)
        try:
            return cand.exists() and bool(cand.resolve().relative_to(repo.resolve()))
        except (OSError, ValueError):
            return False

    candidates: list[Path] = [
        skill_dir / ref,
        repo / ref,
    ]
    candidates.extend(_legacy_skills_candidates(repo, ref))

    for cand in candidates:
        try:
            if cand.is_file() or cand.is_dir():
                cand.resolve().relative_to(repo.resolve())
                return True
        except (OSError, ValueError):
            continue
    return False


def check(repo_root: Path | None = None) -> list[str]:
    root = repo_root or REPO_ROOT
    errors: list[str] = []
    for bucket in SKILL_BUCKETS:
        bucket_path = root / bucket
        if not bucket_path.is_dir():
            continue
        for skill_dir in sorted(p for p in bucket_path.iterdir() if p.is_dir()):
            for md in sorted(skill_dir.rglob("*.md")):
                # Skip on the repo-relative path. Matching on the absolute
                # path made the whole check a no-op inside any git worktree
                # under .worktrees/ (every file "contained" /.worktrees/).
                posix = "/" + md.relative_to(root).as_posix()
                if "/tests/" in posix or "/.worktrees/" in posix:
                    continue
                try:
                    text = md.read_text(encoding="utf-8")
                except OSError as exc:
                    errors.append(f"{md}: {exc}")
                    continue
                rel_md = md.relative_to(root).as_posix()
                for ref in _extract_paths(text):
                    if not _exists_for_skill(root, skill_dir, ref, md):
                        shown = ref[len("link:"):] if ref.startswith("link:") else ref
                        errors.append(
                            f"{rel_md}: references missing path `{shown}` "
                            "(skills MUST only name files that exist in this "
                            "repo/skill, or an allowlisted consumer contract path)"
                        )
    return errors


def main() -> int:
    errors = check()
    if errors:
        for err in errors:
            print(f"fail  {err}", file=sys.stderr)
        return 1
    print("ok      skill file refs")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
