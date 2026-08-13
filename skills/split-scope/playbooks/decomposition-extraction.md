# Decomposition & Extraction Refactors

This covers decomposition only: splitting ONE file's symbols across multiple
NEW modules. If the work is instead relocating an already-cohesive,
self-contained unit (a whole file, or a whole package/directory that is not
being split further) to a new location with the content materially
unchanged, use `rehome-relocation.md` instead. Sequencing a pure move the way
this playbook sequences decomposition creates a long-lived duplicate-logic
drift window — see that playbook's rationale.

When you split a large file by extracting units into new modules, do one
refactor at a time: one PR moves exactly ONE top-level symbol. A function move
is its own PR. A class moves as one PR with its methods riding along — one
top-level symbol per PR, not method-by-method. Create the target file, move
that one symbol, re-point its references in the same PR so behavior is
preserved, and keep the public surface (facade, exports, dispatcher) stable. Do
not batch several distinct extractions into one diff.

Each move is a separate review claim. Every extraction has its own seam and its
own "is behavior preserved?" question, so the reviewer checks one move at a
time. "Extract prepare + dispatch + finalize" is three moves, three claims,
three slices — not one.

This does NOT contradict grouping the "exact same mechanical migration across
many files." That rule is one transformation applied to N call sites (one
claim). Decomposition is N distinct transformations (N claims): different code,
different seams, different risk.

Dependency-cluster exception: if the moved symbol depends on a private helper in
the same file that is not part of the public surface, and moving the symbol
alone would break the build or force a throwaway re-export shim, move that
minimal helper cluster together in the same PR. Keep the cluster as small as the
build requires — this is still one cohesive move, not a licence to batch
unrelated extractions.

## Slice shape for one move

- `Review claim:` "Move <unit> out of <file> into <new module>, behavior
  unchanged."
- create the new module and move exactly one top-level symbol into it
- update imports/facade in the same PR so the public surface is byte-for-byte
  identical to callers
- keep directly affected tests with the move; they prove behavior is preserved
- no behavior change in a move slice (Fowler's "two hats": never refactor and
  change behavior in the same diff)

## Sequence the decomposition stack as

1. one slice per extracted unit (create-and-move), foundational unit first
2. re-point remaining callers once a unit is extracted
3. delete now-dead original code in its own slice, as soon as it is unused

Grounding: Fowler, *Refactoring* — "Move Function" applied as small
behavior-preserving steps (compile-test-commit each); Beck, *Tidy First?* —
keep structural changes isolated from behavioral ones, each in its own
PR/commit; industry guidance (Graphite, Artsy) — one module/class per PR keeps
diffs near the 50–200 line review sweet spot.
