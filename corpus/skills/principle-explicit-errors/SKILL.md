---
name: principle-explicit-errors
description: "Apply whenever code catches, suppresses, translates, retries, or otherwise handles an error or exception."
disable-model-invocation: true
---

# Make Errors Explicit

Every error path must make its disposition visible: handle the error, propagate
it, translate it into a named domain result, or suppress only a narrow,
documented exception whose absence is safe and observable when that assumption
changes.

An empty or comments-only exception handler is not an error policy. It hides
failures from callers, logs, tests, and future maintainers. Do not write
`catch {}`, `except: pass`, ignored promise rejections, or equivalent silent
fallbacks. Replace them with an explicit action and preserve the original
error context where the failure may matter.

Before adding an exception path, answer three questions in code or its nearby
test: which errors are expected, what happens to each one, and how would an
unexpected error become visible? Prefer a narrow predicate over catching a
whole operation, and prefer a structural check or lint rule when the policy
can be machine-enforced.

This principle complements [[principle-encode-lessons-in-structure]]: repeated
error-handling corrections belong in a checker, type, or runtime invariant,
not in another reminder to be careful.
