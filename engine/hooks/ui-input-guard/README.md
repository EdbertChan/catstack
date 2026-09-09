# ui-input-guard

PreToolUse hook (Bash): never drive the user's own keyboard, mouse, or screen
uninvited. Synthetic input acts on the session the user is sitting in — typed
into the wrong window it sends real messages, trips real shortcuts, and lands
in the lock screen; a screen recording captures whatever they have open.

Blocked mechanisms: AppleScript `System Events` with `keystroke`, `key code`,
or `click at`; `cliclick`; `xdotool`; `screencapture -V`; `ffmpeg` capturing
an `avfoundation` screen device. A command that runs a local script is scanned
through that script's contents, because the wrapper hides what it does, and
shell variables in the path are resolved first (`S=/tmp/run; $S/drive.sh`).

Scripts are streamed in chunks rather than skipped for being large: a silent
skip is an unchecked file reported as clean. Past an 8 MB ceiling, or on a
read error, the command is refused with the path and the reason instead,
because a guard that cannot check does not assume safe. The escape is the
same hands-off marker, or splitting the input-driving part into a file that
can be read.

Allowed when all three hold:

1. A hands-off window is open — `touch /tmp/.ui-input-window` (override with
   `UI_INPUT_WINDOW_FILE`), younger than 30 minutes.
2. The screen is not locked (macOS `CGSSessionScreenIsLocked`).
3. The user has been idle at least 10 seconds (macOS `HIDIdleTime`).

Stays silent on the neighbours that only observe or author: `open` on a deep
link, an AppleScript geometry read, a still `screencapture`, `ffmpeg`
transcoding a file, a `cat > script <<EOF` heredoc that writes a driver, and
read-only pipelines whose search pattern happens to contain the words. Code
handed to a non-shell interpreter, as a heredoc or through `-c`/`-e`, counts
as data, so input driven from inside a Python or Node program is a known gap;
`osascript -e` is not stripped, since there the words are the mechanism.

Mechanical half of the live-demo rules in `engine/CLAUDE.core.md` and the UI
testing section of `corpus/skills/cat-mode/SKILL.md`. Probe errors and
non-macOS hosts fail open on lock and idle; a missing marker still blocks.

## Files

- `detect.py` — mechanism patterns, heredoc and read-only stripping, script
  following, lock/idle probes, `decide()`.
- `claude_pretooluse_check.py` — Claude PreToolUse entrypoint.
- `claude.hook.json` / `install_claude_hook.py` — settings.json merge (idempotent).
- `tests/fixtures/commands_{fire,silent}.json` — sanitized real commands.
- `tests/test_hooks.py`

## Env

| Var | Effect |
|-----|--------|
| `UI_INPUT_WINDOW_FILE` | Hands-off marker path (default `/tmp/.ui-input-window`). |
