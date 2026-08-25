#!/usr/bin/env python3
"""Idempotently merge always-on catstack fragments into ~/.codex/AGENTS.md.

Codex reads AGENTS.md as global instructions. That file also holds other
personal rules, so this never replaces the whole file: it inserts or
replaces marked blocks. Safe to rerun. Creates AGENTS.md when missing.

Each always-on/<name>.md is wrapped in:
  <!-- catstack-<name> -->
  ...
  <!-- /catstack-<name> -->
"""
import os

REPO_DIR = os.path.dirname(os.path.abspath(__file__))
ALWAYS_ON_DIR = os.path.join(REPO_DIR, "always-on")
AGENTS_PATH = os.path.expanduser("~/.codex/AGENTS.md")

# Stable order: draft-pr first (historical), then create-skill, then any others.
PREFERRED_ORDER = ("draft-pr", "create-skill")


def fragment_paths():
    names = []
    for preferred in PREFERRED_ORDER:
        path = os.path.join(ALWAYS_ON_DIR, f"{preferred}.md")
        if os.path.isfile(path):
            names.append(preferred)
    if os.path.isdir(ALWAYS_ON_DIR):
        for filename in sorted(os.listdir(ALWAYS_ON_DIR)):
            if not filename.endswith(".md"):
                continue
            name = filename[:-3]
            if name not in names:
                names.append(name)
    return [(name, os.path.join(ALWAYS_ON_DIR, f"{name}.md")) for name in names]


def wrap_fragment(name, fragment):
    begin = f"<!-- catstack-{name} -->"
    end = f"<!-- /catstack-{name} -->"
    body = fragment.strip() + "\n"
    return begin, end, f"{begin}\n{body}{end}\n"


def merge_block(existing, begin, end, block):
    if begin in existing:
        start = existing.index(begin)
        end_idx = existing.find(end, start)
        if end_idx == -1:
            return existing[:start] + block, True
        end_idx += len(end)
        if end_idx < len(existing) and existing[end_idx] == "\n":
            end_idx += 1
        new_text = existing[:start] + block + existing[end_idx:]
        return new_text, new_text != existing
    sep = ""
    if existing and not existing.endswith("\n"):
        sep = "\n"
    extra = "\n" if existing else ""
    return existing + sep + extra + block, True


def main():
    os.makedirs(os.path.dirname(AGENTS_PATH), exist_ok=True)
    existing = ""
    if os.path.exists(AGENTS_PATH):
        with open(AGENTS_PATH) as handle:
            existing = handle.read()

    text = existing
    any_changed = False
    for name, path in fragment_paths():
        with open(path) as handle:
            fragment = handle.read()
        begin, end, block = wrap_fragment(name, fragment)
        text, changed = merge_block(text, begin, end, block)
        if changed:
            any_changed = True
            action = "merged" if existing else "created"
            print(f"link    {action} {name} block into ~/.codex/AGENTS.md")
        else:
            print(f"ok      codex AGENTS.md {name} block already up to date")

    if any_changed:
        with open(AGENTS_PATH, "w") as handle:
            handle.write(text)


if __name__ == "__main__":
    main()
