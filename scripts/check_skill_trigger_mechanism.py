#!/usr/bin/env python3
"""A skill's trigger fixtures MUST match how the skill actually activates,
not just check that some prose exists.

Two tiers, from strongest to weakest evidence available:

- Mechanism-verified (disable-model-invocation: true): per Claude Code's
  own docs, this flag means the model NEVER reads the skill's
  `description:` to decide whether to invoke it -- the description isn't
  even loaded into context. The ONLY way such a skill activates is an
  explicit `/<skill-name>` invocation. So for these skills, "does this
  fixture actually fire it" is no longer a judgment call: it's a literal
  string check. fires_example.md MUST contain `/<skill-name>`;
  stays_silent_example.md MUST NOT (a fixture that includes the
  invocation string can't credibly claim to stay silent).
- Vocabulary floor (everything else): for auto-invoked skills there is no
  deterministic oracle for "would the model's semantic match actually
  fire here" -- that's a real judgment call this script cannot make. All
  it checks is a cheap floor: fires_example.md shares at least one
  significant word with the skill's own `description:` field. This
  proves the fixture is topically about the right skill; it does NOT
  prove it would actually trigger. Report this tier's failures as
  "weak-signal" -- unlike the mechanism-verified tier, this is advisory,
  not proof of a real defect.

Usage:
    python3 scripts/check_skill_trigger_mechanism.py
    python3 scripts/check_skill_trigger_mechanism.py --strict-weak-signal
        # also fail (not just warn) on vocabulary-floor misses
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SKILL_BUCKETS = ("engine/skills", "corpus/skills", "product/skills")

STOPWORDS = frozenset(
    {
        "this", "that", "with", "from", "have", "will", "when", "does",
        "should", "into", "your", "user", "skill", "trigger", "prompt",
        "example", "about", "which", "their", "there", "these", "those",
        "than", "then", "them", "they", "what", "where", "while", "would",
        "could", "been", "being", "over", "some", "such", "only", "also",
        "each", "even", "just", "like", "make", "made", "here", "must",
        "used", "uses", "using", "asks", "says",
    }
)
WORD_RE = re.compile(r"[a-z]{4,}")


def _skill_dirs(root: Path) -> list[Path]:
    out: list[Path] = []
    for bucket in SKILL_BUCKETS:
        bucket_path = root / bucket
        if not bucket_path.is_dir():
            continue
        out.extend(sorted(p for p in bucket_path.iterdir() if p.is_dir()))
    return out


def _read_skill_md(skill_dir: Path) -> str:
    md = skill_dir / "SKILL.md"
    if not md.is_file():
        return ""
    return md.read_text(encoding="utf-8")


def _frontmatter(text: str) -> str:
    if not text.startswith("---"):
        return ""
    end = text.find("\n---", 3)
    return text[3:end] if end != -1 else ""


def is_disable_model_invocation(skill_md_text: str) -> bool:
    fm = _frontmatter(skill_md_text)
    return bool(re.search(r"^disable-model-invocation:\s*true\s*$", fm, re.MULTILINE))


def skill_name(skill_md_text: str, fallback: str) -> str:
    fm = _frontmatter(skill_md_text)
    m = re.search(r"^name:\s*(\S+)\s*$", fm, re.MULTILINE)
    return m.group(1) if m else fallback


def description_words(skill_md_text: str) -> set[str]:
    fm = _frontmatter(skill_md_text)
    m = re.search(r"^description:\s*(.*)$", fm, re.MULTILINE | re.DOTALL)
    desc = m.group(1) if m else ""
    # description may continue on following indented/quoted lines; stop at
    # the next top-level `key:` line if any.
    stop = re.search(r"\n[a-zA-Z-]+:\s", desc)
    if stop:
        desc = desc[: stop.start()]
    words = {w for w in WORD_RE.findall(desc.lower()) if w not in STOPWORDS}
    return words


def fixture_words(text: str) -> set[str]:
    return {w for w in WORD_RE.findall(text.lower()) if w not in STOPWORDS}


def check(repo_root: Path | None = None) -> tuple[list[str], list[str]]:
    """Return (mechanism_errors, weak_signal_warnings)."""
    root = repo_root or REPO_ROOT
    mechanism_errors: list[str] = []
    weak_warnings: list[str] = []

    for skill_dir in _skill_dirs(root):
        rel = skill_dir.relative_to(root).as_posix()
        fires = skill_dir / "tests" / "fires_example.md"
        silent = skill_dir / "tests" / "stays_silent_example.md"
        if not fires.is_file() or not silent.is_file():
            continue  # code-covered skill, or not yet backfilled -- out of scope here

        skill_md_text = _read_skill_md(skill_dir)
        name = skill_name(skill_md_text, skill_dir.name)
        fires_text = fires.read_text(encoding="utf-8")
        silent_text = silent.read_text(encoding="utf-8")

        if is_disable_model_invocation(skill_md_text):
            marker = f"/{name}"
            if marker not in fires_text:
                mechanism_errors.append(
                    f"{rel}: disable-model-invocation is true, so the ONLY way this "
                    f"skill activates is an explicit `{marker}` invocation -- "
                    f"tests/fires_example.md must contain that literal string, but doesn't"
                )
            if marker in silent_text:
                mechanism_errors.append(
                    f"{rel}: tests/stays_silent_example.md contains `{marker}` -- "
                    "that IS the invocation, so this can't credibly claim to stay silent"
                )
        else:
            desc_words = description_words(skill_md_text)
            fires_words = fixture_words(fires_text)
            if desc_words and not (desc_words & fires_words):
                weak_warnings.append(
                    f"{rel}: tests/fires_example.md shares no significant word with "
                    "this skill's own description -- weak signal only, may be a false "
                    "positive, but worth a human look"
                )

    return mechanism_errors, weak_warnings


def main() -> int:
    strict = "--strict-weak-signal" in sys.argv[1:]
    mechanism_errors, weak_warnings = check()

    if mechanism_errors:
        print("fail  mechanism-verified trigger check:", file=sys.stderr)
        for err in mechanism_errors:
            print(f"  - {err}", file=sys.stderr)

    if weak_warnings:
        level = "fail " if strict else "warn "
        print(f"{level} vocabulary-floor check (weak signal, human judgment still required):", file=sys.stderr)
        for w in weak_warnings:
            print(f"  - {w}", file=sys.stderr)

    if mechanism_errors or (strict and weak_warnings):
        return 1
    print("ok      skill trigger mechanism")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
