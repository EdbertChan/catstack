#!/usr/bin/env python3
"""Fail closed when a skill names a file path that does not exist in catstack.

Invariant: portable skills MUST NOT reference files that are not in this
repo (or in that skill package), except a small allowlist of consumer/runtime
contract paths that intentionally live outside catstack.

Usage:
    python3 scripts/check_skill_file_refs.py
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SKILL_BUCKETS = ("engine/skills", "corpus/skills", "product/skills")

# Backtick spans that look like file paths (have a slash or a known suffix).
PATH_RE = re.compile(
    r"`("
    r"(?:[^`\s]| )*"  # allow rare spaces? we'll reject spaces later
    r")`"
)
# Simpler: no spaces inside backticks for path candidates
PATH_TICK_RE = re.compile(r"`([^`\n]+)`")

SUFFIXES = (
    ".py",
    ".sh",
    ".md",
    ".json",
    ".yaml",
    ".yml",
    ".tsv",
    ".toml",
    ".jsonl",
    ".mjs",
    ".txt",
    ".plist",
    ".mdc",
)

# Paths that intentionally do not live in catstack (consumer cwd / runtime).
CONSUMER_OR_RUNTIME_ALLOWLIST = frozenset(
    {
        ".cursor/judge-swarm-bindings.json",
        "drafter.config.json",
        ".env",
        "decisions.tsv",
        "package.json",
        "pyproject.toml",
        "AGENTS.md",
        "CLAUDE.md",  # may be root-linked; also exists in repo
    }
)


def _looks_like_path(text: str) -> bool:
    s = text.strip()
    if not s or " " in s or "\t" in s:
        return False
    if "<" in s or ">" in s:
        return False  # templates like domains/<type>.md
    if s.startswith("http://") or s.startswith("https://"):
        return False
    if s.startswith("~/"):
        return True  # absolute-ish home paths → always resolve fail unless allowlisted
    if s.startswith("/"):
        return True
    if "/" in s:
        return True
    return any(s.endswith(suf) for suf in SUFFIXES)


def _extract_paths(markdown: str) -> list[str]:
    out: list[str] = []
    for match in PATH_TICK_RE.finditer(markdown):
        inner = match.group(1).strip()
        if _looks_like_path(inner):
            out.append(inner)
    return out


def _exists_for_skill(repo: Path, skill_dir: Path, ref: str) -> bool:
    if ref in CONSUMER_OR_RUNTIME_ALLOWLIST:
        return True
    if ref.startswith("~/") or (ref.startswith("/") and not ref.startswith("//")):
        return False

    candidates = [
        skill_dir / ref,
        repo / ref,
    ]
    # Basename-only: only within the same skill package.
    if "/" not in ref:
        candidates.append(skill_dir / "scripts" / ref)
        candidates.extend(skill_dir.rglob(ref))

    for cand in candidates:
        try:
            if cand.is_file() or cand.is_dir():
                # rglob can escape with .. — reject
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
                if "/tests/" in md.as_posix().replace("\\", "/"):
                    continue
                try:
                    text = md.read_text(encoding="utf-8")
                except OSError as exc:
                    errors.append(f"{md}: {exc}")
                    continue
                rel_md = md.relative_to(root).as_posix()
                for ref in _extract_paths(text):
                    if not _exists_for_skill(root, skill_dir, ref):
                        errors.append(
                            f"{rel_md}: references missing path `{ref}` "
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
