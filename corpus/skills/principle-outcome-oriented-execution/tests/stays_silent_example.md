A library is being renamed from `widget-utils` to `ui-utils` across the
repo, with no new required parameter, field, or API argument involved —
just an import-path and package-name rewrite.

Does not trigger: this is a named rewrite/rename with no new required
value threading through callers, which the skill explicitly scopes
itself away from ("not just named rewrites/migrations").
