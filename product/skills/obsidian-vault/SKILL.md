---
name: obsidian-vault
description: >-
  Write a durable note into the user's Obsidian vault, in the vault's own
  style. Use when the user says "make a note", "add that to my notes", "upload
  to Obsidian", or "save this to the vault", or when a study, investigation,
  or meeting finishes and the user wants it kept. Finds the vault, copies the
  layout of the neighbouring notes, links only notes that exist, ties every
  number to its source, and reads the file back. Not for Google Docs,
  artifacts, or docs that belong in a repo.
---

# Obsidian vault

A vault is a folder of Markdown files, marked by a hidden `.obsidian` folder.
Writing a note is writing one `.md` file. No app, plugin, or sync step is
involved, so the skill can only prove that the file exists, never that
Obsidian shows it.

## Steps

1. **Find the vault.** Run
   `find "$HOME" -maxdepth 5 -name .obsidian -type d -not -path "*/Library/*" -not -path "*/node_modules/*"`.
   The vault is the parent of the match. One match: use it. Several: ask which.
   None: stop and say so. Never create a vault. Save the vault path to memory
   so the next run skips this step.
2. **Fix the scope before writing.** If "that" could mean the last finding or
   the whole piece of work, ask once. A note on the wrong scope costs a rewrite.
3. **Copy the neighbours.** List the vault root and the five newest notes. Read
   one whole note. Reuse its frontmatter keys, title shape, section order, and
   wording. Do not add keys the neighbours lack.
4. **Name the file** in the neighbours' pattern. When the vault has no pattern,
   use `<Topic> MM-DD.md` at the vault root. If the name exists, do not
   overwrite: pick a new name or append a dated section.
5. **Write the note.** Put these parts in order:
   - A one-line summary.
   - A short statement of what was checked and what was not.
   - The facts. Each one carries its measured value and a source link: a job,
     pipeline, commit, document, or message.
   - Open items last.

   Tag a claim you could not check as unverified and name the blocker. Mask
   secrets and tokens. Link a source instead of pasting more than about ten
   lines of a log.
6. **Link only what exists.** For each `[[wikilink]]`, check that a note with
   that name exists: `find "$VAULT" -iname "<name>.md"`. Drop links that do not
   resolve, unless the user asked for stubs.
7. **Read it back.** Run `ls -l` and `wc -l` on the file and `head` its
   frontmatter, and repeat the wikilink check. Report the path, the line
   count, and which links resolved. Say the note was not opened in Obsidian.

## Do not

- Overwrite or reorganize existing notes.
- Write outside the vault, or inside its `.obsidian` folder.
- Put tokens, personal data, or private message links in a note the user may
  share.
- Say the note "syncs" or "appears" in Obsidian.
