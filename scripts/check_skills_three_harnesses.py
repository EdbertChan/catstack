#!/usr/bin/env python3
"""Mechanical check: skills must target Claude, Cursor, and Codex.

Repo mode (default, CI-safe):
  - install.sh must install into all three personal skill roots
  - create-skill skill + always-on rule/fragment must state the invariant
  - CONTRIBUTING.md must state the three-harness assert

Home mode (--home):
  - Catstack skills present in any personal root must exist in all three
    (except CLAUDE_ONLY_SKILLS, which must stay Claude-only).
  - Non-catstack skills: fail only when the same symlink target is linked
    into two roots but missing from the third (incomplete multi-harness
    install). Unrelated real directories are ignored.

Exit 0 on pass, 1 on failure. Prints each failure line.
"""
from __future__ import annotations

import argparse
import os
import re
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INSTALL_SH = os.path.join(REPO_ROOT, "install.sh")
SKILLS_DIR = os.path.join(REPO_ROOT, "skills")
CREATE_SKILL = os.path.join(SKILLS_DIR, "create-skill", "SKILL.md")
CONTRIBUTING = os.path.join(REPO_ROOT, "CONTRIBUTING.md")
CURSOR_RULE = os.path.join(
    REPO_ROOT, "cursor", "rules", "create-skill-three-harnesses.mdc"
)
ALWAYS_ON = os.path.join(REPO_ROOT, "always-on", "create-skill.md")

REQUIRED_PHRASE = "Claude, Cursor, and Codex"


def parse_claude_only(install_text: str) -> set[str]:
    match = re.search(
        r"CLAUDE_ONLY_SKILLS=\((.*?)\)",
        install_text,
        flags=re.DOTALL,
    )
    if not match:
        return set()
    return set(re.findall(r"[A-Za-z0-9][A-Za-z0-9_-]*", match.group(1)))


def check_repo() -> list[str]:
    errors: list[str] = []
    with open(INSTALL_SH) as handle:
        install_text = handle.read()

    for agent, marker in (
        ("claude", 'install_into claude "$HOME/.claude/skills"'),
        ("cursor", 'install_into cursor "$HOME/.cursor/skills"'),
        ("codex", 'install_into codex'),
    ):
        if marker not in install_text or f"$HOME/.{agent}/skills" not in install_text:
            errors.append(f"install.sh missing install_into for {agent}")

    for path, label in (
        (CREATE_SKILL, "skills/create-skill/SKILL.md"),
        (CONTRIBUTING, "CONTRIBUTING.md"),
        (CURSOR_RULE, "cursor/rules/create-skill-three-harnesses.mdc"),
        (ALWAYS_ON, "always-on/create-skill.md"),
    ):
        if not os.path.isfile(path):
            errors.append(f"missing {label}")
            continue
        with open(path) as handle:
            text = handle.read()
        if REQUIRED_PHRASE not in text:
            errors.append(f"{label} must state '{REQUIRED_PHRASE}'")
        if "MUST" not in text:
            errors.append(f"{label} must use assert language (MUST)")

    if not os.path.isdir(os.path.join(SKILLS_DIR, "create-skill")):
        errors.append("skills/create-skill/ directory missing")

    link_script = os.path.join(REPO_ROOT, "scripts", "link_skill_three_harnesses.sh")
    if not os.path.isfile(link_script):
        errors.append("scripts/link_skill_three_harnesses.sh missing")
    elif not os.access(link_script, os.X_OK):
        errors.append("scripts/link_skill_three_harnesses.sh is not executable")

    return errors


def skill_names_in(root: str) -> set[str]:
    if not os.path.isdir(root):
        return set()
    names: set[str] = set()
    for entry in os.listdir(root):
        if entry.startswith("."):
            continue
        path = os.path.join(root, entry)
        if os.path.isdir(path) or os.path.islink(path):
            names.add(entry)
    return names


def repo_skill_names() -> set[str]:
    if not os.path.isdir(SKILLS_DIR):
        return set()
    return {
        name
        for name in os.listdir(SKILLS_DIR)
        if os.path.isdir(os.path.join(SKILLS_DIR, name))
    }


def skill_entry(root: str, name: str) -> tuple[bool, str | None]:
    """Return (exists, shared_symlink_target_or_None)."""
    path = os.path.join(root, name)
    if os.path.islink(path):
        return True, os.path.realpath(path)
    if os.path.isdir(path):
        return True, None
    return False, None


def check_home(home: str) -> list[str]:
    """Flag incomplete multi-harness installs.

    - Catstack repo skills MUST exist in all three roots (except CLAUDE_ONLY).
    - Non-catstack skills: only fail when the *same symlink target* is linked
      into two roots but missing from the third (the wipe-bad-pr class). Real
      single-harness copies (Invoker dirs, etc.) are ignored.
    """
    errors: list[str] = []
    with open(INSTALL_SH) as handle:
        claude_only = parse_claude_only(handle.read())

    roots = {
        "claude": os.path.join(home, ".claude", "skills"),
        "cursor": os.path.join(home, ".cursor", "skills"),
        "codex": os.path.join(home, ".codex", "skills"),
    }
    by_agent = {agent: skill_names_in(path) for agent, path in roots.items()}
    catstack_names = repo_skill_names()
    all_names = set().union(*by_agent.values()) | catstack_names

    for name in sorted(all_names):
        present = {}
        targets = {}
        for agent, root in roots.items():
            exists, target = skill_entry(root, name)
            present[agent] = exists
            if target is not None:
                targets[agent] = target

        if name in claude_only:
            if not any(present.values()):
                continue
            if not present["claude"]:
                errors.append(f"{name}: CLAUDE_ONLY but missing from ~/.claude/skills")
            for agent in ("cursor", "codex"):
                if present[agent]:
                    errors.append(
                        f"{name}: CLAUDE_ONLY but present in ~/.{agent}/skills"
                    )
            continue

        if name in catstack_names:
            if not any(present.values()):
                # Not installed into this home at all — skip (fresh/empty HOME).
                continue
            missing = [agent for agent, ok in present.items() if not ok]
            if missing:
                errors.append(
                    f"{name}: catstack skill missing from: " + ", ".join(missing)
                )
            continue

        # Same source linked into ≥2 harnesses ⇒ must be in all three.
        if len(targets) < 2:
            continue
        # Group agents by target path.
        by_target: dict[str, list[str]] = {}
        for agent, target in targets.items():
            by_target.setdefault(target, []).append(agent)
        for target, agents in by_target.items():
            if len(agents) < 2:
                continue
            missing = [agent for agent in roots if agent not in agents]
            if missing:
                errors.append(
                    f"{name}: same source linked in {', '.join(sorted(agents))} "
                    f"but missing from: {', '.join(missing)}"
                )
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--home",
        action="store_true",
        help="Check live $HOME skill roots for three-harness parity",
    )
    parser.add_argument(
        "--home-dir",
        default=os.path.expanduser("~"),
        help="Home directory to inspect with --home (default: ~)",
    )
    args = parser.parse_args(argv)

    errors = check_repo()
    if args.home:
        errors.extend(check_home(args.home_dir))

    if errors:
        print("FAIL: skills three-harness check", file=sys.stderr)
        for err in errors:
            print(f"  - {err}", file=sys.stderr)
        return 1
    print("ok      skills three-harness check")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
