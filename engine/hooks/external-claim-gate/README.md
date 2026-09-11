# external-claim-gate

Blocks a shell command that writes prose to GitHub when that prose claims a
cause or a fix and carries no evidence.

Every other evidence gate here reads one thing: the chat message at Stop
time. Text sent through a tool call never shows up there. So an issue body
that says "it crashes because X" gets published without any check. This hook
reads that text before the command runs.

## When it fires

Both of these must be true:

1. **The command writes to GitHub.** One of:
   - `gh issue create`: `--body`/`-b`, `--body-file`/`-F`, `--title`/`-t`
   - `gh issue comment` and `gh pr comment`: `--body`/`-b`, `--body-file`/`-F`
   - `gh release create`: `--notes`/`-n`, `--notes-file`/`-F`, `--title`/`-t`
   - `gh api` sent as POST or PATCH (set with `-X`, or implied because fields
     were given) with a `body` field: `-f body=...`, `-F body=...`,
     `-F body=@file`, or an `--input` JSON file that has a `body` key.
2. **The text makes a claim.** The claim test is `find_unverified_claim` from
   `engine/hooks/diu-stop/claude_stop_check.py`, loaded from that file, not
   copied. It runs on the extracted body text, not on the whole command line.
   If the diu-stop rule changes, this gate changes with it.

The hook reads the command with a small shell parser. It follows `cd`,
`bash -c` / `sh -c` scripts, `eval`, leading `VAR=value` settings, and
wrapper words like `env`, `command`, `sudo` and `timeout`. Text that only
*mentions* a gh command (`echo ...`, `git commit -m ...`, `grep ...`) is not a
write, so it never fires.

## What clears it

Any of these, anywhere in the same body:

- a fenced block (three backticks or three tildes)
- a `file:line` reference (`src/cache/store.py:88`, or `store.py#L88`)
- pasted command output, shown by a prompt line (`$ cmd` or `>>> expr`)
- an explicit `{{CAT-UNVERIFIED: <claim> -- cannot verify: <reason>}}` tag

Inline backticks clear the paragraph they sit in, because the shared matcher
works that way.

A body with no claim passes: a feature request, a question, a status note.

## Three outcomes

| Outcome | What happens |
| --- | --- |
| hit | blocked (exit 2). The message quotes the claim, lists the evidence that is missing, and gives the two ways through: add the evidence to the body, or tag the claim with `{{CAT-UNVERIFIED: ... -- cannot verify: <reason>}}`. |
| clean | allowed |
| UNCHECKED | blocked (exit 2). The body could not be read, so it has not been cleared. |

The hook reports UNCHECKED when the body:

- comes from stdin (`--body-file -` with a heredoc, a here-string, a pipe, or
  a `<` redirect; `-F body=@-`; `--input -`)
- uses shell expansion (`"$BODY"`, `"$(cat <<'EOF' ...)"`, backticks)
- is a file that is missing, unreadable, not a regular file, or over the
  1,000,000-byte read cap
- is a file that the same command writes before gh runs (a `>` redirect,
  `tee`, or a nested `bash -c`), so the file on disk is not what gh will
  send, or that same command writes to a path the hook cannot resolve
- is a relative path after a `cd` the hook could not follow
- sits in a command that cannot be parsed (for example an unclosed quote)
- sits in a `gh api` field whose *name* uses shell expansion

To get past UNCHECKED, make the body readable. Put it inline with
`--body '...'`, or write it to a file in an earlier, separate command and pass
that path. Then the normal check runs.

## Fail direction

- **Fails closed** when a GitHub write is named but its body cannot be read.
  That covers every UNCHECKED case above. It also covers a hook payload that
  is not JSON, or a detector crash, when the raw text still names a gh write.
- **Fails open** when the hook finds no GitHub write: gh called from a script
  file or an alias, `ssh`, `xargs`, or any wrapper not listed above; GraphQL
  mutations through `gh api graphql`; and `gh pr create` / `gh pr edit`,
  which `pr-schema-gate` and `history-claim-check` cover. A payload or
  detector failure on a command that names no gh write is also allowed. The
  hook writes the reason to stderr.

## Known limits

- The claim test is the diu-stop matcher, which is a rough stand-in, not a
  truth check. A feature request that explains itself with "because" is
  flagged just like a diagnosis. The same two ways through apply.
- Evidence is checked by shape. A fenced block full of made-up output clears
  the gate.

## Files

- `detect.py`: the shell parser, finds the body, three-outcome verdict, block
  message
- `claude_pretooluse.py`: Claude `PreToolUse` entry point; exits 2 with the
  message on stderr
- `claude.tool.hook.json`: settings fragment (matcher `Bash`)
- `install_claude_hook.py`: merges the fragment into `~/.claude/settings.json`
  and leaves other entries alone

## Install

`./install.sh` from the repo root. It creates the `~/.claude/hooks/` link
and merges the settings entry. Then restart Claude Code.

## Tests

```sh
python3 -m unittest discover -s engine/hooks/external-claim-gate/tests -v
```
