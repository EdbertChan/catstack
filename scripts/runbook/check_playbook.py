#!/usr/bin/env python3
"""Fail any playbook whose steps are not each bound to a rule id the repo actually ships."""
from __future__ import annotations

import argparse
import csv
import re
import sys
from pathlib import Path

RULES_TSV = Path("engine/runbook/rules.tsv")
PLAYBOOK_GLOBS = ("*/skills/*/playbooks/*.md", "*/playbooks/*.md")
REQUIRED_FRONT_MATTER_KEYS = ("runbook", "version", "applies_to", "compiled_from", "playbook-trigger", "enforcement_profile")
LIST_FRONT_MATTER_KEYS = ("applies_to", "compiled_from")
SCALAR_FRONT_MATTER_KEYS = ("runbook", "version")
ENFORCEMENT_PROFILES = ("advisory", "guided", "strict")
LEVELS = ("hard", "conditional", "soft")
LEVELS_REQUIRING_EVIDENCE = ("hard", "conditional")
MAXIMUM_STEPS = 9
MAXIMUM_STEP_BODY_LINES = 3
MINIMUM_TRIGGER_WORDS = 2
BINDING_SEPARATOR = "·"
EXIT_CLEAN = 0
EXIT_PROBLEMS = 1
EXIT_UNCHECKED = 2
STEP_HEADING = re.compile(r"^##\s+(\d+)\.\s+(.*?)\s*$")
STEP_BINDING = re.compile(r"^(?P<title>.*?)\s*\[(?P<binding>[^\[\]]*)\]$")
TRIGGER_PHRASE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 -]*$")
LIST_ITEM = re.compile(r"^[ \t]+-\s+(.*)$")
FRONT_MATTER_KEY = re.compile(r"^([A-Za-z0-9_-]+):\s*(.*)$")
USAGE = (
    "A step is one line `## N. Title [rule-id · level · evidence: key · @event]`, where level is hard, "
    "conditional or soft, and evidence plus @event are required on hard and conditional. Exit 0 is clean, exit 1 "
    "names every breach with its file and step number, and exit 2 is unchecked: the rule inventory or a playbook "
    "could not be read, which is never reported as a pass."
)


class Unchecked(Exception):
    """Raised when an input cannot be read, so the answer is unchecked rather than clean.

    The caller prints the reason and exits 2.
    """


def strip_one_quote_layer(value: str) -> str:
    """Drop one layer of matching quotes from a front matter value."""
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    return value


