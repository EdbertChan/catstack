#!/usr/bin/env python3
"""Claude Code PreToolUse (Agent) entrypoint for cat-mode-default.

Renders differently from the shared SDK shape: a fired finding here replaces
the whole tool_input via `hookSpecificOutput.updatedInput` (the finding's
evidence is the JSON-encoded replacement tool_input), not the generic
`additionalContext`. Off, silent, and stop still use the shared renderer, so
a registry override to stop blocks the subagent's tool call the normal way.
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "_sdk"))

from detect import detect  # noqa: E402
from render import render as default_render  # noqa: E402
from runtime import run_hook  # noqa: E402


def _render_agent_prompt(harness, hook_event_name, mode, findings):
    if mode == "off" or mode == "stop" or not findings:
        return default_render(harness, hook_event_name, mode, findings)
    updated_input = json.loads(findings[0].evidence)
    return (
        json.dumps({
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "updatedInput": updated_input,
            }
        }) + "\n",
        "",
        0,
    )


def main() -> None:
    run_hook("cat-mode-default", "claude", detect, "PreToolUse", render_fn=_render_agent_prompt)


if __name__ == "__main__":
    main()
