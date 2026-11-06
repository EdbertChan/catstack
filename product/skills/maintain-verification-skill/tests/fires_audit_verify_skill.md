A user types: "/maintain-verification-skill" in a repo that already has
`.cursor/skills/verify-notes/` with a feature map, after a week of UI changes.

This skill fires. It finds the one verify skill, fixes the map index, sends one
read-only reader per feature file, drives every feature live behind a doctor
check, triages drift versus harness gap versus product bug, and reports clean,
changed, or blocked. It publishes nothing unless the user asked.
