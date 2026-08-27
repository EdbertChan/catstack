User: "Make a PR for this fix," in a different repo that has no
`engine/skills/make-pr/SKILL.md` overlay file at all.

This should NOT fire: `make-pr` is a catstack-local overlay. In a repo
without this file present, plain `draft-pr` applies on its own — there
are no catstack-specific hook/skill-bucket gates to add.
