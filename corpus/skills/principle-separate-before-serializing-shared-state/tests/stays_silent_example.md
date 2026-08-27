Two indexing jobs each write their own metrics file
(`indexer-state.json` and `metrics-state.json`), and a separate reporter
process reads both at the end to produce a combined summary. Neither job
ever opens the other's file, and no explicit invocation of this
principle skill was made.

Stays silent: this skill has `disable-model-invocation: true`, so
nothing about the description or the situation itself can trigger it —
only its own explicit invocation would. And even if it had been
invoked, there is no shared mutable write target at all — each actor
owns its own file, which is exactly the sharing-eliminated shape the
skill recommends.
