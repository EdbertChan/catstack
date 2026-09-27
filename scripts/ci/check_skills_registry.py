#!/usr/bin/env python3
"""Every skill directory must appear in skills.toml and every listed skill must exist."""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts" / "install"))
from skills_from_registry import disk_skill_dirs, load_skills  # noqa: E402

SKILLS_TOML = REPO_ROOT / "skills.toml"


def main() -> int:
    if not SKILLS_TOML.is_file():
        print(f"FAIL missing {SKILLS_TOML}")
        return 1
    skills = load_skills(SKILLS_TOML)
    on_disk = disk_skill_dirs(REPO_ROOT)
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
    if failures:
        print("\n".join(failures))
        return 1
    print(f"ok {len(listed)} skills in skills.toml match disk")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
