`disable-model-invocation: true` means the model never reads this
skill's `description:` to decide whether to apply it — that text isn't
even loaded into context. The only way this skill activates is an
explicit `/principle-experience-first` invocation.

Scoping a settings page, the team is deciding between shipping 3
well-polished settings that cover the common cases, or 10 settings
including several edge-case toggles that are half-tested and
confusing to explain. Before deciding, someone explicitly invokes
`/principle-experience-first` to load the full principle.

This skill fires here specifically because of that explicit invocation
— a product/UX scope tradeoff between convenience and delight is
exactly the pattern the skill targets once loaded (choose fewer
polished features over more rough ones), but no amount of matching
prose alone would have triggered it.
