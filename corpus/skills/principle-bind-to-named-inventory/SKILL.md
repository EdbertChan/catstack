---
name: principle-bind-to-named-inventory
description: >
  Apply after an audit, scoring review, or a request for a "real classifier"
  / "less arbitrary weights" when existing scorers, rankers, or weight
  formulas were already named. Pick among those named gaps before proposing
  a new model or library.
disable-model-invocation: true
---

# Bind to Named Inventory

After an audit (or any pass that names N existing scorers/rankers/formulas
and their failures), the next plan must pick among **those named gaps**.

Do not add a new model, library, or parallel scorer until each named system
is mapped: what it scores, whether its weights are literal or labeled, and
which failure the user is pointing at.

**Must always:**

- Bind phrases like "real classifier" or "these weights are arbitrary" onto
  a named scorer from the inventory ("the `.5/.3/.2` mix is finding-priority
  ranking; flag `a` appearing in two frauds is `fraud_learning` case
  frequency") before proposing sklearn, logistic regression, or a new file.
- Prefer replace-or-feed an existing scorer over adding a fourth.
- If the user is not comfortable with ML, teach the existing named scorers
  first. Offer a no-library path before a new dependency.

**Must never:**

- Box the user into a new prediction target that was not in the audit.
- Treat "I need a real classifier" as license to invent a model while an
  exact-string transfer gap already named in the same session sits unused.

**Battle-tested:** A scoring audit named three heuristics and that held-out
flag types often get weight 0 because the type strings do not match across
companies. The follow-up "we need a real classifier; the `.5/.3/.2` weights
are arbitrary" was boxed into logistic finding-usefulness vs a 9-company
fraud detector. The user had to invent "event X has a,b,c; event Q has
a,d,e; then a should weigh more" — which was already `fraud_learning`
prevalence, blocked by exact-string match.
