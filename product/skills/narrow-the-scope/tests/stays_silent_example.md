Session has run for two hours: the user asked for a login page, then
asked to also add password-reset, then asked to add rate-limiting on
top of that — each request confirmed and landed before the next one
arrived, with a passing test run after every change.

No error is recurring, and there's no edit streak on one file without
verification — this is normal collaborative work expanding session
scope by request, not one problem failing to converge. The SKILL.md
explicitly distinguishes this case as `[[principle-scope-the-session]]`'s
territory, a different failure mode, not this skill's.
