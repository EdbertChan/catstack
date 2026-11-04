A user finishes a CI cost study with two Google Docs that cite scripts and
CSV files. They ask: "are the proofs and scripts attached to the documents?
move them to their own folder, with the high-level document in the parent and
the supporting scripts in folders underneath".

This skill fires. The request asks for the parent-folder layout and for the
scripts to be attached. The agent lists the parent folder, creates `scripts`,
`data`, and `results`, and moves the existing files so their ids stay valid.
It uploads one small new script, saves the folder listing as JSON, and runs
`scripts/verify_drive_upload.py`. The check prints one file as 132 bytes
short, so the agent renames that file as invalid and asks before deleting it.
It writes a README, relinks the documents, and reports the tree.
