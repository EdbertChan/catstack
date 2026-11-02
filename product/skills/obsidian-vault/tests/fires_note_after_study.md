A user and the agent finish a week-long investigation into which CI uploads
anyone reads. The user says: "make a note of that, upload to Obsidian vault".

This skill fires. The request names the vault and asks to keep finished work.
The agent runs the `find` for a `.obsidian` folder and gets one match, so it
uses that vault. "That" could mean the last finding or the whole study, so the
agent asks once and the user picks the whole study. It lists the vault root,
reads the newest note, and copies that note's frontmatter keys, title shape,
and "what I checked" paragraph. Each number in the new note carries a source
link. It runs the wikilink check, drops one `[[link]]` that does not resolve,
runs `ls -l` and `wc -l` on the file, and reports the path and line count. It
says the note was not opened in Obsidian.
