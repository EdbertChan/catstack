#!/usr/bin/env python3
from __future__ import annotations

import entrypoint


def main() -> None:
    entrypoint.run(
        "codex",
        "PostToolUse",
        "llm-judge: Codex PostToolUse could not read payload",
    )


if __name__ == "__main__":
    main()
