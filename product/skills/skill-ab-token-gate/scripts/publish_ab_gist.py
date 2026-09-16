#!/usr/bin/env python3
"""Create or update a GitHub gist for an A/B token-gate out dir."""
from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path


def run(cmd: list[str]) -> str:
    proc = subprocess.run(cmd, check=True, capture_output=True, text=True)
    return proc.stdout.strip()


def collect_files(out_dir: Path) -> list[Path]:
    names = ["REPORT.md", "aggregate.json", "registry.json"]
    files = [out_dir / n for n in names if (out_dir / n).exists()]
    files.extend(sorted(out_dir.glob("session-*.jsonl")))
    files.extend(sorted(out_dir.glob("pr-*.diff")))
    return files


def gist_filenames(gist_id: str) -> set[str]:
    meta = json.loads(run(["gh", "api", f"gists/{gist_id}"]))
    return set((meta.get("files") or {}).keys())


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--gist-id", default="")
    parser.add_argument("--desc", default="skill A/B token gate report")
    parser.add_argument("--public", action="store_true", default=True)
    args = parser.parse_args()
    files = collect_files(args.out)
    if not files:
        raise SystemExit(f"no publishable files under {args.out}")

    if args.gist_id:
        existing = gist_filenames(args.gist_id)
        for path in files:
            if path.name in existing:
                run(["gh", "gist", "edit", args.gist_id, "--filename", path.name, str(path)])
            else:
                run(["gh", "gist", "edit", args.gist_id, "--add", str(path)])
        meta = json.loads(run(["gh", "api", f"gists/{args.gist_id}"]))
        url = meta.get("html_url") or f"https://gist.github.com/{args.gist_id}"
    else:
        cmd = ["gh", "gist", "create", "--desc", args.desc]
        if args.public:
            cmd.append("--public")
        cmd.extend(str(p) for p in files)
        url = run(cmd)
        args.gist_id = url.rstrip("/").split("/")[-1]

    (args.out / "gist-meta.json").write_text(
        json.dumps({"gist_id": args.gist_id, "html_url": url}, indent=2) + "\n"
    )
    print(url)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
