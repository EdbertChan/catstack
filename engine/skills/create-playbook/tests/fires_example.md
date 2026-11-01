User says: "Create playbook for handing a stuck release over to the next
person. The same three things get forgotten every time, so write it down as
steps the router can inject."

This is the case the skill exists for — a new file under a `playbooks/`
directory for a task type nothing routes yet. The prompt opens with this
skill's trigger phrase, so the router injects the eight steps, and those
steps are what force the parts a hand-written playbook drops: a trigger
phrase checked against the installed playbooks before it is claimed, a rule
id from `engine/runbook/rules.tsv` on every step, a level chosen from what a
harness event can actually see, and the fixture pair plus a validator run
before the PR.

It fires the same way on a rewrite, by name or by model match:
"/create-playbook — the release-handover playbook has eleven steps and half
of them name no rule." That is still authoring playbook steps, so the
binding, level and validator steps all apply.
