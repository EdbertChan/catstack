#!/usr/bin/env python3
"""A skill that tells the model to spawn subagents MUST state the scope contract.

A parent delegates because it cannot hold the work itself, which is exactly
why it cannot review every action the subagent took -- it sees a summary. So
the boundary has to be in the prompt the skill tells the parent to write, or
it is nowhere. See corpus/skills/principle-subagent-inherits-scope.

A skill qualifies as a spawner when its body instructs delegation (spawn /
fan out / subagent_type / one worker per ...). Such a skill must name
`principle-subagent-inherits-scope`, or cite the scope contract in
corpus/skills/principle-prove-it/references/finding-shape.md, which carries
it for the investigation products.

Pre-existing spawners are grandfathered in
scripts/subagent_scope_debt_allowlist.txt, shrink-only in the same way as
scripts/skill_test_debt_allowlist.txt. A new spawner must state the contract
rather than land on the list.

    python3 scripts/check_subagent_scope_contract.py
    python3 scripts/check_subagent_scope_contract.py --list   # spawners found

SPAWNER_RE is deliberately narrow: prose *about* fan-out is not an instruction
to fan out. "don't fan out delegates to hand-apply what a script can do"
(principle-build-the-lever) and "re-spawning the agent"
(principle-trace-token-burn-loop) are descriptions, and a looser pattern
flagged both. So the verb must take a concrete agent object, and NEGATED_RE
skips a line that negates or merely prices delegation.
"""
from __future__ import annotations

import argparse
import re
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SKILL_BUCKETS = ("engine/skills", "corpus/skills", "product/skills")
ALLOWLIST = REPO_ROOT / "scripts" / "subagent_scope_debt_allowlist.txt"

PRINCIPLE = "principle-subagent-inherits-scope"
CONTRACT_REF = "finding-shape.md"

SPAWNER_RE = re.compile(
    r"spawn(?:s|ing)?\s+(?:\w+\s+){0,4}?(?:subagent|agent|explorer|investigator|"
    r"reviewer|judge|worker|candidate|synthesizer|fork)s?\b|"
    r"`?subagent_type`?\s*[:=]|"
    r"fan(?:s|ning)?\s+(?:out|N)\b|"
    r"one\s+(?:worker|reviewer|explorer|investigator|agent)\s+per\b|"
    r"parallel\s+`?Agent`?\s+calls",
    re.IGNORECASE,
)

NEGATED_RE = re.compile(
    r"don't|do not|never|beats|avoid|instead of|rather than|re-spawning|"
    r"uncounted cost|worth knowing about",
    re.IGNORECASE,
)

PROMISED_CATCH = (
    "Spawn one reviewer subagent per file.",
    "Fan out to three explorers.",
    "Set subagent_type: Explore for each shard.",
    "Run one worker per package.",
    "Make parallel Agent calls, one per repo.",
)
PROMISED_ALLOW = (
    f"Spawn one reviewer subagent per file under {PRINCIPLE}.",
    f"Spawn one reviewer subagent per file; each prompt carries the contract in {CONTRACT_REF}.",
    "don't fan out delegates to hand-apply what a script can do",
    "re-spawning the agent is an uncounted cost",
    "Read every file yourself.",
)


def flags_exemplar(exemplar: str) -> bool:
    with tempfile.TemporaryDirectory() as tmp:
        skill = Path(tmp) / "corpus/skills/demo"
        skill.mkdir(parents=True)
        (skill / "SKILL.md").write_text(exemplar + "\n", encoding="utf-8")
        return bool(violations(Path(tmp), set()))


def body(text: str) -> str:
    """Everything after the frontmatter block."""
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            return text[end + 4:]
    return text


def allowlisted(path: Path = ALLOWLIST) -> set[str]:
    if not path.is_file():
        return set()
    return {
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }


def spawners(repo_root: Path) -> list[str]:
    """'bucket/name' for every skill whose body instructs delegation."""
    out: list[str] = []
    for bucket in SKILL_BUCKETS:
        root = repo_root / bucket
        if not root.is_dir():
            continue
        for skill_dir in sorted(p for p in root.iterdir() if p.is_dir()):
            md = skill_dir / "SKILL.md"
            if not md.is_file():
                continue
            for line in body(md.read_text(encoding="utf-8")).splitlines():
                if SPAWNER_RE.search(line) and not NEGATED_RE.search(line):
                    out.append(f"{bucket}/{skill_dir.name}")
                    break
    return out


def states_contract(repo_root: Path, rel: str) -> bool:
    text = (repo_root / rel / "SKILL.md").read_text(encoding="utf-8")
    return PRINCIPLE in text or CONTRACT_REF in text


def violations(repo_root: Path, allow: set[str]) -> list[str]:
    out: list[str] = []
    for rel in spawners(repo_root):
        name = rel.split("/")[-1]
        if name == PRINCIPLE or rel in allow or name in allow:
            continue
        if not states_contract(repo_root, rel):
            out.append(
                f"{rel}: instructs spawning subagents but names neither "
                f"{PRINCIPLE} nor the scope contract in {CONTRACT_REF}"
            )
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--list", action="store_true", help="print the spawners found")
    args = ap.parse_args()

    if args.list:
        for rel in spawners(REPO_ROOT):
            mark = "ok " if states_contract(REPO_ROOT, rel) else "BARE"
            print(f"{mark}\t{rel}")
        return 0

    errors = violations(REPO_ROOT, allowlisted())
    if errors:
        for e in errors:
            print(f"fail\t{e}", file=sys.stderr)
        return 1
    print("ok\tsubagent scope contract")
    return 0


if __name__ == "__main__":
    sys.exit(main())
