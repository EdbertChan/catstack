`disable-model-invocation: true` means the model never reads this
skill's `description:` to decide whether to apply it — that text isn't
even loaded into context. The only way this skill activates is an
explicit `/principle-assert-invariants-not-last-bug` invocation.

A code-review bot flagged a duplicate row for ticker "AUR" in the
holdings table. The fix ships as `if ticker == "AUR": dedupe()`. Two
weeks later the same duplicate-row bug appears for ticker "SERV" and
sails through review because the fix only patched the AUR case. During
the `/reflect` session that follows, the flow explicitly invokes
`/principle-assert-invariants-not-last-bug` to load the full principle
before writing the real fix.

This skill fires here specifically because of that explicit invocation
— the commit message reading like "fix dedupe for AUR" is exactly the
pattern the skill targets once loaded, but no amount of matching prose
alone would have triggered it.
