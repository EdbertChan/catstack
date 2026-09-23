# handback-needs-attempt

This Stop hook asks the shared background judge to flag a reply that hands the user a command or step the agent could have attempted, when the turn shows no attempt and no valid human-only or refusal reason.

It is silent after a permission denial, sandbox or classifier refusal, password or OAuth consent, hardware interaction, or a same-turn attempt. It also returns silently when `stop_hook_active` is set so a rewrite cannot loop.

The next-turn message is:

`handback-needs-attempt: this reply hands you a step the agent did not attempt this turn. Attempt the command first, or name the permission refusal, environment refusal, or human-only step that makes it yours.`

The hook fails open for the live reply: it never blocks the Stop event. A judge failure is reported as `unchecked` by the shared `llm-judge` inbox and is never treated as clean.

There is no bypass for a hand-back that the agent could have attempted. The escape hatch is to attempt the step first or state the concrete refusal or human-only boundary.

Meaning belongs in [`handback-needs-attempt.json`](../llm-judge/phrases/handback-needs-attempt.json). Add real misses or false alarms there; do not add a prose regex to this hook.
