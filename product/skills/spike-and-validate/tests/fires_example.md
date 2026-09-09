A plan needs a streaming ZIP reader for uploads up to 2GB. Nobody on the
team has used the candidate library, and `alternatives-considered` returned
it labeled `invented` — plausible, never run here.

This skill fires. An untested assumption is about to decide an expensive
choice, which is the stated trigger and the gate
`alternatives-considered` routes to. Step 1 writes the kill condition first
("streams a 2GB fixture without loading it into memory, under 4GB RSS"),
Step 2 builds a hardcoded throwaway in its own scratch directory, Step 3
runs it and pastes the real output including the case that breaks, and Step
4 deletes the code, keeps one finding row with `null_result` naming what the
spike did not cover, and reports validated, killed, or inconclusive.
