# Design-doc shape

How a design doc is laid out when the user asks for one. Voice, sentence
rules, and footnote rules live in `product/skills/technical-writing/SKILL.md`;
this file is only the order of sections and what each one holds.

## Sections, in this order, and no others

1. **Summary.** Three short paragraphs: the gap today (what nobody can
   answer now), then what the tool is, then the suspects (where people
   already expect the answer to point). Motivation lives here. There is
   no Background, Justification, or status section anywhere in the doc,
   and no mention of where the request came from (a chat thread, a
   message).
2. **Vocabulary.** One sentence saying the doc uses these words and no
   others, a picture of how the things nest, and a table: the word, then
   its name in the code.
3. **Architecture.** The parts as a numbered list; each item opens with
   the part's name in bold, then one or two sentences on what it does.
   Layer rules (who may import whom) in one sentence above the list.
4. **User functionality.** A numbered flow, one sentence per step, in the
   order the user experiences it. A step says what happens, never why:
   no "because". No literal tunables (cap values, intervals, timeouts):
   say "up to its cap", "every few seconds". Sub-bullets only to list
   what one step shows.
5. **Fields table.** One row per number the page shows: the field, where
   it comes from, how the answers combine. The first mention of a source
   gives the full endpoint (method and path); later mentions use the
   source's short name.
6. **Decisions.** Numbered. Each title names the choice made ("Step
   timings come from X"), not the topic. Under it: the constraint in one
   or two sentences, the alternatives as bullets, then "We do the Nth"
   and the trade-off accepted. Wire-format and layout choices (one page
   or two, a JSON shape, row order) are not decisions; leave them out.
7. **Run it.** The commands, nothing else.
8. **Known limits.** What the reader will hit, one per bullet.

## Rules that cut across sections

- No placeholders anywhere in the doc: a figure, number, or section that
  is not ready is left out, not marked as coming.
- Figures only when the user asks for one; the Vocabulary picture is the
  one exception, since that section is defined around it.
- A number that needs a source carries a footnote; the footnote rules are
  in `technical-writing`, not here.
