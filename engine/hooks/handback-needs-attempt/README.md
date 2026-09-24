# handback-needs-attempt

This advisory Stop hook asks the shared `llm-judge` to inspect an assistant reply and the current exchange. It fires when the reply hands a command or step back to the user without an attempt in the turn. It stays silent after a permission, sandbox, classifier, or tool refusal, and for human-only actions such as passwords, OAuth consent, or hardware interaction.

The hook never blocks the live reply. A judge hit is delivered on the next turn with a request to attempt the step first or name the concrete human-only boundary. An unreadable transcript or failed judge is `unchecked` and is not treated as clean. `stop_hook_active` is an escape hatch for the Stop retry.

The meaning is defined in `../llm-judge/phrases/handback-needs-attempt.json`; this hook has no prose-matching regex. Run `./install.sh` to install it for Claude, Cursor, and Codex.
