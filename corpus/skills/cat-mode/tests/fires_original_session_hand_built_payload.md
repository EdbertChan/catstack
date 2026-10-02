`disable-model-invocation: true` means the model never reads this
skill's `description:` to decide whether to apply it. cat-mode applies
only when the `CATSTACK_CAT_MODE_DEFAULT=on` hook fires, or on an
explicit `/cat-mode` invocation. Here the hook is on.

The agent is fixing a hook miss. It claims the fix is done after calling
the inner detect function on three hand-built payloads and running a
green unit suite. It never replays the original session or rollout
through the harness entrypoint that missed.

This rule fires. Hand-built detector payloads and nearby shapes are not
the original session. Evidence must include the session or a session
fixture extracted from it, exercised on the harness entrypoint that
missed — not only detect. Claim fixed only after that product-path replay.
