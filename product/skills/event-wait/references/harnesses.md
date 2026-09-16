# Harness ownership recipes

Installation in three skill roots is not a live wake test. For each harness,
record source_ready, callback_ready, event_received, and a resumed parent result
before calling its live path tested. The callback socket contract is in
[specification.md](specification.md); adapters must obtain real registration acknowledgment.
Do not enable global hooks, install a relay, send external messages or mutate a
producer to obtain this evidence.

## Codex tool-level completion

The [official subagent documentation](https://developers.openai.com/codex/multi-agent)
describes collecting child results. In a tool harness that explicitly delivers
child final notifications, delegate a bounded listener task only when delegation
is authorized. The child starts **and awaits** its listener subprocess using its
own process handle; it returns the sanitized terminal receipt to the parent.
The parent records ack-wake only after receiving that child result. Native mode
lets the child finish without waiting for that post-completion acknowledgment.

A process created by the parent cannot be assumed consumable by the child:
`Unknown process id` is an ownership failure, not a reason to poll. Do not invent
`notify_on_output` options for a public CLI or a tool schema that lacks them.
A terminal notification or shell exit is not an automatic chat turn. The recipe
is conditional on the current tool's documented completion delivery; otherwise
report session_wake_unsupported. This does not advertise public CLI idle wake.

## Claude running-session integration

[Claude's hook reference](https://code.claude.com/docs/en/hooks) documents
`asyncRewake: true`: exit code 2 wakes the running session. The hook timeout is
enforced. Ordinary `async: true` defers output to the next turn; it does not wake
an idle session. Noninteractive session teardown can cancel outstanding hooks.

If an authorized, session-local adapter already exists, set its timeout longer
than the runner's finite deadline. The adapter registers native callback readiness,
starts and awaits the listener, and emits a bounded sanitized completion reminder
with exit 2 **for wake signaling**, including when the listener observed success.
The listener's exit status and target_outcome remain separate fields; do not
interpret that wrapper's 2 as target failure. After actual resume, the parent
records ack-wake. Do not fabricate callback_ready from configuration alone.
This package does not install hooks or claim this recipe has been exercised in
Claude. No supported running-session registration means session_wake_unsupported.

## Cursor local SDK

[Cursor's Python SDK](https://cursor.com/docs/sdk/python#background-subagents)
documents local background-subagent results as follow-up turns on the same run.
The SDK owner's run.messages() iterator includes those turns; run.wait() completes
after them. Scope the recipe to SDK-owned **local** runs, not arbitrary IDE tabs or
cloud runs. A delegated child owns its process and await handle, registers the
callback, and returns its receipt. The SDK parent acknowledges actual follow-up
delivery, then records ack-wake. Without that owning run and documented background
mechanism, report session_wake_unsupported. This package does not start SDK agents
or claim a Cursor live test.

## Evidence boundaries

A fake socket server replying callback_ready/wake_delivered tests the protocol
only. Readiness is a bridge attestation, not authentication or proof of resume.
A genuine live test needs a synthetic source, the actual owning harness's native
completion, a parent that waits idle, and that parent's acknowledgment/result.
Never substitute live CI for synthetic-source success. CI provider access is a
separate prerequisite, even when the harness path has been exercised.
