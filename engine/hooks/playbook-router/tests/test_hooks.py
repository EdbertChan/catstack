from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

HOOK_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = HOOK_DIR.parents[2]
FIXTURES = Path(__file__).parent / "fixtures"
PROCEDURE = "# Repair widget\n\n## Steps\n\n1. Observe the widget.\n2. Repair the widget.\n"


class RouterCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name) / "home"
        self.repo = Path(self.tmp.name) / "repo"
        self.home.mkdir()
        (self.repo / ".git").mkdir(parents=True)

    def write(self, path, content):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def run_hook(self, payload):
        result = subprocess.run(
            [sys.executable, str(HOOK_DIR / "claude_prompt_submit.py")],
            input=payload if isinstance(payload, str) else json.dumps(payload),
            text=True,
            capture_output=True,
            env={**os.environ, "HOME": str(self.home)},
            cwd=self.repo,
            timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, "")
        if not result.stdout:
            return None
        output = json.loads(result.stdout)
        self.assertEqual(set(output), {"hookSpecificOutput"})
        hook = output["hookSpecificOutput"]
        self.assertEqual(hook["hookEventName"], "UserPromptSubmit")
        self.assertEqual(set(hook), {"hookEventName", "additionalContext"})
        return hook["additionalContext"]

    def fixture(self, name):
        fixture = json.loads((FIXTURES / name).read_text())
        source = REPO_ROOT / fixture["skill"]
        self.write(self.home / ".claude/skills" / source.parent.name / "SKILL.md", source.read_text())
        context = self.run_hook(fixture["payload"])
        return fixture, context

    def test_fires_land_stack_fixture_with_ordered_steps(self):
        fixture, context = self.fixture("fires_land_stack.json")
        self.assertIsNotNone(context)
        positions = [context.index(step) for step in fixture["expect_steps"]]
        self.assertEqual(positions, sorted(positions))
        self.assertIn("Never discover by branch name.", context)
        self.assertIn("python3 scripts/verify_stack.py", context)

    def test_silent_unrelated_fixture(self):
        _, context = self.fixture("silent_unrelated.json")
        self.assertIsNone(context)

    def test_detects_new_file_without_registration(self):
        payload = {"prompt": "repair widget"}
        self.assertIsNone(self.run_hook(payload))
        self.write(self.repo / "playbooks/repair-widget.md", PROCEDURE)
        self.assertIn("1. Observe the widget.\n2. Repair the widget.", self.run_hook(payload))

    def test_detects_source_skill_from_nested_cwd(self):
        nested = self.repo / "nested/dir"
        nested.mkdir(parents=True)
        for layer in ("engine", "corpus", "product", ".claude"):
            source = self.write(self.repo / layer / "skills/repair-widget/SKILL.md", PROCEDURE)
            self.assertIn("Repair the widget.", self.run_hook({"prompt": "/repair-widget", "cwd": str(nested)}))
            source.unlink()

    def test_silent_for_nested_reference_playbooks(self):
        fixture = json.loads((FIXTURES / "silent_reference_playbooks.json").read_text())
        sources = list((REPO_ROOT / fixture["directory"]).glob("*.md"))
        self.assertEqual(len(sources), 2)
        for source in sources:
            self.write(self.home / ".claude/skills/split-scope/playbooks" / source.name, source.read_text())
            self.assertIsNone(self.run_hook({"prompt": "run " + source.stem}))
        self.write(self.home / ".claude/skills/split-scope/playbooks/repair-widget.md", PROCEDURE)
        self.assertIsNone(self.run_hook({"prompt": "repair widget"}))

    def test_silent_for_mentions_negation_partial_names_and_paths(self):
        self.write(self.repo / "playbooks/repair-widget.md", PROCEDURE)
        for prompt in (
            "Do not repair widget", "Explain repair-widget", "repair something",
            "widget repair", "repair-widget-extra", "/repair-widget-extra",
            "repair-widget.md", "repair-widget/file", "I used repair-widget yesterday",
        ):
            with self.subTest(prompt=prompt):
                self.assertIsNone(self.run_hook({"prompt": prompt}))

    def test_silent_for_ambiguous_names(self):
        self.write(self.repo / "playbooks/repair-widget.md", PROCEDURE)
        self.write(self.home / ".claude/skills/repair-widget/SKILL.md", PROCEDURE + "\nDifferent owner.\n")
        self.assertIsNone(self.run_hook({"prompt": "repair widget"}))

    def test_detects_symlinked_source_only_once(self):
        source = self.write(self.repo / ".claude/skills/repair-widget/SKILL.md", PROCEDURE)
        installed = self.home / ".claude/skills/repair-widget"
        installed.parent.mkdir(parents=True)
        installed.symlink_to(source.parent)
        context = self.run_hook({"prompt": "repair widget"})
        self.assertEqual(context.count("1. Observe the widget."), 1)

    def test_silent_on_missing_or_malformed_procedures(self):
        self.assertIsNone(self.run_hook({"prompt": "repair widget"}))
        path = self.repo / "playbooks/repair-widget.md"
        for content in ("# Reference\n1. Example\n", "## Steps\n- A bullet\n", "## Steps\n1. One\n3. Three\n"):
            self.write(path, content)
            self.assertIsNone(self.run_hook({"prompt": "repair widget"}))
        path.write_bytes(b"\xff")
        self.assertIsNone(self.run_hook({"prompt": "repair widget"}))

    def test_fails_open_on_malformed_payloads(self):
        for payload in ("not json", "[]", "null", "1", {}, {"prompt": 7}, {"cwd": []}):
            with self.subTest(payload=payload):
                self.assertIsNone(self.run_hook(payload))

    def test_detects_steps_with_fenced_headings_and_continuations(self):
        steps = "1. Inspect.\n\n   ```md\n## Example\n1. Example item\n   ```\n\n2. Repair."
        self.write(self.repo / "playbooks/repair-widget.md", "## Steps\n\n" + steps + "\n\n## Notes\nUnrelated notes.\n")
        context = self.run_hook({"prompt": "repair widget"})
        self.assertIn(steps, context)
        self.assertNotIn("Unrelated notes.", context)

    def test_trigger_override_is_optional_and_literal(self):
        self.write(self.repo / "playbooks/repair-widget.md", '---\nplaybook-trigger: "repair the broken widget"\n---\n' + PROCEDURE)
        self.assertIsNone(self.run_hook({"prompt": "repair widget"}))
        self.assertIn("Repair the widget.", self.run_hook({"prompt": "Repair the broken widget now"}))
        self.assertIn("Repair the widget.", self.run_hook({"prompt": "/repair-widget"}))

    def test_silent_for_heading_inside_indented_code(self):
        self.write(self.repo / "playbooks/repair-widget.md", "    ## Steps\n1. This is outside a steps section.\n")
        self.assertIsNone(self.run_hook({"prompt": "repair widget"}))

    def test_detects_indented_heading_boundary(self):
        self.write(self.repo / "playbooks/repair-widget.md", "  ## Steps\n1. Inspect.\n2. Repair.\n  ## Notes\nUnrelated notes.\n")
        context = self.run_hook({"prompt": "repair widget"})
        self.assertIn("1. Inspect.\n2. Repair.", context)
        self.assertNotIn("Unrelated notes.", context)

    def test_malformed_trigger_fails_open(self):
        for trigger in ('"unterminated', "[repair, widget]", "", "repair.*widget"):
            self.write(self.repo / "playbooks/repair-widget.md", "---\nplaybook-trigger: " + trigger + "\n---\n" + PROCEDURE)
            self.assertIsNone(self.run_hook({"prompt": "/repair-widget"}))

    def test_detects_supported_prompt_payload_shapes(self):
        self.write(self.repo / "playbooks/repair-widget.md", PROCEDURE)
        for payload in (
            {key: "repair widget"} for key in ("prompt", "user_prompt", "userPrompt", "message", "text", "content")
        ):
            self.assertIn("Repair the widget.", self.run_hook(payload))
        self.assertIn("Repair the widget.", self.run_hook({"content": [{"type": "text", "text": "repair widget"}]}))

    def test_installer_preserves_settings_and_is_idempotent(self):
        path = self.write(self.home / ".claude/settings.json", json.dumps({
            "model": "existing",
            "hooks": {"UserPromptSubmit": [{"hooks": [{"type": "command", "command": "other-hook"}]}]},
        }))
        installed = []
        for _ in range(2):
            result = subprocess.run(
                [sys.executable, str(HOOK_DIR / "install_claude_hook.py")],
                env={**os.environ, "HOME": str(self.home)}, capture_output=True, text=True, timeout=10,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            installed.append(path.read_text())
        self.assertEqual(installed[0], installed[1])
        settings = json.loads(installed[0])
        self.assertEqual(settings["model"], "existing")
        commands = [hook["command"] for entry in settings["hooks"]["UserPromptSubmit"] for hook in entry["hooks"]]
        self.assertEqual(commands, ["other-hook", "python3 $HOME/.claude/hooks/playbook-router/claude_prompt_submit.py"])


if __name__ == "__main__":
    unittest.main()
