# Creating skills (apply everywhere)

When asked to create, add, install, or author a skill, or when about to write
a new `SKILL.md` / home-link a skill directory, read the `create-skill` skill
first (`skills/create-skill/SKILL.md` or the installed `create-skill` skill).

A skill MUST be available to Claude, Cursor, and Codex unless it is listed in
`CLAUDE_ONLY_SKILLS` in catstack `install.sh`. Prefer catstack
`skills/<name>/` + `./install.sh`. Project-skill home links MUST hit all three
roots (`scripts/link_skill_three_harnesses.sh`). Do not follow Cursor-only
`~/.cursor/skills/` install advice.
