#!/usr/bin/env python3
"""Write every rule the repo ships, hooks and skills alike, into one TSV that people annotate."""
from __future__ import annotations

import argparse
import csv
import io
import re
import sys
import tomllib
from pathlib import Path

MECHANICAL = ("rule_id", "kind", "bucket", "source", "mode", "why_mode", "auto_fire", "summary")
REVIEW = ("proposed_level", "verifiability", "severity", "fp_cost")
COLUMNS = MECHANICAL + REVIEW
BUCKETS = ("engine", "corpus", "product")
DEFAULT_OUT = Path("engine/runbook/rules.tsv")
SUMMARY_LIMIT = 160
USAGE = (
    "Mechanical columns are regenerated every run from hooks.toml and SKILL.md front matter. "
    "The review columns (proposed_level, verifiability, severity, fp_cost) are filled by people "
    "and kept for any rule id already in the file. --check exits 1 when the file on disk is stale."
)


def parse_front_matter(text: str, source: Path) -> dict[str, str]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise SystemExit(f"{source}: no front matter block; a skill without one cannot install, so it cannot be inventoried")
    fields: dict[str, str] = {}
    key = None
    folded = False
    for line in lines[1:]:
        if line.strip() == "---":
            break
        match = re.match(r"^([A-Za-z0-9_-]+):\s*(.*)$", line)
        if match and not line.startswith((" ", "\t")):
            key, value = match.group(1), match.group(2).strip()
            folded = value in (">", ">-", "|", "|-")
            fields[key] = "" if folded else value.strip("\"'")
            continue
        if key is not None and folded and line.startswith((" ", "\t")):
            fields[key] = (fields[key] + " " + line.strip()).strip()
    return fields


def one_line(text: str) -> str:
    flat = " ".join(text.split())
    return flat if len(flat) <= SUMMARY_LIMIT else flat[: SUMMARY_LIMIT - 1].rstrip() + "…"


def hook_rows(root: Path) -> list[dict[str, str]]:
    config = root / "engine" / "hooks" / "hooks.toml"
    data = tomllib.loads(config.read_text(encoding="utf-8"))
    rows = []
    for name, entry in sorted(data.get("hooks", {}).items()):
        rows.append({
            "rule_id": name,
            "kind": "hook",
            "bucket": "engine",
            "source": f"engine/hooks/{name}/",
            "mode": str(entry.get("mode", "")),
            "why_mode": str(entry.get("why_mode", "")),
            "auto_fire": "event",
            "summary": one_line(str(entry.get("summary", ""))),
        })
    return rows


def skill_rows(root: Path) -> list[dict[str, str]]:
    rows = []
    for bucket in BUCKETS:
        for skill_md in sorted((root / bucket / "skills").glob("*/SKILL.md")):
            fields = parse_front_matter(skill_md.read_text(encoding="utf-8"), skill_md)
            explicit_only = fields.get("disable-model-invocation", "").lower() == "true"
            rows.append({
                "rule_id": fields.get("name") or skill_md.parent.name,
                "kind": "skill",
                "bucket": bucket,
                "source": str(skill_md.relative_to(root)),
                "mode": "prose",
                "why_mode": "",
                "auto_fire": "no" if explicit_only else "yes",
                "summary": one_line(fields.get("description", "")),
            })
    return rows


def read_existing(path: Path) -> dict[str, dict[str, str]]:
    if not path.exists():
        print(f"no inventory at {path} yet; review columns start empty", file=sys.stderr)
        return {}
    with path.open(encoding="utf-8", newline="") as handle:
        return {row["rule_id"]: row for row in csv.DictReader(handle, delimiter="\t")}


def build(root: Path, existing: dict[str, dict[str, str]]) -> list[dict[str, str]]:
    rows = hook_rows(root) + skill_rows(root)
    seen: dict[str, str] = {}
    for row in rows:
        key = f'{row["kind"]}:{row["rule_id"]}'
        if key in seen:
            raise SystemExit(f"duplicate rule id {key}: {seen[key]} and {row['source']}")
        seen[key] = row["source"]
        kept = existing.get(row["rule_id"], {})
        for column in REVIEW:
            row[column] = kept.get(column, "")
    return rows


def render(rows: list[dict[str, str]]) -> str:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=COLUMNS, delimiter="\t", lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, epilog=USAGE)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--check", action="store_true", help="exit 1 when the file on disk is stale")
    args = parser.parse_args(argv)
    root = args.root.resolve()
    out = (root / DEFAULT_OUT) if args.out is None else args.out
    existing = read_existing(out)
    rows = build(root, existing)
    rendered = render(rows)
    hooks = sum(1 for row in rows if row["kind"] == "hook")
    skills = len(rows) - hooks
    if args.check:
        current = out.read_text(encoding="utf-8") if out.exists() else ""
        if current != rendered:
            print(f"stale: {out} differs from a fresh inventory ({hooks} hooks, {skills} skills); rerun without --check", file=sys.stderr)
            return 1
        print(f"fresh: {out} ({hooks} hooks, {skills} skills)")
        return 0
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(rendered, encoding="utf-8")
    print(f"wrote {out}: {len(rows)} rows ({hooks} hooks, {skills} skills)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
