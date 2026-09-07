#!/bin/bash
cat > build.py <<'PY'
def build(rows, lots):
    for row in rows:
        t = row["ticker"]
        if not lots[t]:
            yield {"ticker": t, "status": "unmatched", "reason": "no cost lot"}
            continue
        yield lots[t][0]
PY
cat > notes.txt <<'TXT'
if not lots: continue
except: pass
TXT
