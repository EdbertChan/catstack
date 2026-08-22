#!/usr/bin/env python3
"""Idempotently merge the always-on draft-pr block into ~/.codex/AGENTS.md.

Codex reads AGENTS.md as global instructions. That file also holds other
personal rules, so this never replaces the whole file: it inserts or
replaces a marked block. Safe to rerun. Creates AGENTS.md when missing.
"""
import os

BEGIN = "<!-- catstack-draft-pr -->"
END = "<!-- /catstack-draft-pr -->"
AGENTS_PATH = os.path.expanduser("~/.codex/AGENTS.md")
FRAGMENT_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "always-on",
    "draft-pr.md",
)


def wrap_fragment(fragment):
    body = fragment.strip() + "\n"
    return f"{BEGIN}\n{body}{END}\n"


def merge_agents_md(existing, fragment):
    block = wrap_fragment(fragment)
    if BEGIN in existing:
        start = existing.index(BEGIN)
        end = existing.find(END, start)
        if end == -1:
            return existing[:start] + block, True
        end += len(END)
        if end < len(existing) and existing[end] == "\n":
            end += 1
        new_text = existing[:start] + block + existing[end:]
        return new_text, new_text != existing
    sep = ""
    if existing and not existing.endswith("\n"):
        sep = "\n"
    extra = "\n" if existing else ""
    return existing + sep + extra + block, True


def main():
    with open(FRAGMENT_PATH) as f:
        fragment = f.read()

    os.makedirs(os.path.dirname(AGENTS_PATH), exist_ok=True)
    existing = ""
    if os.path.exists(AGENTS_PATH):
        with open(AGENTS_PATH) as f:
            existing = f.read()

    new_text, changed = merge_agents_md(existing, fragment)
    if not changed:
        print("ok      codex AGENTS.md draft-pr block already up to date")
        return

    with open(AGENTS_PATH, "w") as f:
        f.write(new_text)
    if existing:
        print("link    merged draft-pr block into ~/.codex/AGENTS.md")
    else:
        print("link    created ~/.codex/AGENTS.md with draft-pr block")


if __name__ == "__main__":
    main()
