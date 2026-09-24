#!/usr/bin/env python3
"""Scripts moved into scripts/{ci,install,pr,test}/ left a symlink at the old
path. A script that finds the repo from its own path must follow that link,
or the old path computes the wrong root and fails (Invoker plans still call
scripts/check_rules_are_wired.py and got "engine/hooks not found").
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
TOOLCHAIN = REPO / "scripts" / "test" / "ensure_node_toolchain.sh"
BASH = shutil.which("bash") or "/bin/bash"

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


def _repo_reached_through_a_link(tmp: Path) -> tuple[Path, Path]:
    """A repo holding the script at its new path plus a link at the old one."""
    root = tmp / "repo"
    (root / "scripts" / "test").mkdir(parents=True)
    new_path = root / "scripts" / "test" / "ensure_node_toolchain.sh"
    new_path.write_text(TOOLCHAIN.read_text(encoding="utf-8"), encoding="utf-8")
    old_path = root / "scripts" / "ensure_node_toolchain.sh"
    old_path.symlink_to(Path("test") / "ensure_node_toolchain.sh")
    (root / "package.json").write_text('{"name":"x"}\n', encoding="utf-8")
    (root / "node_modules").mkdir()
    return old_path, new_path


def _path_without_realpath(tmp: Path) -> str:
    """Only dirname, the one external command the script needed before."""
    bindir = tmp / "no-realpath-bin"
    bindir.mkdir()
    (bindir / "dirname").symlink_to(shutil.which("dirname") or "/usr/bin/dirname")
    return str(bindir)


def _run(script: Path, path_env: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [BASH, str(script)],
        capture_output=True, text=True, timeout=120,
        env=dict(os.environ, PATH=path_env),
    )


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

    def test_the_old_path_link_reaches_the_same_repo_as_the_new_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            old_path, _ = _repo_reached_through_a_link(Path(tmp))
            result = _run(old_path, os.environ.get("PATH", "/usr/bin:/bin"))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("already installed", result.stdout)

    def test_the_new_path_needs_no_resolver_on_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, new_path = _repo_reached_through_a_link(Path(tmp))
            result = _run(new_path, _path_without_realpath(Path(tmp)))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("already installed", result.stdout)

    def test_a_link_it_cannot_follow_is_refused_not_silently_mislocated(self):
        with tempfile.TemporaryDirectory() as tmp:
            old_path, _ = _repo_reached_through_a_link(Path(tmp))
            result = _run(old_path, _path_without_realpath(Path(tmp)))
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("realpath is not on PATH", result.stderr)
        self.assertNotIn("no package.json here", result.stdout)


if __name__ == "__main__":
    unittest.main()
