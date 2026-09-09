#!/usr/bin/env python3
"""Run scenario conversations through the real hook detectors.

Why this exists: the repo could prove a hook's own unit fixtures pass, and
prove a skill shipped a fires/stays_silent file, but nothing proved that a
realistic conversation actually trips the guard it was written for. A skill's
prose and a hook's regex can both look right and still miss the case.

What is deterministic here and what is not:

- DETERMINISTIC: whether a hook fires. Each scenario is materialized into a
  real transcript JSONL and passed to the hook's own `decide(payload)` -- the
  same function the installed Stop hook calls. A mismatch is a real defect.
- NOT DETERMINISTIC: whether the model chooses a given skill. That needs a
  model in the loop. This runner checks only the mechanical half of skill
  routing: whether a skill is even reachable without being named
  (`disable-model-invocation`), via `expect_skill_auto` / `expect_skill_named`.
  A scenario asserting "the model would pick /how here" is not something this
  script can honestly check, so it does not pretend to.

    python3 scripts/run_skill_scenarios.py
    python3 scripts/run_skill_scenarios.py --only fix-claim-no-evidence
    python3 scripts/run_skill_scenarios.py --list
    python3 scripts/run_skill_scenarios.py -v      # show each hook's message
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCENARIO_DIR = REPO_ROOT / "tests" / "scenarios"
HOOK_DIR = REPO_ROOT / "engine" / "hooks"

_DETECT_CACHE: dict[str, object] = {}


def load_detect(hook: str):
    """Import engine/hooks/<hook>/detect.py under a unique module name."""
    if hook in _DETECT_CACHE:
        return _DETECT_CACHE[hook]
    path = HOOK_DIR / hook / "detect.py"
    if not path.is_file():
        raise SystemExit(f"fail\tno such hook detector: {path.relative_to(REPO_ROOT)}")
    spec = importlib.util.spec_from_file_location(f"_scenario_detect_{hook.replace('-', '_')}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    _DETECT_CACHE[hook] = module
    return module


def user_line(text: str) -> dict:
    return {"type": "user", "message": {"role": "user", "content": text}}


def bash_line(command: str) -> dict:
    return {
        "type": "assistant",
        "message": {
            "role": "assistant",
            "content": [{"type": "tool_use", "name": "Bash", "input": {"command": command}}],
        },
    }


def transcript_for(scenario: dict) -> list[dict]:
    """prior entries, then the user's turn, then any tool calls made in it."""
    lines = list(scenario.get("prior") or [])
    lines.append(user_line(scenario.get("user") or "do the thing"))
    lines.extend(bash_line(c) for c in scenario.get("ran") or [])
    return lines


def write_transcript(lines: list[dict]) -> str:
    tmp = tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False, encoding="utf-8")
    tmp.write("".join(json.dumps(line) + "\n" for line in lines))
    tmp.close()
    return tmp.name


def hook_message(hook: str, scenario: dict, transcript_path: str) -> str | None:
    """The hook's real verdict for this scenario: its message, or None."""
    module = load_detect(hook)
    decide = getattr(module, "decide", None) or getattr(module, "decide_stop", None)
    if decide is None:
        raise SystemExit(f"fail\t{hook}: detect.py exposes neither decide nor decide_stop")
    payload = {
        "last_assistant_message": scenario.get("reply") or "",
        "transcript_path": transcript_path,
    }
    return decide(payload)


def skill_frontmatter(name: str) -> str | None:
    for bucket in ("engine/skills", "corpus/skills", "product/skills"):
        md = REPO_ROOT / bucket / name / "SKILL.md"
        if md.is_file():
            text = md.read_text(encoding="utf-8")
            if text.startswith("---"):
                end = text.find("\n---", 3)
                return text[3:end] if end != -1 else text
            return ""
    return None


def check_scenario(scenario: dict, verbose: bool = False) -> list[str]:
    """Failures for one scenario. Empty list means it passed."""
    failures: list[str] = []
    path = write_transcript(transcript_for(scenario))

    for hook in scenario.get("expect_fire") or []:
        msg = hook_message(hook, scenario, path)
        if not msg:
            failures.append(f"{hook}: expected to FIRE, stayed silent")
        elif verbose:
            print(f"      {hook} fired: {msg.splitlines()[0][:100]}")

    for hook in scenario.get("expect_silent") or []:
        msg = hook_message(hook, scenario, path)
        if msg:
            failures.append(f"{hook}: expected SILENCE, fired: {msg.splitlines()[0][:120]}")

    for skill in scenario.get("expect_skill_auto") or []:
        fm = skill_frontmatter(skill)
        if fm is None:
            failures.append(f"{skill}: no such skill in this repo")
        elif "disable-model-invocation: true" in fm:
            failures.append(
                f"{skill}: expected reachable without being named, but carries "
                "disable-model-invocation: true"
            )

    for skill in scenario.get("expect_skill_named") or []:
        fm = skill_frontmatter(skill)
        if fm is None:
            failures.append(f"{skill}: no such skill in this repo")
        elif "disable-model-invocation: true" not in fm:
            failures.append(
                f"{skill}: expected to require an explicit /{skill}, but is "
                "auto-invocable (no disable-model-invocation)"
            )
    return failures


def load_scenarios(directory: Path = SCENARIO_DIR) -> list[dict]:
    out: list[dict] = []
    for path in sorted(directory.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        for scenario in data if isinstance(data, list) else [data]:
            scenario.setdefault("name", path.stem)
            scenario["_file"] = path.name
            out.append(scenario)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--only", help="run just this scenario name")
    ap.add_argument("--list", action="store_true", help="list scenario names")
    ap.add_argument("-v", "--verbose", action="store_true", help="print each fired message")
    args = ap.parse_args()

    scenarios = load_scenarios()
    if not scenarios:
        print(f"fail\tno scenarios found under {SCENARIO_DIR.relative_to(REPO_ROOT)}", file=sys.stderr)
        return 1
    if args.list:
        for s in scenarios:
            print(f"{s['name']}\t{s['_file']}\t{s.get('situation', '')}")
        return 0
    if args.only:
        scenarios = [s for s in scenarios if s["name"] == args.only]
        if not scenarios:
            print(f"fail\tno scenario named {args.only}", file=sys.stderr)
            return 1

    failed = 0
    for s in scenarios:
        failures = check_scenario(s, verbose=args.verbose)
        if failures:
            failed += 1
            print(f"FAIL\t{s['name']}")
            for f in failures:
                print(f"      {f}")
        else:
            print(f"ok  \t{s['name']}")

    total = len(scenarios)
    if failed:
        print(f"\nfail\t{failed} of {total} scenario(s) failed", file=sys.stderr)
        return 1
    print(f"\nok\tall {total} scenario(s) behaved as declared")
    return 0


if __name__ == "__main__":
    sys.exit(main())
