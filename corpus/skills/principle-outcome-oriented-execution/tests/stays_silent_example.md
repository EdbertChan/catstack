A library is being renamed from `widget-utils` to `ui-utils` across the
repo — just an import-path and package-name rewrite, no new required
parameter, field, or API argument involved — and no explicit invocation
of this principle skill was made.

Stays silent: this skill has `disable-model-invocation: true`, so
nothing about the description or the situation itself can trigger it —
only its own explicit invocation would. And even if it had been
invoked, this is a named rewrite/rename with no new required value
threading through callers, which the skill explicitly scopes itself
away from.
