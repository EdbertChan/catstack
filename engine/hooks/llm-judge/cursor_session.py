#!/usr/bin/env python3
from __future__ import annotations

import entrypoint


def main() -> None:
    entrypoint.run(
        "cursor",
        "stop",
        "llm-judge: could not read the Cursor stop payload",
    )


if __name__ == "__main__":
    main()
