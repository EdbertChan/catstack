#!/usr/bin/env python3
"""Which skills may the model fire on its own? Declare it, then keep it true.

Two failures this catches, both real:

1. A skill whose own prose asks not to be auto-invoked while remaining
   auto-invocable. Found in this repo: product/skills/admin-bypass-sweep
   force-merges PRs past required checks via `gh pr merge --admin`, and its
   description said "MANUAL, HUMAN-ONLY ... Do not auto-invoke this skill
   from a natural-language request, a description match, or another agent's
   delegation" -- with no `disable-model-invocation: true` to enforce it.
   Prose asking a model not to match a description it can read is tier-4
   where tier-3 applies (see reflect/references/lenses.md's fix hierarchy).

2. docs/skill-triggers.md drifting from reality. A hand-maintained
   inventory of 35+ skills rots by the second PR, so the doc carries a
   generated block and this script is what proves it still matches.

    python3 scripts/check_skill_trigger_policy.py           # verify
    python3 scripts/check_skill_trigger_policy.py --write   # regenerate doc
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SKILL_BUCKETS = ("engine/skills", "corpus/skills", "product/skills")
DOC_PATH = REPO_ROOT / "docs" / "skill-triggers.md"

BEGIN_MARK = "<!-- BEGIN generated: skill-triggers (scripts/check_skill_trigger_policy.py) -->"
END_MARK = "<!-- END generated: skill-triggers -->"

FLAG = "disable-model-invocation: true"

MANUAL_DECL_RE = re.compile(
    r"human-only|do not auto-invoke|never auto-invoke|manual,\s*human|"
    r"only run this skill when a human|do not invoke (?:this )?automatically|"
    r"must not be auto-invoked",
    re.IGNORECASE,
)


def frontmatter(text: str) -> str:
    """The YAML block between the opening and closing '---' lines, or ''."""
    if not text.startswith("---"):
        return ""
    end = text.find("\n---", 3)
    return text[3:end] if end != -1 else ""


def frontmatter_declares_manual(frontmatter_block: str) -> bool:
    """Whether the skill's own frontmatter asks not to be model-invoked.

    A skill declaring itself manual/human-only there must back it with FLAG.
    Reads the frontmatter block alone, never the body, so prose describing
    some other skill's manual policy does not trip the rule.
    """
    return bool(MANUAL_DECL_RE.search(frontmatter_block))


def skills(repo_root: Path) -> list[tuple[str, str, bool, bool]]:
    """(bucket, name, auto_fires, self_declared_manual), sorted."""
    out: list[tuple[str, str, bool, bool]] = []
    for bucket in SKILL_BUCKETS:
        root = repo_root / bucket
        if not root.is_dir():
            continue
        for skill_dir in sorted(p for p in root.iterdir() if p.is_dir()):
            md = skill_dir / "SKILL.md"
            if not md.is_file():
                continue
            fm = frontmatter(md.read_text(encoding="utf-8"))
            out.append(
                (
                    bucket,
                    skill_dir.name,
                    FLAG not in fm,
                    frontmatter_declares_manual(fm),
                )
            )
    return out


def violations(rows: list[tuple[str, str, bool, bool]]) -> list[str]:
    return [
        f"{bucket}/{name}: frontmatter declares itself manual/human-only but "
        f"has no '{FLAG}', so the model can still fire it from a description match"
        for bucket, name, auto, manual in rows
        if auto and manual
    ]


def render(rows: list[tuple[str, str, bool, bool]]) -> str:
    auto = [f"`{n}`" for b, n, a, _ in rows if a]
    explicit = [f"`{n}`" for b, n, a, _ in rows if not a]
    lines = [
        BEGIN_MARK,
        "",
        f"### Auto-fire ({len(auto)})",
        "",
        "The model may invoke these from a description match. Everything here "
        "is a gate or a procedure that is useless if it only runs when named.",
        "",
        ", ".join(auto) if auto else "_none_",
        "",
        f"### Explicit invocation only ({len(explicit)})",
        "",
        f"These carry `{FLAG}`. Claude Code does not load their "
        "`description:` at all, so the only way in is a typed `/<name>`.",
        "",
        ", ".join(explicit) if explicit else "_none_",
        "",
        END_MARK,
    ]
    return "\n".join(lines)


def splice(doc: str, block: str) -> str:
    start, end = doc.find(BEGIN_MARK), doc.find(END_MARK)
    if start == -1 or end == -1:
        raise SystemExit(f"fail\t{DOC_PATH}: missing generated-block markers")
    return doc[:start] + block + doc[end + len(END_MARK):]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--write", action="store_true", help="regenerate the doc block")
    args = ap.parse_args()

    rows = skills(REPO_ROOT)
    errors = violations(rows)
    block = render(rows)

    if args.write:
        DOC_PATH.write_text(splice(DOC_PATH.read_text(encoding="utf-8"), block), encoding="utf-8")
        print(f"wrote\t{DOC_PATH.relative_to(REPO_ROOT)}")
    elif not DOC_PATH.is_file():
        errors.append("docs/skill-triggers.md: missing; run --write")
    elif block not in DOC_PATH.read_text(encoding="utf-8"):
        errors.append(
            "docs/skill-triggers.md: generated block is stale; run "
            "python3 scripts/check_skill_trigger_policy.py --write"
        )

    if errors:
        for e in errors:
            print(f"fail\t{e}", file=sys.stderr)
        return 1
    print("ok\tskill trigger policy")
    return 0


if __name__ == "__main__":
    sys.exit(main())
