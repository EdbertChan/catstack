---
name: principle-guard-the-context-window
description: "Apply when context is filling up: large outputs, long files, repeated reads, fan-out planning. Route bulk to subagents; keep summaries in the main thread, not raw payloads."
disable-model-invocation: true
---

# Guard the Context Window

The context window is finite and non-renewable within a session. Every token that enters should earn its place.

**Why:** Context overflow degrades reasoning quality, creates compression artifacts, and halts progress. Unlike compute or time, context spent inside a session cannot be reclaimed.

**Pattern:**
- **Isolate large payloads.** Route verbose outputs, screenshots, and large documents to subagents. The main context gets summaries, not raw data.
- **File-then-parse.** Never pipe a large CLI dump (trace JSON, multi-MB transcript, long log) straight into the main thread or through a pipe that the harness truncates (~30KB on Claude Code Bash). Redirect to a file first, then `jq` / read only the fields you need. Prefer extract-fields or a small structured report over fetching the full payload when the tool supports it.
- **Don't read what you won't use.** Read selectively based on relevance. If a file isn't needed for the current task, skip it.
- **Keep frequently used content inline.** Templates and references used on every invocation belong in the skill file, not in separate files that cost a read each time. Progressive disclosure is the inverse: put rarely-needed bulk in `references/` and load it only when that step runs.
- **Size phases and cap scope.** Limit files per phase, set turn budgets, account for mechanism costs.

**Battle-tested, with a concrete threshold:** a 13MB session hit forced compaction after accumulating multiple 250–330KB inline image results in the main thread, with almost no subagent delegation the whole session. The rule as written ("route verbose outputs to subagents") is correct but has no number attached, so it's easy to keep telling yourself "just one more" until compaction forces the issue. Two concrete triggers: a single tool result over roughly 200KB (a screenshot, a video frame, a full-file read) should go to a subagent instead of staying inline; about to view or compare a 3rd image, or re-read the same file a 3rd time, in the main thread — delegate that work and bring back a short text verdict, not the payload.

**Battle-tested #2, cumulative drift without any single large payload:** a corpus retrospective found a session with zero tool errors and zero redundant reads — legitimate work throughout — that still burned 936K tokens of context before its first forced auto-compaction. Only 4 subagent/fork calls occurred across roughly 1700 turns, despite dozens of sequential grep/sed/cat dives into large source files spanning several unrelated worktrees. No single read crossed the 200KB threshold above. The trigger isn't just "is this one payload big" — it's "is unresolved cross-file investigation piling up in this thread." Fork a research subagent before the 3rd or 4th exploratory dive into unfamiliar code, not only before the 3rd oversized read.

**Battle-tested #3, a Skill invocation is a large payload too:** invoking a bundled reference skill for a single narrow fact — "pricing for two models" — loaded 922KB of unrelated per-language documentation into the main thread in one turn (verified against the bundled skill directory's own byte count), immediately followed by a cache-creation jump from ~3K to ~350K tokens. The skill wasn't misused — it just answers a broader class of question than the one actually asked, and there was no smaller reference to reach for instead. When a Skill call is likely to load far more than the question needs, consider whether a fork can answer the narrow question and report back a short verdict, the same way you'd delegate an oversized tool result — the mechanism (a large chunk of text entering the main thread's context) is identical either way. Related, not a rule change: fanning out many parallel `Agent` calls in one turn can independently blow the prompt-cache breakpoint (a ~590K-token context rewritten from scratch two seconds after ten agents launched, no idle gap or bug involved) — that's a real, uncounted cost of large fan-outs worth knowing about, not a reason to avoid them.

## CI log diagnostics

When a CI job log is the large payload, use the helper in this skill package:
`scripts/ci_logs.py`. Read `scripts/ci_logs.py --help` before copying a command
so the invocation matches the installed helper.

The helper has two phases:

1. Capture the full log once into a private local artifact.
2. Ask bounded snippet questions against the artifact handle.

For a GitHub Actions job log, capture the completed job attempt once:

```bash
python3 scripts/ci_logs.py capture github \
  --artifact-root "$artifact_root" \
  --api-url "$api_url" \
  --repo "$repo" \
  --run-id "$run_id" \
  --attempt "$attempt" \
  --job-id "$job_id"
```

For an existing local log, import it instead of reprinting it:

```bash
python3 scripts/ci_logs.py capture local \
  --artifact-root "$artifact_root" \
  --file "$stdout_log" \
  --stderr-file "$stderr_log" \
  --producer-exit-status "$producer_exit_status" \
  --repo "$repo" \
  --run-id "$run_id" \
  --attempt "$attempt" \
  --job-id "$job_id"
```

Then query the returned artifact handle with literal or structural snippets:

```bash
python3 scripts/ci_logs.py snippet \
  --artifact-root "$artifact_root" \
  --handle "$artifact_handle" \
  --pattern "$literal_failure_text" \
  --context 2 \
  --max-matches 5
```

```bash
python3 scripts/ci_logs.py snippet \
  --artifact-root "$artifact_root" \
  --handle "$artifact_handle" \
  --line-start "$line_start" \
  --line-end "$line_end"
```

The complete stdout and stderr logs stay on disk under the artifact root. The
JSON response is capped at 16384 UTF-8 bytes, metadata included. If the response
or an excerpt is shortened, treat that as an evidence limit, not a result: cite
`response_truncated`, `excerpt_truncated`, `omitted_prefix_bytes`,
`omitted_suffix_bytes`, `omitted_match_count`, `byte_start`, `byte_end`, and the
line range when you report what you saw. Always cite the `artifact.handle`, the
source fields (`repo`, `run_id`, `attempt`, `job_id`, or local `path`), and the
`stdout_sha256` when answering from a snippet.

`status: no_match` means the requested pattern was not found in the inspected
stream. It never means the job passed. A missing match, an empty snippet list, an
incomplete artifact, or a truncated excerpt is explicit uncertainty.

The helper preserves producer exit status separately from helper success. A
local import with `--producer-exit-status 17` can still return
`status: complete`; report `artifact.producer_exit_status` instead of implying
the original command exited zero. A failed download or missing local file returns
a nonzero helper exit and an explicit JSON error while preserving whatever log
bytes were captured.

Completed GitHub capture is download-once per `(repo, run_id, attempt, job_id,
api_url)`. Repeating the same capture returns the completed artifact from the
local cache with `cache_hit: true`; incomplete downloads are not cached as
complete.

If the first snippet does not answer the question, ask a fresh read-only
subagent to inspect the artifact instead of pulling the full log into the parent
context. Use a prompt like:

```text
You are a read-only CI-log investigator. Artifact handle: <handle>. Question:
<specific diagnostic question>. Evidence budget: at most <N> snippets and
16384 bytes per helper response. Do not write files or mutate state. Use
scripts/ci_logs.py snippet only. Return only the answer, exact source ranges
with artifact handle/source/hash, supporting excerpts, and explicit uncertainty
for missing matches, omitted bytes, incomplete artifacts, or truncation.
```

The parent receives only the answer and supporting excerpts. Subagent tokens
still count toward total session spend, so delegation reduces parent context
pressure but is not free.

Later dependent slices add runtime guards for recognized shell log fetches.
This recipe only documents helper use; it does not claim arbitrary scripts,
hosted tools, or interactive input are universally covered.
