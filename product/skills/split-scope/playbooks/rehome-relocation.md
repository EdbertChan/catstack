# Rehome / Relocation Refactors

A rehome moves an already-cohesive unit — a whole file, or a whole
package/directory that is not being split further — to a new location with
its content materially unchanged: no new modules are created, no symbol is
split out, and the change is git-mv-shaped (`git diff --stat` renders as a
rename, not an unrelated add+delete pair). This is a different job from
`decomposition-extraction.md`: decomposition is N distinct transformations (N
claims, N seams); a rehome is exactly ONE transformation (the location).
Treating a rehome as a decomposition stack — copy now, repoint later, delete
much later in a disconnected slice — is a misapplication of that guidance,
not a smaller version of it.

## Is it a rehome or a decomposition?

Rehome (this playbook) when ALL of:

- the moved unit keeps its existing internal structure; no top-level symbol
  is being extracted into a module that didn't exist before
- `git mv <old path> <new path>` (or the directory equivalent) produces the
  diff — content is byte-for-byte identical apart from import-path fixups
- exactly one new home is created, not several

Decomposition (`decomposition-extraction.md`) when ANY of:

- the file's symbols are being split across two or more new modules
- the move changes internal structure (function/class boundaries) beyond
  import-path updates
- there is no single git-mv-shaped diff that captures the change — the
  change is inherently a rewrite, not a move

## Core rule: land the move as one slice, not copy-then-delete-later

Decomposition's `create → repoint → delete` sequence is safe because each
step reviews a genuinely different transformation. A rehome has no such
internal seam — the code itself hasn't changed, only its address. Splitting
a rehome the same way creates two independently-editable copies of the same
logic with only one of them live. If anyone hotfixes the old copy before the
deletion slice lands, that fix is invisible in the new copy and is silently
discarded when the old copy is later deleted — nothing re-diffs the two
copies before deletion.

Land the rehome as close to atomically as possible:

- **Preferred:** add the new path and delete the old path in the SAME
  PR/slice — a git-mv-shaped diff. Only deviate from this when the diff is
  provably too large to review in one slice.
- If repointing every caller in the same PR is genuinely too large, do not
  leave the old path as an independently-maintained duplicate. Land the move
  plus a thin forwarding shim at the old path in that same slice: the old
  path re-exports/delegates to the new path, so there is only ever ONE
  source of truth for the logic even though there are temporarily two
  importable paths. Repoint callers in following slices; delete the shim
  once the last caller is repointed, in its own final slice — that deletion
  removes only dead re-export plumbing, never live logic.

## Slice shape for one rehome

- `Review claim:` "Move <unit> from <old path> to <new path>; no logic
  change." (or, with a shim: "Move <unit> to <new path> and leave a
  forwarding shim at <old path>; no logic change.")
- git-mv-shaped diff: add at the new path, delete at the old path, in the
  same slice — or, when callers can't all move at once, add at the new path
  and replace the old path's body with a forwarding shim (re-export/delegate
  only, never duplicated logic) in the same slice
- update the moved unit's own internal imports so it is self-contained at
  the new path
- no logic change in a move slice (Fowler's "two hats" applies here too: a
  move is not the place to also fix a bug or add a field)
- keep directly affected tests with the move
- a shim-removal slice depends only on the callers-repointed slice(s), not
  unrelated work, and lands as soon as the last caller is repointed

## Sequence a rehome stack as

1. one slice: move the unit (git-mv-shaped) and, only if the full caller set
   cannot be repointed in the same slice, leave a forwarding shim at the old
   path in that SAME slice — never leave the old path holding
   independently-maintained live logic
2. re-point callers across following slices; the shim keeps them working
   meanwhile
3. delete the shim in its own slice once the last caller is repointed — this
   deletes only re-export plumbing, so there is nothing to lose

Contrast with the Decomposition sequence: there, step 3 deletes the OLD, LIVE
implementation — safe only because each extracted unit was reviewed as its
own transformation first. In a rehome nothing has changed except location,
so retiring the original must not be deferred past the slice that repoints
its last caller.

Grounding: Fowler, *Refactoring* — "Move File"/"Rename" are catalogued as
trivial, tool-supported, behavior-preserving moves, distinct from "Extract
Function"/"Extract Class" (decomposition); Fowler / Newman — Branch by
Abstraction and the Strangler Fig pattern, where a stable seam (the shim)
sits in front of code being relocated so there is exactly one live
implementation at all times, even mid-migration; Beck, *Tidy First?* — a
move commits no behavior change, so it should not straddle a window where
the moved thing has two independently-editable homes.
