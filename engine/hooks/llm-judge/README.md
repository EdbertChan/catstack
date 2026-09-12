# llm-judge

A shared model judge for catstack hooks. A hook asks a small model a yes/no
style question instead of matching a regex, so new phrasings of the same
meaning still get caught. The model call always runs in the background, so a
hook never waits on it and the reply is never delayed.

No hook asks the judge a question yet. The inbox below already delivers any
verdict that lands, so a hook that starts calling `enqueue` is heard at once.

Standard library only. Works the same under Claude, Codex, and Cursor hooks,
because it shells out to whichever model CLI is installed.

## How a hook uses it

1. On one event, the hook builds a job and calls `judge.enqueue(job)`. It
   returns the job id at once. A detached `python3 judge.py run <job>` process
   does the model call.
2. On a later event for the same transcript, the hook calls
   `judge.drain(transcript)`. It gets back every finished verdict for that
   transcript, oldest first, and those verdict files are deleted.

A job looks like this:

```json
{
  "id": "unique-file-safe-id",
  "hook": "wrong-check-reflect",
  "transcript": "/path/to/transcript.jsonl",
  "prompt": "Reply with one line of JSON: {\"retracts\": true|false}. Text: ...",
  "hit_if_all_true": ["retracts"],
  "on_hit": "message the hook shows when the verdict is a hit"
}
```

If `id` is missing, `enqueue` makes one. An id with a `/` or a leading `.` is
refused with `ValueError`.

The prompt must ask for a single-line JSON object. The judge reads the model's
stdout line by line and keeps the last line that parses as a JSON object. A
JSON object spread over several lines is not read.

The prompt is passed as one command-line argument, so very large prompts
(over about 128 KB on Linux) fail for every runner and come back `unchecked`.

## Phrase dictionaries

A checker whose condition is a prose meaning can declare that meaning as a
JSON dictionary in `engine/hooks/llm-judge/phrases/<checker>.json`. The file is
one JSON object with these keys:

| Key | Meaning |
| --- | --- |
| `checker` | String equal to the file stem. |
| `meaning` | One sentence naming the meaning the checker is looking for. |
| `reads` | One of `reply`, `user`, or `exchange`, naming the text the checker reads. |
| `match` | Non-empty array of phrases that should count as the meaning. |
| `not_match` | Array of phrases that should not count, including harmless, quoted, or negated examples. |
| `on_hit` | Text shown to the agent when the verdict is a hit. |

`phrases.load(checker, directory=None)` reads and validates the dictionary from
the default `phrases/` directory, or from `directory` when tests pass one in.
Malformed dictionaries raise `ValueError` with the file path and bad key.

`phrases.prompt(dictionary, text)` renders the dictionary and the text into the
single-line JSON prompt shape that llm-judge expects. It includes the meaning,
every `match` phrase, every `not_match` phrase, and the text to judge.

`phrases.job(dictionary, transcript, text)` builds the dormant llm-judge job:
it uses the dictionary's checker name as `hook`, includes the transcript path,
asks for `match`, sets `hit_if_all_true` to `["match"]`, and carries through
the dictionary's `on_hit` text.

## Runner order

`ask(prompt)` tries these in order and stops at the first one that answers:

1. **codex**: `codex exec --skip-git-repo-check -m gpt-5.3-codex-spark --sandbox read-only -c notify=[] PROMPT`
2. **claude**: `claude -p --model haiku --settings '{"disableAllHooks": true}' PROMPT`
3. **cursor**: `cursor-agent -p --output-format text PROMPT`

Each runner gets 60 seconds, no stdin, a fresh empty temp directory as its
working directory, and the current environment plus
`CATSTACK_LLM_JUDGE_CHILD=1`. On timeout the runner's whole process group is
killed.

A runner fails, and the next one is tried, when its binary is not on `PATH`
(reason `not installed`), it exits non-zero, it times out, or no stdout line
parses as a JSON object. Each try is recorded in `attempts` with a reason of at
most 300 characters, taken from the end of stderr or the error text.

