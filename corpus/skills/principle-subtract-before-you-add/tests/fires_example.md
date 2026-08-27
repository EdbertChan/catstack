A channel-registration bug has now recurred a third time. Each prior fix
added another completeness check on top of the existing duplicated
registration blocks, rather than removing the duplication itself. The
plan for this fix is: add one more validator to catch the missed case.

Trigger: this is the exact pattern the skill names — patching a symptom
on top of code that already duplicates something, for the second or
third time. Grep for the existing duplicate implementations and
de-duplicate first, then decide if a new addition is even still needed.
