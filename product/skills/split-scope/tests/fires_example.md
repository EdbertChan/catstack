User says: "Let's implement the new billing-webhook feature: it needs a
DB migration, a write-path handler, an API endpoint, and a UI toggle."

This is exactly the case the skill exists for — authoring a multi-diff
plan that crosses architectural boundaries (DB migration, write path,
API exposure, UI use). Before writing any code, split by those
boundaries, and for each slice state the review claim, review lane,
safety invariant, slice rationale, and non-goals — then confirm each
safety invariant with the user before finalizing.
