#!/usr/bin/env python3
from __future__ import annotations

import entrypoint


def main() -> None:
    entrypoint.run(
        "claude",
        "PostToolUse",
        "llm-judge: Claude PostToolUse could not read payload",
    )


if __name__ == "__main__":
    main()
