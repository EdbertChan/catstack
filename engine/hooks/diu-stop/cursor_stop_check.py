#!/usr/bin/env python3
"""Cursor stop hook entrypoint for diu-stop."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from claude_stop_check import detect as detect_diu_stop  # noqa: E402
from runtime import run_hook  # noqa: E402


def detect(event):
    if "last_assistant_message" not in event:
        for key in ("lastAssistantMessage", "last-assistant-message", "assistant_message", "response"):
            value = event.get(key)
            if isinstance(value, str):
                event = dict(event)
                event["last_assistant_message"] = value
                break
    return detect_diu_stop(event)


def main():
    run_hook("diu-stop", "cursor", detect, "stop")


if __name__ == "__main__":
    main()
