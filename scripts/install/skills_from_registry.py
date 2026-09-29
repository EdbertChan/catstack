#!/usr/bin/env python3
"""Read skills.toml for install.sh and CI."""
from __future__ import annotations

import argparse
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - py<3.11
    import tomli as tomllib  # type: ignore

REPO_ROOT = Path(__file__).resolve().parents[2]
SKILLS_TOML = REPO_ROOT / "skills.toml"
SKILL_BUCKETS = ("engine/skills", "corpus/skills", "product/skills")


def load_skills(path: Path = SKILLS_TOML) -> dict[str, dict]:
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    skills = data.get("skills")
    if not isinstance(skills, dict):
        raise SystemExit(f"{path}: missing [skills.*] tables")
    return skills


def claude_only_names(skills: dict[str, dict]) -> list[str]:
    return sorted(name for name, meta in skills.items() if meta.get("harnesses") == "claude-only")


def engine_core_product_names(skills: dict[str, dict]) -> list[str]:
    return sorted(name for name, meta in skills.items() if meta.get("engine_core_product") is True)


def skill_names(skills: dict[str, dict]) -> set[str]:
    return set(skills)


def disk_skill_dirs(repo_root: Path = REPO_ROOT) -> dict[str, str]:
    found: dict[str, str] = {}
    for bucket in SKILL_BUCKETS:
        base = repo_root / bucket
        if not base.is_dir():
            continue
        for entry in sorted(base.iterdir()):
            if entry.is_dir() and (entry / "SKILL.md").is_file():
                found[entry.name] = f"{bucket}/{entry.name}"
    return found


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--claude-only", action="store_true")
    parser.add_argument("--engine-core-product", action="store_true")
    parser.add_argument("--names", action="store_true", help="print every skill name")
    parser.add_argument("--path", type=Path, default=SKILLS_TOML)
    args = parser.parse_args(argv)
    skills = load_skills(args.path)
    if args.claude_only:
        print(" ".join(claude_only_names(skills)))
        return 0
    if args.engine_core_product:
        print(" ".join(engine_core_product_names(skills)))
        return 0
    if args.names:
        print("\n".join(sorted(skills)))
        return 0
    parser.error("pick --claude-only, --engine-core-product, or --names")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
