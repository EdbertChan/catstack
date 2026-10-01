from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[4] / "scripts" / "install" / "mirror_stop_hooks_to_subagent_stop.py"
SPEC = importlib.util.spec_from_file_location("mirror_stop_hooks_to_subagent_stop", SCRIPT)
mirror_stop_hooks = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = mirror_stop_hooks
assert SPEC.loader is not None
SPEC.loader.exec_module(mirror_stop_hooks)


class SubagentStopMirrorDispatcher(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.hooks_dir = Path(self.tmp.name) / "hooks"

    def _manifest(self, name: str, script: str, subagent_stop: dict | None = None) -> None:
        hook_dir = self.hooks_dir / name
        hook_dir.mkdir(parents=True)
        manifest = {
            "hooks": {
                "Stop": [
                    {
                        "matcher": "*",
                        "hooks": [
                            {
                                "type": "command",
                                "command": f"python3 $HOME/.claude/hooks/{name}/{script}",
                                "timeout": 10,
                            }
                        ],
                    }
                ]
            }
        }
        if subagent_stop is not None:
            manifest["subagent_stop"] = subagent_stop
        (hook_dir / "claude.hook.json").write_text(json.dumps(manifest), encoding="utf-8")

    def test_dispatch_opted_hooks_are_grouped_while_non_opted_hooks_stay_direct(self):
        self._manifest("fixture-dispatched", "stop.py", {"dispatch": True})
        self._manifest("fixture-direct", "direct.py")
        self._manifest("fixture-opt-out", "out.py", {"inherit": False, "reason": "fixture"})
        manifests = mirror_stop_hooks.load_manifests(
            str(self.hooks_dir),
            active_hooks={"fixture-dispatched", "fixture-direct", "fixture-opt-out"},
        )
        settings = {
            "hooks": {
                "SubagentStop": [
                    {
                        "hooks": [
                            {
                                "type": "command",
                                "command": "python3 $HOME/.claude/hooks/_runner/dispatch.py --event SubagentStop --timeout 9.5",
                                "timeout": 10,
                            }
                        ]
                    },
                    {
                        "hooks": [
                            {
                                "type": "command",
                                "command": "python3 $HOME/.claude/hooks/fixture-opt-out/out.py",
                                "timeout": 10,
                            }
                        ]
                    },
                    {
                        "hooks": [
                            {
                                "type": "command",
                                "command": "python3 $HOME/bin/foreign.py",
                                "timeout": 10,
                            }
                        ]
                    },
                ]
            }
        }

        updated, changed = mirror_stop_hooks.mirror(settings, manifests)

        self.assertTrue(changed)
        entries = updated["hooks"]["SubagentStop"]
        serialized = json.dumps(entries, sort_keys=True)
        self.assertIn("fixture-direct/direct.py", serialized)
        self.assertIn("_runner/dispatch.py --event SubagentStop --timeout 9.5", serialized)
        self.assertIn("$HOME/bin/foreign.py", serialized)
        self.assertNotIn("fixture-dispatched/stop.py", serialized)
        self.assertNotIn("fixture-opt-out/out.py", serialized)
        self.assertEqual(serialized.count("_runner/dispatch.py"), 1)

        again, changed_again = mirror_stop_hooks.mirror(updated, manifests)
        self.assertFalse(changed_again)
        self.assertEqual(again, updated)


if __name__ == "__main__":
    unittest.main()
