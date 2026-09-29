#!/usr/bin/env python3
"""Every skill directory must appear in skills.toml and every listed skill must exist."""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts" / "install"))
from skills_from_registry import disk_skill_dirs, load_skills  # noqa: E402

SKILLS_TOML = REPO_ROOT / "skills.toml"

PROMISED_CATCH = (
    "unlisted product/skills/orphan",
    "missing orphan product all model prose-fixtures",
)
PROMISED_ALLOW = (
    "matched demo product all model prose-fixtures",
)


def registry_failures(skills: dict[str, dict], on_disk: dict[str, str]) -> list[str]:
    listed = set(skills)
    disk_names = set(on_disk)
    failures: list[str] = []
    for name in sorted(disk_names - listed):
        failures.append(f"FAIL skill directory not in skills.toml: {on_disk[name]}")
    for name in sorted(listed - disk_names):
        bucket = skills[name].get("bucket", "?")
        failures.append(f"FAIL skills.toml lists missing skill: {name} (bucket={bucket})")
    for name, meta in sorted(skills.items()):
        bucket = meta.get("bucket")
        want = f"{bucket}/skills/{name}" if bucket else None
        got = on_disk.get(name)
        if want and got != want:
            failures.append(f"FAIL {name}: skills.toml bucket={bucket} but on disk at {got}")
        harnesses = meta.get("harnesses")
        if harnesses not in ("all", "claude-only"):
            failures.append(f"FAIL {name}: harnesses must be all|claude-only, got {harnesses!r}")
        invocation = meta.get("invocation")
        if invocation not in ("model", "explicit", "default-injected"):
            failures.append(f"FAIL {name}: bad invocation {invocation!r}")
        test_shape = meta.get("test_shape")
        if test_shape not in ("prose-fixtures", "code-tests"):
            failures.append(f"FAIL {name}: bad test_shape {test_shape!r}")
    return failures


def flags_exemplar(exemplar: str) -> bool:
    kind, _, rest = exemplar.partition(" ")
    skills: dict[str, dict] = {}
    on_disk: dict[str, str] = {}
    if kind == "unlisted":
        on_disk[Path(rest).name] = rest
    elif kind in ("missing", "matched"):
        name, bucket, harnesses, invocation, test_shape = rest.split()
        skills[name] = {
            "bucket": bucket,
            "harnesses": harnesses,
            "invocation": invocation,
            "test_shape": test_shape,
        }
        if kind == "matched":
            on_disk[name] = f"{bucket}/skills/{name}"
    else:
        raise ValueError(f"unknown exemplar kind {kind!r}")
    return bool(registry_failures(skills, on_disk))


def main() -> int:
    if not SKILLS_TOML.is_file():
        print(f"FAIL missing {SKILLS_TOML}")
        return 1
    skills = load_skills(SKILLS_TOML)
    failures = registry_failures(skills, disk_skill_dirs(REPO_ROOT))
    if failures:
        print("\n".join(failures))
        return 1
    print(f"ok {len(skills)} skills in skills.toml match disk")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
