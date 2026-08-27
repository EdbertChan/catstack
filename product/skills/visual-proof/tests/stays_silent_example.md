User says: "I fixed a race condition in the background job queue —
here's the diff."

Nothing about this change touches UI: no screen, component, or
user-visible rendering changed. There is no before/after screen state to
capture, so the visual-proof workflow (before/after capture, pixel diff,
`Manually inspected:` line) does not apply — a passing test or log-based
proof is the right evidence here, not screenshots.
