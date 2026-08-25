# Multi-conversation / corpus scan

Read this when running reflect in multi-conversation mode (step 1, corpus path).

## When

The user asks *why does X keep happening* across a span of time or across machines — e.g. "why do these PRs keep thrashing," "look at all our conversations from the last day," "check every DO worker." A repeated-failure pattern's signature often only shows up in the *shape* of many transcripts (a burst of sessions across several machines within minutes of each other), which no single transcript can reveal on its own.

## Command

Use `skills/reflect/scripts/corpus_scan.py <keyword-regex> --hours N` — the tool version of the manual "find matching files, grep them, run token_audit, bucket by time" process, built after doing that by hand once revealed two costly failure modes worth never repeating: a Python regex with unbounded quantifiers (`.{0,80}...`) run against a whole multi-MB transcript read into one string can peg a CPU core for 15+ minutes with zero observable progress (use `grep -c`, not `re.findall`, for keyword/signal counting — see the script's own docstring), and piping a long driver through `| tail -N` (no `-f`) hides all progress until the process exits, making a slow-but-fine run indistinguishable from a hung one.

Local-only is the default and needs no confirmation:

```
python3 skills/reflect/scripts/corpus_scan.py "e2e|playwright|ci-regression" --hours 24
```

It writes a structured JSON (one row per matched session: host, kind, timestamps, tool-error counts, and configurable keyword-signal counts) plus a stdout summary bucketed by host × 15-minute window — that bucketing is where a **dispatch-burst pattern** (several machines starting near-identical sessions within the same few minutes, the actual fingerprint of retry/dedup-gap churn, as opposed to independently-occurring flakiness) becomes visible at a glance instead of buried in a hundred-plus rows.

Local discovery covers Claude (`~/.claude/projects`), Codex (`~/.codex/sessions/rollout-*.jsonl`), and Cursor (`~/.cursor/projects/*/agent-transcripts/*/*.jsonl`). Cursor rows have no `total_tokens` — rank them on thrash / keyword signals, not cost.

## Remote scan

To also cover the DigitalOcean/SSH remote targets in `~/.invoker/config.json`, add `--include-remote all` (or a comma-separated subset). Without `--confirm-remote-scan` it only *prints* the exact `ssh`/`find`/`grep` command it would run per target and exits — this is deliberate and matches this skill's remote-scan policy: a confirmation to scan remote hosts, given before the exact command exists, authorizes the *scope*, not the *payload*, so show the printed command to the user once before re-running with `--confirm-remote-scan`. The remote command is read-only (`find` + `grep -l`, nothing destructive, nothing that writes on the remote host) and pulls only files that already matched the keyword, via `scp`, into `--pull-dir` (default `/tmp/reflect-corpus-pull`) for local auditing — nothing is left running on the remote host afterward.

Feed `corpus_scan.py`'s output JSON to the same lens fan-out in step 3 in place of a single transcript path — give each reviewer the aggregate JSON (not 100+ raw transcripts) plus the specific file paths for anything they want to read in full. Whole-file grep of `again` / `I said` / `try again` is not an intervention signal — those match tool results, `/loop` polls, and source documents. Score **human** messages via `token_audit.py` (`frustration-signals`, `intervention-must-automate`); `DEFAULT_SIGNALS` includes a tight `agent_blame` pattern (`you fucked up|messed up|broke`, `I told you`, `you're ignoring`) for triage only.

## Tests

`skills/reflect/scripts/tests/test_corpus_scan.py` locks down that `remote_scan_command`'s printed output is byte-for-byte what would actually execute (the "show the exact command" transparency guarantee), that it's read-only (no write/exfil commands, no `>` redirect besides `2>/dev/null`), and that `bucket_summary` correctly flags a same-window multi-host burst. Run with `python3 -m unittest discover -s skills/reflect/scripts/tests -v`.
