---
name: study-handoff
description: >-
  Lay out a finished study in Drive: the high-level documents in a parent
  folder, and the scripts, data, and results in folders underneath. Use when
  the user asks "are the proofs and scripts attached", "put the scripts in
  their own folder", "upload the study to Drive", or after a study whose
  documents cite scripts and numbers. Checks every upload by size so a hand
  copy that silently differs is caught, and keeps old links working.
---

# Study handoff

A reader of a study document must be able to open the script behind every
number. This skill keeps those files next to the document, in a fixed layout,
and proves each upload matches the local file.

## Layout

```text
<study folder>/
  <high-level documents>   the analysis and the proof page
  README.md                what each folder holds and the commands to rerun
  scripts/                 current scripts, older versions renamed "(v1)"
  data/                    the lists of items the study sampled
  results/                 printed summaries, one subfolder per case
```

## Steps

1. **List what exists.** Read the parent folder listing. Note where each
   document lives. A document outside the study folder is moved in.
2. **Create the folders** that are missing: `scripts`, `data`, `results`.
3. **Move files, do not copy them.** A move keeps the file id, so links in
   existing documents keep working. Replacing a file's content is not
   possible, so a changed script becomes a new file. Rename the old one
   `(v1, <date>)` and keep it in `scripts`.
4. **Upload only what you can verify.** Never retype a file of more than a
   few hundred lines into an upload call. A hand copy can differ without any
   error. Upload files small enough to paste, then compare sizes. For a larger
   file, do not upload it. Put the command that rebuilds it in the README.
5. **Check every upload by size.** Save the Drive folder listing as JSON
   (`title`, `fileSize`) and run
   `python3 scripts/verify_drive_upload.py --local-directory <folder> --listing <listing.json>`
   once per folder. Exit 0 means every size matches. Exit 1 prints the files
   that differ. Exit 2 means the check could not run.
6. **On a mismatch, never delete.** Rename the bad file so nobody uses it
   (for example `<name> (INVALID COPY, do not use).csv`), say so, and ask
   before deleting it.
7. **Write the README.** List each folder, each script with one line on what
   it does, the commands that rerun the study, and the known gaps (files not
   uploaded, files that cannot be rebuilt).
8. **Relink the documents.** Point each link at the current file. Read the
   links back and confirm each one names a file that exists in the tree.
9. **Report the tree.** Read the folder listings back and show the layout,
   the files that did not match, and what was left out.

## Do not

- Delete or trash a file the user did not ask to delete.
- Say a file is uploaded because the call succeeded. Compare the size.
- Put tokens, credentials, or private message links in any uploaded file.
