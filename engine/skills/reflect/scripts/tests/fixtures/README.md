# Sample conversation fixtures

Portable Claude Code–shaped JSONL sessions for end-to-end `token_audit` tests.
Not real user transcripts — synthetic, but they use the same line layout
(one JSONL line per content block, shared `message.id`, `usage` on every
block) so dedup and thrash detectors see real shapes.

| File | Story | Expected cost-audit signal |
|---|---|---|
| `clean_efficient_session.jsonl` | Read+Edit in one turn → `pytest` → done. High cache-read share. | All five flags `no` |
| `token_thrash_session.jsonl` | Cache spike, lookup-only turns, identical-window re-read, same error 3×, 4 edits with no verify. | All five flags `yes` |
| `lookup_heavy_session.jsonl` | Only Grep/Glob/Read turns with large output. | `model-tier-candidates` `yes` with a positive $ backtest in the rationale; other thrash flags `no` |
| `restated_rule/fires.jsonl` | A rejected tool call, the person's restatement after it, then a restated existing rule. | `intervention-must-automate` `yes` under `--judge` |
| `restated_rule/silent.jsonl` | The same restatement text only in a tool_result, a skill injection, a subagent prompt, and a rejection with no human reply. | `intervention-must-automate` `no` under `--judge`, `unchecked` without it |

Regenerate after changing detector thresholds:

```
python3 skills/reflect/scripts/tests/fixtures/generate_sample_conversations.py
```
