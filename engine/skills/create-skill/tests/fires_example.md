User: "Add a new skill that watches flaky CI jobs and retries them —
make sure it's available in Claude, Cursor, Codex, and Muse."

This should fire: authoring a new skill / adding a `SKILL.md` / needing
it home-linked across all four harnesses is exactly this skill's scope.

The ecosystem doc link in SKILL.md is `../../../docs/ecosystem.md`
(three levels up from engine/skills/create-skill/). `scripts/ci/check_skill_file_refs.py`
now validates relative markdown links, so a wrong depth fails CI.

---

User: "Add a skill that replays the hook checks on the harness without a
hook pipeline — it should only ever install for Muse."

This should also fire: authoring a new skill is this skill's scope, and the
Muse-only exception (`MUSE_ONLY_SKILLS` in `install.sh`, the mirror of
`CLAUDE_ONLY_SKILLS`) is part of what the author needs to get right.
