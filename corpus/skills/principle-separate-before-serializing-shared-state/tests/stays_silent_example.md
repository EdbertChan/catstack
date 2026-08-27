Two indexing jobs each write their own metrics file
(`indexer-state.json` and `metrics-state.json`), and a separate reporter
process reads both at the end to produce a combined summary. Neither job
ever opens the other's file.

Does not trigger: there is no shared mutable write target at all — each
actor owns its own file and merging happens only at the read/reporting
boundary, which is exactly the sharing-eliminated shape the skill
recommends.
