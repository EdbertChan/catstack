#!/bin/bash
cat > build.py <<'PY'
def build(rows, lots):
    for row in rows:
        t = row["ticker"]
        if not lots[t]:
            continue
        yield lots[t][0]
PY
