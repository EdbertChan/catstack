---
name: technical-writing
description: "Write a document a tired engineer understands on the first read. Use for /technical-writing, or when writing or reviewing a doc, RFC, README, PR description, or commit message. A chat reply stays with diu."
disable-model-invocation: true
---

# Technical writing

Write so a tired engineer understands on the first read. Apply all four layers.

`diu` owns a chat reply. This skill owns a document: a README, an RFC, a PR body, or a commit message. Type `/technical-writing` to run it.

Three rules sit above the layers:

- **Cut every word that does no work.** If the sentence survives without a word, the word goes. "In order to" is "to". "It is important to note that" is nothing.
- **Use the short, everyday word.** "Use", not "utilize". "Help", not "facilitate". "Do", not "perform". A long word has to buy its length with precision.
- **When a rule makes a sentence worse, fix the sentence another way or leave it alone.** A sentence that follows every rule and sounds like a machine wrote it has failed.

The codebase is the word list. Write the real symbol, file, flag, or command name, not a synonym or a description of it.

Use the words a developer would say out loud: "move", "delete", "a budget that only decreases", not "evacuate", "ratchet", or "endgame". A named pattern is fine when the doc says what it means the first time. A new banned phrase lands in `scripts/grade_prose.py` with a fixture that fails before the phrase is added.

## Vary the rhythm

A doc can obey every layer and still read machine-written: every sentence clipped short, no view anywhere, nothing specific.

- Mix sentence lengths on purpose. Short sentences land a point. Longer ones carry a fact with its condition or consequence.
- One thought per sentence does not mean one length per sentence. Split the sentence that carries two thoughts. Keep the long sentence that carries one.
- Have a view where the mode allows it. Explanation weighs trade-offs, so say what you make of them. Reference stays dry.
- Be specific. "A column rename fails the build" tells the reader what happens.

## Pick the mode first (Diátaxis)

One document, one mode. Two questions pick it: does the content inform action (doing) or understanding (thinking), and does it serve learning or work?

- Action + learning: **tutorial**.
- Action + work: **how-to**.
- Understanding + work: **reference**.
- Understanding + learning: **explanation**.

