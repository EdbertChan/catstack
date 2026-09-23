#!/usr/bin/env python3
"""Scripts moved into scripts/{ci,install,pr,test}/ left a symlink at the old
path. A script that finds the repo from its own path must follow that link,
or the old path computes the wrong root and fails (Invoker plans still call
scripts/check_rules_are_wired.py and got "engine/hooks not found").
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

UNRESOLVED_PY = re.compile(r"os\.path\.(abspath|dirname)\(__file__\)")
UNRESOLVED_SH = re.compile(r'dirname "\$(0|\{BASH_SOURCE\[0\]\})"')


def linked_scripts() -> list[tuple[Path, Path]]:
    pairs = []
    for root, dirs, files in os.walk(REPO):
        dirs[:] = [d for d in dirs if d not in {".git", "node_modules"}]
        for name in files:
            link = Path(root) / name
            if link.is_symlink() and link.suffix in {".py", ".sh"}:
                pairs.append((link, link.resolve()))
    return pairs


class MovedScriptLinksResolve(unittest.TestCase):
    def test_links_exist_so_the_scan_is_not_vacuous(self):
        self.assertGreater(len(linked_scripts()), 10)

    def test_no_linked_script_locates_itself_without_following_the_link(self):
        offenders = []
        for link, target in linked_scripts():
            text = target.read_text(encoding="utf-8")
            pattern = UNRESOLVED_PY if target.suffix == ".py" else UNRESOLVED_SH
            for number, line in enumerate(text.splitlines(), 1):
                if pattern.search(line):
                    offenders.append(f"{target.relative_to(REPO)}:{number} (linked from {link.relative_to(REPO)})")
        self.assertEqual(offenders, [])

    def test_hit_old_path_rules_checker_finds_the_hooks_folder(self):
        result = subprocess.run(
            [sys.executable, str(REPO / "scripts" / "check_rules_are_wired.py")],
            cwd=REPO, capture_output=True, text=True, timeout=120,
        )
        self.assertNotIn("No such file or directory", result.stderr)
        self.assertEqual(result.returncode, 0, result.stderr[-2000:])

    def test_old_path_comment_checker_imports_its_detector(self):
        result = subprocess.run(
            [sys.executable, str(REPO / "scripts" / "check_no_new_comments.py"), "--help"],
            cwd=REPO, capture_output=True, text=True, timeout=120,
        )
        self.assertNotIn("ModuleNotFoundError", result.stderr)


if __name__ == "__main__":
    unittest.main()