def split_front_matter(text: str) -> tuple[list[str] | None, list[str]]:
    """Return the lines inside the leading front matter block and the lines after it."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return None, lines
    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            return lines[1:index], lines[index + 1:]
    return None, lines


def parse_front_matter(front_matter_lines: list[str]) -> dict[str, str | list[str]]:
    """Read front matter scalars, inline lists and dash lists into one mapping."""
    fields: dict[str, str | list[str]] = {}
    current_key: str | None = None
    for line in front_matter_lines:
        item = LIST_ITEM.match(line)
        if item and current_key is not None and isinstance(fields.get(current_key), list):
            fields[current_key].append(strip_one_quote_layer(item.group(1).strip()))
            continue
        if line.startswith((" ", "\t")):
            continue
        header = FRONT_MATTER_KEY.match(line)
        if not header:
            continue
        current_key, raw_value = header.group(1), header.group(2).strip()
        if raw_value.startswith("[") and raw_value.endswith("]"):
            inner = raw_value[1:-1].strip()
            fields[current_key] = [strip_one_quote_layer(part.strip()) for part in inner.split(",") if part.strip()]
        elif raw_value == "":
            fields[current_key] = []
        else:
            fields[current_key] = strip_one_quote_layer(raw_value)
    return fields


def collect_steps(body_lines: list[str]) -> list[dict[str, object]]:
    """Pair every numbered step heading with the non-blank body lines under it."""
    steps: list[dict[str, object]] = []
    current: dict[str, object] | None = None
    for line in body_lines:
        heading = STEP_HEADING.match(line)
        if heading:
            current = {"number": int(heading.group(1)), "remainder": heading.group(2), "body": []}
            steps.append(current)
            continue
        if line.startswith("#"):
            current = None
            continue
        if current is not None and line.strip():
            current["body"].append(line)
    return steps


def normalize_trigger(trigger: str) -> str:
    """Flatten a trigger phrase to the form two spellings of one phrase share."""
    return " ".join(trigger.lower().split())


def display_path(path: Path, root: Path) -> str:
    """Name a playbook the way a person reading the repo would."""
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def read_rule_ids(root: Path) -> set[str]:
    """Read every rule id the inventory ships, or refuse rather than return an empty allowlist."""
    path = root / RULES_TSV
    try:
        with path.open(encoding="utf-8", newline="") as handle:
            rule_ids = {row["rule_id"].strip() for row in csv.DictReader(handle, delimiter="\t") if row.get("rule_id")}
    except OSError as error:
        raise Unchecked(f"{path}: rule inventory unreadable ({error}); every rule id would look unknown") from error
    except UnicodeDecodeError as error:
        raise Unchecked(f"{path}: rule inventory is not UTF-8 ({error}); every rule id would look unknown") from error
    if not rule_ids:
        raise Unchecked(f"{path}: rule inventory has no rule_id rows; every rule id would look unknown")
    return rule_ids


def read_playbook_text(path: Path) -> str:
    """Read one playbook, or refuse rather than treat an unreadable file as conforming."""
    try:
        return path.read_text(encoding="utf-8")
    except OSError as error:
        raise Unchecked(f"{path}: playbook unreadable ({error})") from error
    except UnicodeDecodeError as error:
        raise Unchecked(f"{path}: playbook is not UTF-8 ({error})") from error


def discover_playbooks(root: Path) -> list[Path]:
    """List every installed playbook under the root, each resolved path once."""
    found: dict[Path, None] = {}
    for pattern in PLAYBOOK_GLOBS:
        for path in sorted(root.glob(pattern)):
            found.setdefault(path.resolve(), None)
    return list(found)


def check_front_matter(label: str, fields: dict[str, str | list[str]], rule_ids: set[str], problems: list[str]) -> None:
    """Check the declared contract keys of one playbook."""
    for key in REQUIRED_FRONT_MATTER_KEYS:
        if key not in fields:
            problems.append(f"{label}: front matter is missing {key}")
    for key in LIST_FRONT_MATTER_KEYS:
        if key in fields and (not isinstance(fields[key], list) or not fields[key]):
            problems.append(f"{label}: {key} must be a non-empty list")
    for key in SCALAR_FRONT_MATTER_KEYS:
        if key in fields and (isinstance(fields[key], list) or not str(fields[key]).strip()):
            problems.append(f"{label}: {key} must be a non-empty value")
    profile = fields.get("enforcement_profile")
    if "enforcement_profile" in fields:
        spelled = "" if isinstance(profile, list) else str(profile).strip().lower()
        if spelled not in ENFORCEMENT_PROFILES:
            problems.append(f"{label}: enforcement_profile {profile!r} is not advisory, guided or strict")
    compiled_from = fields.get("compiled_from")
    if isinstance(compiled_from, list):
        for rule_id in compiled_from:
            if rule_id not in rule_ids:
                problems.append(f"{label}: compiled_from names unknown rule id {rule_id!r}; not in {RULES_TSV}")


def check_trigger(label: str, fields: dict[str, str | list[str]], problems: list[str]) -> str | None:
    """Check the trigger phrase shape and hand back the phrase for the collision check."""
    if "playbook-trigger" not in fields:
        return None
    trigger = fields["playbook-trigger"]
    if isinstance(trigger, list):
        problems.append(f"{label}: playbook-trigger must be one phrase, not a list")
        return None
    phrase = normalize_trigger(trigger)
    if not TRIGGER_PHRASE.match(phrase) or len(phrase.split()) < MINIMUM_TRIGGER_WORDS:
        problems.append(
            f"{label}: playbook-trigger {trigger!r} is not {MINIMUM_TRIGGER_WORDS} or more plain words "
            "of letters, digits, spaces and hyphens"
        )
        return None
    return phrase


def check_step(label: str, step: dict[str, object], rule_ids: set[str], problems: list[str]) -> None:
    """Check one step's binding, its required evidence and event, and its body length."""
    where = f"{label}: step {step['number']}"
    body_lines = step["body"]
    if len(body_lines) > MAXIMUM_STEP_BODY_LINES:
        problems.append(f"{where} has a {len(body_lines)}-line body; the cap is {MAXIMUM_STEP_BODY_LINES} lines")
    binding = STEP_BINDING.match(str(step["remainder"]))
    if not binding:
        problems.append(f"{where} ({step['remainder']!r}) carries no [rule-id {BINDING_SEPARATOR} level] binding")
        return
    if not binding.group("title").strip():
        problems.append(f"{where} has a binding but no title")
    parts = [part.strip() for part in binding.group("binding").split(BINDING_SEPARATOR)]
    rule_id = parts[0]
    level = parts[1].lower() if len(parts) > 1 else ""
    if rule_id not in rule_ids:
        problems.append(f"{where} names unknown rule id {rule_id!r}; not in {RULES_TSV}")
    if level not in LEVELS:
        problems.append(f"{where} declares level {level!r}; expected hard, conditional or soft")
    evidence_key = ""
    event_name = ""
    for part in parts[2:]:
        if part.lower().startswith("evidence:"):
            evidence_key = part.split(":", 1)[1].strip()
        elif part.startswith("@"):
            event_name = part[1:].strip()
    if level in LEVELS_REQUIRING_EVIDENCE:
        if not evidence_key:
            problems.append(f"{where} declares {level} with no 'evidence: <key>'; nothing can check it")
        if not event_name:
            problems.append(f"{where} declares {level} with no '@event'; nothing can fire it")


