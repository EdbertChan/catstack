#!/usr/bin/env python3
from __future__ import annotations

import entrypoint


def main() -> None:
    entrypoint.run(
        "claude",
        "UserPromptSubmit",
        "llm-judge: could not read the UserPromptSubmit payload",
    )


if __name__ == "__main__":
    main()
