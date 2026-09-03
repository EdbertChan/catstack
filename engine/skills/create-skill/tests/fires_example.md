User: "Add a new skill that watches flaky CI jobs and retries them —
make sure it's available in Claude, Cursor, and Codex."

This should fire: authoring a new skill / adding a `SKILL.md` / needing
it home-linked across all three harnesses is exactly this skill's scope.

The ecosystem doc link in SKILL.md is `../../../docs/ecosystem.md`
(three levels up from engine/skills/create-skill/). `scripts/check_skill_file_refs.py`
now validates relative markdown links, so a wrong depth fails CI.