`CATSTACK_LLM_JUDGE_RUNNERS` replaces the three runners. It is a JSON list of
`[name, argv]` pairs, and any argv item equal to `{prompt}` becomes the prompt.
Tests use it to plug in small fake runners. If it is set but not that shape,
`ask` raises `ValueError` instead of quietly falling back to the real runners.

## Three outcomes

`verdict(job, result)` turns an `ask` result into one of:

- **hit**: a runner answered, and every key in `hit_if_all_true` is JSON `true`
  in the answer. The string `"true"` does not count. An empty
  `hit_if_all_true` list is a hit whenever a runner answers.
- **clean**: a runner answered, and at least one of those keys is false,
  missing, or not a real `true`.
- **unchecked**: no runner answered, or the judge itself broke. This is never
  treated as clean. The `reason` field says why, for example
  `codex: not installed; claude: exit 1: ...`.

A verdict carries `id`, `hook`, `transcript`, `outcome`, `on_hit`, `reason`,
`runner`, `answer`, `attempts`, and `finished_at`.

## Recursion guard

Every runner is started with `CATSTACK_LLM_JUDGE_CHILD=1`. The model CLIs run
their own hooks, and those hooks may call `enqueue` too. When that variable is
set, `enqueue` returns `None` and does nothing, so a judge never starts another
judge. The claude runner also turns off all its hooks with
`disableAllHooks`.

## State layout

The state root is `CATSTACK_LLM_JUDGE_STATE_DIR`, or
`~/.cache/catstack-llm-judge` when that is unset.

```
<state>/
  judge.log                         background output and every judge error, with the job id
  jobs/<id>.json                    waiting or running jobs; deleted once the verdict is written
  verdicts/<hash>/<id>.json         finished verdicts; <hash> is the first 16 hex of sha1(transcript path)
```

Verdicts are written to a temp file and then renamed into place, so `drain`
never reads half a file. `drain` claims each file by renaming it before reading
it, so two drains running at once never return the same verdict. If a job
crashes (bad job file, bad runner config, anything else), the error goes to
`judge.log` and an `unchecked` verdict with that reason is still written. A
verdict file that cannot be read comes back from `drain` as `unchecked`.

## Delivery: the inbox

A verdict finishes after the reply that caused it. So it is shown to the agent
at the start of its next turn, never in the same turn. Waiting for it would
hold up the reply.

`inbox.messages(transcript)` drains that transcript's verdicts and turns each
one into a line of text:

- **hit**: the job's `on_hit` text, word for word.
- **unchecked**: `llm-judge: <hook> could not judge the last reply: ` then
  `<runner>: <reason>` for each try, joined by `; `. If there were no tries
  (the judge broke, or the verdict file was unreadable), the verdict's own
  `reason` is used instead.
- **clean**: nothing.

Each verdict is delivered once. Draining deletes it.

One small script per harness calls it:

| Harness | Script | Event | How the text reaches the agent |
| --- | --- | --- | --- |
| Claude | `claude_prompt_submit.py` | `UserPromptSubmit` | `hookSpecificOutput.additionalContext` |
| Cursor | `cursor_session.py` | `stop` | `followup_message` |
| Codex | `codex_notify.py` | `notify` (`agent-turn-complete`) | text on stderr, then chains to the prior notify command |

Claude uses the payload's `transcript_path` as is. Cursor and Codex find the
transcript the same way `wrong-check-reflect` does: `agent_transcript_path`,
`transcript_path`, or `transcriptPath` if that file exists, else the Cursor
transcript for `conversation_id`. If no transcript is found, the script says so
on stderr and drains nothing, because draining without a transcript would read
some other session's verdicts. A payload that cannot be parsed, or a drain that
fails, is also written to stderr with the reason. Every script exits 0, so the
inbox never blocks a prompt or a reply.

`./install.sh` links this folder into `~/.claude/hooks/`, `~/.cursor/hooks/`,
and `~/.codex/hooks/`, then runs `install_claude_hook.py`,
`install_cursor_hook.py`, and `install_codex_notify.py`. Each one is safe to
rerun and replaces only its own entry.

## Tests

```
python3 -m unittest discover -s engine/hooks/llm-judge/tests -v
```
