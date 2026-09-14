# _flags

One reader for "is this catstack flag on", shared by every hook that can be
switched off.

## The switch

`CATSTACK_REFLECT_ENFORCEMENT` turns reflect/automate-me enforcement on. It is
**off unless something sets it**. Four hooks answer to it:

| Hook | What it does when on |
|---|---|
| `scope-lock` | stops every tool after a second scope correction, until the user types `/reflect` and `automate-me` |
| `reflect-on-thrash` | asks for a reflect at the end of a thrashy session |
| `wrong-check-reflect` | queues a judge on a retraction-shaped reply |
| `verdict-flip-watch` | notes a verifier that passed and then failed |

Turn it on for a machine:

```sh
echo 'CATSTACK_REFLECT_ENFORCEMENT=1' >> ~/.catstack.env
```

or for one repo, in that repo's `.env`, or by exporting it in the shell.

`frustration-watchdog` is deliberately **not** in the table. It enforces the
live-demo "end the wait" rule and never mentions reflect or automate-me; the
only reason it reads like a reflect hook is a comment saying a reflect pass is
what motivated it.

## Where the value comes from

First source that defines the key wins:

1. the process environment
2. the file named by `$CATSTACK_ENV_FILE`
3. `<repo root>/.env`, walking up from the hook payload's `cwd`
4. `~/.catstack.env`

Files are read as plain `KEY=VALUE` lines, never sourced, and no key other
than the one asked for is kept. `1`, `true`, `yes` and `on` mean on; anything
else, including an empty value, means off.

## Three outcomes, not two

A lookup answers set-on, set-off, or could-not-tell. The third one is why this
module exists in the shape it does. A candidate `.env` file that is there and
cannot be read (wrong type, bad bytes, no permission) used to come back as
`None`, which every caller then read as "the flag is not set" -- a check that
could not run reporting clean.

Now `read_flag_from_file` raises `UnreadableEnvFile` for that case,
`resolve_flag` collects those paths in `FlagLookup.unreadable`, and
`enforcement_gate` prints them to stderr before returning. The gate still
fails closed, because a quiet advisory is the safe direction for these hooks,
but the user is told which file could not be checked rather than being left to
read silence as consent.

## Using it from a hook

```python
sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "_flags"))

from flags import enforcement_gate  # noqa: E402

if not enforcement_gate("my-hook", payload.get("cwd")):
    return None
```

Two `dirname` calls, never `realpath`: install.sh links each hook directory
separately, so a hook finds this module as a sibling of its own symlink.
`realpath` would jump into the checkout and miss it in a partial install.

install.sh links `_flags` into `~/.claude/hooks`, `~/.cursor/hooks` and
`~/.codex/hooks`, because `scope-lock` and `wrong-check-reflect` are installed
into all three and import this module at load time. A missing link is an
`ImportError` at hook start, which fails open and looks exactly like "the user
did not opt in" -- `tests/test_installed_layout.py` pins the link per harness
for that reason.

## Tests

```sh
python3 -m unittest discover -s engine/hooks/_flags/tests -v
```