Daniele Procida, [Diátaxis](https://diataxis.fr/).

**Tutorial: learning by doing.** The learner's success is your job. Open by saying what the learner will build. Every step produces a visible result. Tell them what they should see: the expected output, the prompt change, the log line. Cut explanation to one clause and a link. Write as "we", in commands: "First, do x. Now, do y."

**How-to: steps to a goal.** Solve a problem a person has. Assume competence and skip teaching. Action only. Link the background. Allow forks: "If you want x, do y." Name the guide by the task: "How to calibrate the radar array".

**Reference: facts for lookup.** Only describe. Be dry, complete, and sure. State facts, options, limits, and errors. Mirror the structure of the thing described. Generate from code where possible.

**Explanation: understanding and why.** One bounded topic, readable away from the product. Anchor on a real why question. Give the design decision, the history, and the constraint. Opinion is allowed here and nowhere else.

Split mixed modes and link them. A reference that says "you will learn" or "First, click" has left reference.

## Design docs (explanation mode)

A design or decision document is explanation. These rules sit on top of that mode.

- Write the team's decisions as "we": "We use Datadog as a fallback." "We do the second."
- Write runtime behavior with the component as the subject: "The loader reads the budget."
- Never address the reader as "you" in a design doc. "You" belongs to a tutorial or a how-to.
- When the user models a sentence in a review comment, adopt its voice, not only its content.
  Source: Malte Ubl, "Design Docs at Google", 2020, https://www.industrialempathy.com/posts/design-docs-at-google/. Google developer documentation style guide, "Second person and first person", https://developers.google.com/style/person (second person is for product documentation addressed to a user).
- A measured number goes in a footnote that links to a proof page. A proof page shows the command and its real output. The body sentence keeps only the claim and the footnote mark.
  Source: Malte Ubl, "Design Docs at Google", 2020, https://www.industrialempathy.com/posts/design-docs-at-google/.
- When the doc and the code disagree on a fact (a count, a layer name, a column, a status), the code is the source of truth and the doc follows. Raise only an architectural disagreement with the user.
- Every number in the doc that a command can print carries that command. Regenerate the number when the doc is republished.
  Source: Andrew Hunt and David Thomas, The Pragmatic Programmer, 1999, the DRY principle (one authoritative representation), https://pragprog.com/tips/.
- Verify a numeric product (a projection, a forecast, a savings number) with a known-answer fixture pushed through the real path. Make the inputs small enough that the expected answer is computed by hand. The assertion compares the product's output to that hand answer.
- A word on the product's screen means exactly what the screen's heading says. "Before and after" means the two numbers the heading names.
  Source: Barr, Harman, McMinn, Shahbaz, and Yoo, "The Oracle Problem in Software Testing: A Survey", IEEE TSE, 2015, https://doi.org/10.1109/TSE.2014.2372785. Eric Evans, Domain-Driven Design, 2003, ubiquitous language.
- In a document written for engineers, standard engineering terms (pipeline, job, cache, index, p50, footnote, endpoint) are the plain words. A term the user has already used in the project is never jargon to replace with a paraphrase. Rewrite only words the reader has not been given.
  Source: no known prior art.

## Write sentences to the reader (Google developer style)

- Talk to the reader as "you", in the present tense, in a tutorial or a how-to. A design doc follows the design-doc section instead. "Will" only for things that genuinely happen later.
- Say who does what: "the compiler checks". Passive is fine only when the actor is unknown or beside the point.
- Write instructions as commands: "Click Submit."
- Put the condition before the instruction: "To delete the document, click Delete."
- Put the common case first. Exceptions after.
- Sound like a knowledgeable friend. No buzzwords, no figurative language, no "please" in instructions, and never "simply", "easy", or "quickly" in a procedure.
- Link with words that say where the link goes. Prefer a sentence of context on the page over a link off it.
- Headings carry the point. Sentence case. A task heading is a bare verb phrase ("Create an instance"). A concept heading is a noun phrase. One h1 per page.
- Numbered lists for sequences, bullets for everything else. Introduce a list with a complete sentence. Keep items parallel.
- Code goes in code font. UI elements go in bold. Use serial commas.

Google's [developer documentation style guide](https://developers.google.com/style).

## Make statements load one at a time (STE)

- One instruction per sentence. One thought per sentence everywhere else.
- Split instructions longer than about 20 words and other sentences longer than about 25.
- Put the warning or condition before the step it guards.
- Keep "the" and "a": "Remove the backup file" reads one way.
- Give each word one meaning and one job, then keep it.
- Pick one word per action and stick to it: "start" here and "start" there.
- Write procedures as direct commands: "Install the component".
- Avoid "-ing" words where you can.

## Leave no sentence open to two readings (Global English)

- Keep words like "only" and "not" next to the word they change.
- Break up long noun strings: "the script that checks the proto-import budget".
- Make every "it", "they", and "this" point at one obvious thing. Repeat the noun when in doubt.
- Give every clause its verb.
- Keep the small words that show structure, such as "that" in "Ensure that the switch is off".
- Repeat the article in a series when it prevents a misread: "the client and the host", when they are two things.
- Say which parts "and" or "or" joins when a sentence can group two ways.
- Use periods. Replace an em dash with a new sentence. Replace a semicolon with a period.
- Make text in parentheses a full grammatical unit or its own sentence.
- Call each thing by one name, everywhere.

## Voice and repo specifics

- PR descriptions and commit messages are writing too. Every layer except Diátaxis applies to them. A PR body is a briefing a reviewer can read in under a minute. Link the logs. Do not paste them.
- Product UI strings are a product's copy, not this skill.
- Indent code snippets with tabs. Write real paths. Make every count true at the commit that lands it, and include the command that regenerates it.

## Eval and the hook

`scripts/grade_prose.py` scores a document. The bad paragraph below fails. The rewrite passes.

The stop hook `technical-writing-guard` runs the sentence checks when the user asked for a document. A chat reply stays silent. Code fences and inline code are removed before the check. Mode choice stays in this skill. The hook does not pick tutorial, how-to, reference, or explanation.

Before:

> Configuration of the proto import ratchet budget script parameters is performed via budget.json. Note that it's important to remember that running with --write, which updates the committed budget to reflect the current count, should only be done when lowering it. If exceeded, CI fails.

After:

> `budget.mjs` reads the committed budget from `budget.json` and counts the files that import protos. If the count exceeds the budget, CI fails. Run `budget.mjs --write` only to lower the budget.
