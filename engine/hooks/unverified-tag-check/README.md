# unverified-tag-check

Check each `CAT-UNVERIFIED` excuse in the background and report the result on
the next turn.

The hook fires on a well-formed unverified tag in a finished assistant reply.
It runs from Claude `Stop`, Cursor `stop`, and Codex `notify`.

It stays silent for malformed tags. It stays silent for tags inside fenced code
blocks or inline code. It stays silent when the same claim was already checked
in the same transcript within 2 hours. It ignores anything past the first 3
tags in one reply.

The live reply is never blocked or delayed. The check is handed to
[`llm-judge`](../llm-judge/README.md) in investigate mode, and the verdict is
delivered through the shared inbox on the agent's next step.

On a hit, the agent sees:

```text
unverified-tag-check: checked "<claim>". Tell the user this result in plain words: <report>
```

The `<report>` text is the checker's sentence about whether the blocker held,
what the claim turned out to be, and the evidence it could read.

Fail open. If the reply cannot be read, the transcript is missing, or the judge
breaks, the hook hands off nothing or the inbox reports the verdict as
unchecked. It never treats that path as true.

The checker is read-only. It only gets Read, Grep, and Glob, so it cannot run
shell or network checks. When files cannot answer the question, it says
unknown.

## Tests

```sh
python3 -m unittest discover -s engine/hooks/unverified-tag-check/tests -v
```
