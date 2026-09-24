# Investigation phases: prove before you search

SKILL.md's Verify section carries the one-line form. This is the full gated
sequence, the tooling a research phase may reach for, and the safety
invariant that governs it: prose and fixture-only, never a live
integration wired into a script.

## The gated sequence

Each phase gates the next. A phase does not open until the one before it
has met its own gate — research literature does not open on a hypothesis,
only on a proved root cause.

1. **Observe.** Record the symptom exactly as seen — the real error text,
   the real log line, the real screenshot — not a paraphrase. Gate: the
   observation is written down verbatim.
2. **Reproduce.** Get a real repro that fails the same way on demand.
   Gate: a command or test that reliably reproduces the failure — this is
   the same repro-before-retry rule CLAUDE.md and `principle-fix-root-causes`
   already carry, not a new one.
3. **Trace.** Follow the failure from symptom to mechanism — logs,
   `strace`, a debugger, a live query — the same instrument-level-proof bar
   the Verify section already sets for causal claims. Gate: a causal chain
   from the observed symptom to a specific line, state, or condition.
4. **Prove root cause.** State the mechanism and demonstrate it with a
   one-variable control: toggle the suspected cause and show the outcome
   flips, fail-before and pass-after. Gate: the fail-before/pass-after pair
   pasted in the same message, isolated to one variable.
5. **Research literature.** Only now. Search for prior art or known
   failure classes matching the *proved* mechanism, not the symptom or an
   unproved guess. See "Tooling" and "Privacy and safety invariant" below.
   Gate: each source found is read at the primary source and recorded as
   support, contradiction, or applicability (see below) — a citation
   dropped into prose without that record does not count as research.
6. **Choose intervention.** Pick a fix informed by the proved mechanism and
   whatever the research phase actually returned support or contradiction
   for. A researched intervention still needs the same evidence any fix
   needs — it is not exempt from repro-then-fix because a citation backs
   it.
7. **Verify.** SKILL.md's Verify section applies unchanged: same-turn
   evidence, re-run the whole probe set, not just the one thing fixed.

## Semantic checkpoints, not turn caps

Move between phases on signal, never on a blind turn-count cap. A turn cap
ends a phase that is still producing new information exactly as readily as
one that has stalled — it cannot tell the two apart, so it is not a
checkpoint, it is a guess dressed as one.

**Progress signal (stay in the phase, or advance):** a new fact observed
that was not known before, a hypothesis eliminated by a control, the
repro's shape or behavior changing under a deliberately varied input. Any
one of these means the investigation is still moving and turn count is not
the thing to check.

**Thrash signal (stop, do not force the next phase):** the same error
recurring after an edit, or repeated edits to the same file or area with
no passing check in between. This is `narrow-the-scope`'s own trigger
condition, named here so a stalled investigation and a moving one are
never judged by the same turn-count number. On a thrash signal: stop,
name it out loud, and narrow the slice — do not push into "research
literature" or "choose intervention" on an investigation that has stopped
producing signal, and do not silently keep guessing at the current phase
either.

**Never terminate a changing investigation solely because of turn count.**
If the progress signal is still firing, the investigation continues
regardless of how many turns it has taken; if neither signal is firing
(no new fact, no eliminated hypothesis, no repro change, but also no
recurrence or repeated edit), that is itself worth naming to the user as
"stalled, no thrash yet" rather than silently continuing or silently
stopping.

## Tooling for the research phase (optional, no live integrations)

These are tools a human or a delegated subagent may use manually when the
research phase opens. Nothing here is a wired-up API call in this repo's
code — this is prose guidance for a person or subagent choosing where to
look, not a script that calls out on its own.

- **Semantic Scholar / OpenAlex** — discovery search by the proved
  mechanism's terms, and citation-graph traversal (forward and backward
  citations) from a paper already found relevant, to find related and
  competing explanations.
- **Crossref** — canonical DOI and bibliographic metadata lookup, so a
  citation records the actual publication rather than a search engine's
  snippet of it.
- **Zotero** — capture a found source into a local library entry (title,
  authors, DOI, one-line relevance note) instead of leaving it as a link
  dropped in chat that nobody can find again.
- **Langfuse / LiteLLM** — token and session observability for the
  investigation itself (how many turns or tokens each phase actually
  cost), feeding a `show-me-your-work` decision log rather than the fix
  itself. If the observability backend is not self-hosted, redact private
  repository or session content from any event sent to it before it
  leaves the machine — the same redaction boundary as the research-service
  rule below, applied to telemetry instead of a search query.

## Privacy and safety invariant

**Never send private repository or session contents to an external
research service.** Before the research phase reaches any external tool —
Semantic Scholar, OpenAlex, Crossref, Zotero, a subagent's own web search,
or a human copying text by hand — the proved mechanism goes out as an
anonymized mechanism statement: a generic description of the failure
class and the causal mechanism (e.g. "a bounded retry queue drops the
newest item under sustained overload") with proprietary code, secrets,
customer data, and identifying repository or session details stripped.
The mechanism statement is derived from the proof in phase 4; nothing
earlier than a proved root cause is anonymized and sent out, because
nothing earlier than that has been proved to be the right thing to
search for.

**Never claim literature support before reading the source.** An abstract
snippet or a search-result summary is not the source. A finding is
support, contradiction, or not-yet-read — never cited as support on the
strength of a title or a snippet alone.

## The support / contradiction / applicability record

Every source the research phase reads gets one row, not a citation folded
into prose:

- **Support** — the source describes the same mechanism and agrees with
  the proposed direction of fix.
- **Contradiction** — the source describes the same mechanism and points
  at a different or incompatible fix; a contradiction is not discarded
  silently, it changes the candidate interventions in phase 6.
- **Applicability** — a one-line note on whether the source's conditions
  actually match this case (same failure class, comparable scale,
  comparable constraints) or only rhymes with it. A source that does not
  apply is recorded as read and not applicable, not omitted.

## Delegation stays read-only, and proof stays independent

The research phase is read-only, non-publishing work — it delegates the
same way the Subagents section already delegates research: a subagent
searches and reads, the parent synthesizes. That does not relax the
independent-proof rule anywhere else in this file: the parent
independently reads the sources the subagent found and confirms the
support/contradiction/applicability record before phase 6 acts on it — a
subagent's own report that a source supports the fix is not verification
that it does, the same way a subagent's own report of staying in scope is
not verification that it did.
