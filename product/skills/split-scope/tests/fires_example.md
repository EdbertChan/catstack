User says: "Let's implement the new billing-webhook feature: it needs a
DB migration, a write-path handler, an API endpoint, and a UI toggle."

This is exactly the case the skill exists for — authoring a multi-diff
plan that crosses architectural boundaries (DB migration, write path,
API exposure, UI use). Before writing any code, split by those
boundaries, and for each slice state the review claim, review lane,
safety invariant, slice rationale, and non-goals — then confirm each
safety invariant with the user before finalizing.

Second shape. A finished branch changes `engine/hooks/playbook-router/`
(a hook that parses skill playbooks) and `product/skills/ship-a-detector/`
(the playbook it parses). The draft PR body says "they ship together
because the router change exists only to read the playbook's new shape".

That is a reader plus the thing it reads: two review claims. Split it into
a stack, playbook first, router second. The make-pr preflight fails on
the unit mix and prints one `split` line per unit.
