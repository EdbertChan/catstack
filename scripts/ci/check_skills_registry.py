#!/usr/bin/env python3
"""Every skill directory must appear in skills.toml and every listed skill must exist."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts" / "install"))
from skills_from_registry import disk_skill_dirs, load_skills  # noqa: E402

SKILLS_TOML = REPO_ROOT / "skills.toml"

VALID_META = """\
harnesses = "all"
invocation = "model"
test_shape = "prose-fixtures"
"""

PROMISED_CATCH = (
    "product/skills/demo/SKILL.md exists but skills.toml is missing",
    "product/skills/demo/SKILL.md exists but skills.toml has no [skills.demo]",
    "skills.toml lists [skills.ghost] but product/skills/ghost/SKILL.md is missing",
    "skills.toml says demo bucket = corpus but demo lives in product/skills/demo",
    "skills.toml gives demo harnesses = codex-only",
    "skills.toml gives demo invocation = manual",
    "skills.toml gives demo test_shape = screenshots",
)
PROMISED_ALLOW = (
    "product/skills/demo/SKILL.md exists and [skills.demo] matches it",
    "corpus/skills/demo/SKILL.md exists and [skills.demo] matches it",
)


def _registry_entry(name: str, bucket: str = "product", overrides: str = "") -> str:
    body = overrides or VALID_META
    return f'[skills.{name}]\nbucket = "{bucket}"\n{body}'


def flags_exemplar(exemplar: str) -> bool:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        if "demo" in exemplar and "[skills.ghost]" not in exemplar:
            bucket = "corpus" if exemplar.startswith("corpus/") else "product"
            skill_dir = root / bucket / "skills" / "demo"
            skill_dir.mkdir(parents=True)
            (skill_dir / "SKILL.md").write_text("---\nname: demo\n---\n", encoding="utf-8")
        if "skills.toml is missing" not in exemplar:
            if "no [skills.demo]" in exemplar:
                body = _registry_entry("other")
            elif "[skills.ghost]" in exemplar:
                body = _registry_entry("ghost")
            elif "bucket = corpus" in exemplar:
                body = _registry_entry("demo", bucket="corpus")
            elif "harnesses = codex-only" in exemplar:
                body = _registry_entry("demo", overrides='harnesses = "codex-only"\ninvocation = "model"\ntest_shape = "prose-fixtures"\n')
            elif "invocation = manual" in exemplar:
                body = _registry_entry("demo", overrides='harnesses = "all"\ninvocation = "manual"\ntest_shape = "prose-fixtures"\n')
            elif "test_shape = screenshots" in exemplar:
                body = _registry_entry("demo", overrides='harnesses = "all"\ninvocation = "model"\ntest_shape = "screenshots"\n')
            else:
                bucket = "corpus" if exemplar.startswith("corpus/") else "product"
                body = _registry_entry("demo", bucket=bucket)
            (root / "skills.toml").write_text(body, encoding="utf-8")
        return bool(check(root))


def check(repo_root: Path = REPO_ROOT) -> list[str]:
    skills_toml = repo_root / "skills.toml"
    if not skills_toml.is_file():
        return [f"FAIL missing {skills_toml}"]
    skills = load_skills(skills_toml)
    on_disk = disk_skill_dirs(repo_root)
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


def main() -> int:
    failures = check(REPO_ROOT)
    if failures:
        print("\n".join(failures))
        return 1
    print(f"ok {len(load_skills(SKILLS_TOML))} skills in skills.toml match disk")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