def check_playbook(path: Path, root: Path, rule_ids: set[str]) -> tuple[list[str], str | None]:
    """Collect every contract breach in one playbook and hand back its trigger phrase."""
    label = display_path(path, root)
    problems: list[str] = []
    front_matter_lines, body_lines = split_front_matter(read_playbook_text(path))
    if front_matter_lines is None:
        problems.append(f"{label}: no closed front matter block; a playbook declares its contract there")
        fields: dict[str, str | list[str]] = {}
    else:
        fields = parse_front_matter(front_matter_lines)
    check_front_matter(label, fields, rule_ids, problems)
    trigger = check_trigger(label, fields, problems)
    steps = collect_steps(body_lines)
    if not steps:
        problems.append(f"{label}: no '## N. Title [rule-id {BINDING_SEPARATOR} level]' steps found")
    if len(steps) > MAXIMUM_STEPS:
        problems.append(f"{label}: {len(steps)} steps; the cap is {MAXIMUM_STEPS}")
    for position, step in enumerate(steps, start=1):
        if step["number"] != position:
            problems.append(f"{label}: step {step['number']} is out of order; expected step {position}")
    for step in steps:
        check_step(label, step, rule_ids, problems)
    return problems, trigger


def read_trigger(path: Path) -> str | None:
    """Read one installed playbook's trigger phrase for the collision check."""
    front_matter_lines, _ = split_front_matter(read_playbook_text(path))
    if front_matter_lines is None:
        return None
    trigger = parse_front_matter(front_matter_lines).get("playbook-trigger")
    if not isinstance(trigger, str) or not trigger.strip():
        return None
    return normalize_trigger(trigger)


def collision_problems(label: str, trigger: str | None, installed_triggers: dict[str, list[str]]) -> list[str]:
    """Report a trigger phrase this playbook shares with another installed playbook."""
    if trigger is None:
        return []
    others = [other for other in installed_triggers.get(trigger, []) if other != label]
    if not others:
        return []
    return [f"{label}: playbook-trigger {trigger!r} is already claimed by {', '.join(sorted(others))}"]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, epilog=USAGE)
    parser.add_argument("path", nargs="?", type=Path, help="one playbook file to validate")
    parser.add_argument("--all", action="store_true", help="validate every installed playbook under --root")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    arguments = parser.parse_args(argv)
    if (arguments.path is None) == (not arguments.all):
        parser.error("give exactly one playbook path or --all")
    root = arguments.root.resolve()
    try:
        rule_ids = read_rule_ids(root)
        installed = discover_playbooks(root)
        installed_triggers: dict[str, list[str]] = {}
        for installed_path in installed:
            installed_trigger = read_trigger(installed_path)
            if installed_trigger is not None:
                installed_triggers.setdefault(installed_trigger, []).append(display_path(installed_path, root))
        targets = installed if arguments.all else [arguments.path.resolve()]
        problems: list[str] = []
        for target in targets:
            target_problems, trigger = check_playbook(target, root, rule_ids)
            problems.extend(target_problems)
            problems.extend(collision_problems(display_path(target, root), trigger, installed_triggers))
    except Unchecked as unchecked:
        print(f"unchecked: {unchecked}", file=sys.stderr)
        return EXIT_UNCHECKED
    if problems:
        for problem in problems:
            print(problem, file=sys.stderr)
        print(f"{len(problems)} problem(s) in {len(targets)} playbook(s)", file=sys.stderr)
        return EXIT_PROBLEMS
    print(f"clean: {len(targets)} playbook(s) bound to {len(rule_ids)} rule ids")
    return EXIT_CLEAN


if __name__ == "__main__":
    raise SystemExit(main())
