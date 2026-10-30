---
name: saveable-artifact
description: >-
  Publish a live HTML page as an Artifact that carries its full data and has a
  Save-for-everyone button, so changes persist in the artifact's database
  without republishing or recreating it. Use when turning a local or live page
  with its own data (a board, explorer, calculator) into an artifact, when asked
  to make a page's changes saveable or shared, or when saved settings apply late
  or get overwritten by the page's defaults.
---

# saveable-artifact

A page published once, with its data inside it, whose settings anyone with edit access can save from the page itself. Saving writes one document to the artifact's database. Opening the page reads it back and applies it at once.

## The three parts

1. **Data inside the page.** JSON is packed into gzip + base64 `<script type="text/plain">` blocks, so the artifact needs no server. An artifact page may not pass 16 MiB; the check fails above it.
2. **A save/load script** (`scripts/templates/`). `standalone_bridge.js` talks to the database itself. `hosted_bridge.js` is for a page shown in an iframe inside another artifact; that outer page carries `parent_bridge.js` and does the database work.
3. **A contract the page implements.** The page tells the save script what to save, how to show a saved object, whether it is drawn yet (needed when it can draw before the save script runs), and whether it took what it was given.

```js
window.savedPage = {
  snapshot: () => ({ changes: state.changes }),
  apply: async saved => { state.changes = saved.changes; draw(); },
  isReady: () => drawn,
  verify: saved => { if (state.changes.length !== saved.changes.length) throw new Error("not applied"); },
};
```

## Steps

1. Pack the data: `python3 scripts/saveable_artifact.py pack --page page.html --data name=file.json --out packed.html`. Read blocks in the page with the added `unpackDataBlock(id)`.
2. Implement the contract. Any code that applies defaults or a preset must start with `if (window.savedPageSettings) return;`. The save script sets that value the moment saved settings arrive, before it applies them.
3. Add the save script: `bridge --page packed.html --mode standalone|hosted --ready-function <name> --settings-path <collection/doc> --out page.html`. For hosted mode also run `parent --page outer.html --frame-id <iframe id> --settings-path <same path> --out outer.html`. Put `<span data-saveable-artifact="button"></span>` where the button should sit.
4. Check, then measure: `check --page page.html`, then `scripts/measure_apply_delay.py --page page.html --mode <mode> --saved saved.json --applied-expression "<js that is true once applied>" --arrivals 0 300 3000 -1`. Paste the table. The tool fails when a saved setting takes over 100 ms or never shows.
5. Publish with the Artifact tool, then seed or change the saved document with `ArtifactData`: read it, keep a backup copy, write with `if_version` set to the version just read, read it back by a second route.

## Rules

- No timers in the save script. A fixed wait before applying saved settings is the bug this skill exists to prevent; `check` fails on `setTimeout`, `setInterval` or `sleep(`.
- Defaults yield to saved settings, never the reverse. Applying saved settings late, or retrying until they stick, hides a defaults script that overwrites them.
- A saved document someone else wrote is theirs: back it up and pin the write to its version before replacing it, and say so in the reply.
- A publish refused because the live page changed: read the live page in full, merge, then publish. Never use `force`.
- A check run against a stand-in proves the page's logic, not the real service. Call the real database read and write unproven until the page is opened signed in, and say so; the measuring tool is one such stand-in.
- Keep this skill and its templates neutral: no employer names, hosts or project paths.

## Files

- `scripts/saveable_artifact.py`: `pack`, `bridge`, `parent`, `check`.
- `scripts/measure_apply_delay.py`: headless Chrome timing for both modes.
- `scripts/templates/standalone_bridge.js`, `hosted_bridge.js`, `parent_bridge.js`: the browser code, with `__SETTINGS_PATH__`, `__READY_FUNCTION__` and `__FRAME_ID__` filled in.
- `tests/`: unit tests, a toy page, and a Chrome run that skips when Chrome is absent.
