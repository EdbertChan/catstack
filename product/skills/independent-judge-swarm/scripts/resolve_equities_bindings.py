#!/usr/bin/env python3
"""Resolve independent-judge-swarm command bindings from the consumer cwd.

Catstack ships this resolver only. Command paths and argv templates MUST come
from a bindings file in the consumer workspace:

  .cursor/judge-swarm-bindings.json

That file is not part of catstack. If it is missing, fail closed — do not
invent script paths.

Usage:
  python3 resolve_equities_bindings.py --cwd /path/to/consumer \\
    --ticker UBER --sheet-url 'https://...' [--produce] --json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Well-known consumer relative path. The file itself lives in the consumer
# repo, not in catstack.
BINDINGS_REL = Path(".cursor/judge-swarm-bindings.json")


def load_bindings(cwd: Path) -> tuple[dict | None, str | None]:
    path = cwd.resolve() / BINDINGS_REL
    if not path.is_file():
        return None, f"missing consumer bindings: {BINDINGS_REL.as_posix()}"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return None, f"invalid bindings at {BINDINGS_REL.as_posix()}: {exc}"
    if not isinstance(data, dict) or "commands" not in data:
        return None, f"bindings must be an object with a 'commands' key: {BINDINGS_REL.as_posix()}"
    return data, None


def _fill(template: list[str], *, ticker: str, sheet_url: str | None) -> list[str]:
    out: list[str] = []
    for part in template:
        if part == "<RESOLVED>":
            out.append(ticker)
        elif part == "<URL>":
            if sheet_url:
                out.append(sheet_url)
        else:
            out.append(part)
    return out


def resolve(
    cwd: Path,
    *,
    ticker: str,
    sheet_url: str | None = None,
    produce: bool = False,
) -> dict:
    """Return binding dict. On missing bindings/scripts, ok=False and errors[]."""
    root = cwd.resolve()
    errors: list[str] = []
    bindings, err = load_bindings(root)
    if err:
        return {
            "ok": False,
            "cwd": str(root),
            "ticker": None,
            "produce": produce,
            "sheet_url": sheet_url,
            "bindings_path": None,
            "commands": [],
            "errors": [err],
        }

    assert bindings is not None
    commands_spec = bindings.get("commands") or {}
    resolved = ticker.strip().upper()
    if not resolved:
        errors.append("ticker is required")

    commands: list[dict] = []

    def add_command(name: str, required: bool) -> None:
        spec = commands_spec.get(name)
        if not spec:
            if required:
                errors.append(f"bindings.commands.{name} is required")
            return
        rel = spec.get("relative")
        template = spec.get("argv_template")
        if not isinstance(rel, str) or not rel:
            errors.append(f"bindings.commands.{name}.relative must be a non-empty string")
            return
        if not isinstance(template, list) or not all(isinstance(x, str) for x in template):
            errors.append(f"bindings.commands.{name}.argv_template must be a string list")
            return
        if "<URL>" in template and not sheet_url:
            errors.append(f"sheet_url is required for command {name!r}")
            return
        path = root / rel
        if not path.is_file():
            errors.append(f"missing consumer script: {rel}")
            return
        if not resolved:
            return
        commands.append(
            {
                "name": name,
                "relative": rel,
                "path": str(path),
                "argv": _fill(template, ticker=resolved, sheet_url=sheet_url),
            }
        )

    if produce:
        add_command("produce", required=True)
    add_command("grade", required=True)

    bindings_path = root / BINDINGS_REL
    return {
        "ok": not errors,
        "cwd": str(root),
        "ticker": resolved or None,
        "produce": produce,
        "sheet_url": sheet_url,
        "bindings_path": str(bindings_path),
        "commands": commands,
        "errors": errors,
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--cwd", type=Path, default=Path.cwd())
    p.add_argument("--ticker", default="")
    p.add_argument("--sheet-url", default=None)
    p.add_argument("--produce", action="store_true")
    p.add_argument("--json", action="store_true")
    args = p.parse_args(argv)

    result = resolve(
        args.cwd,
        ticker=args.ticker,
        sheet_url=args.sheet_url,
        produce=args.produce,
    )
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        if not result["ok"]:
            for err in result["errors"]:
                print(f"error: {err}", file=sys.stderr)
            return 1
        for cmd in result["commands"]:
            print(" ".join(cmd["argv"]))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
