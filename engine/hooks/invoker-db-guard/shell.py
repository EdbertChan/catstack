"""Just enough of a shell reader to find the commands a Bash call really runs.

A PreToolUse hook sees one string. The database path can arrive quoted, as
`~`, `$HOME`, or a variable set earlier in the same string; the SQL can sit
in a heredoc, a here-string, a pipe from `echo`, or a `-c` argument. Text
that only mentions the database -- a commit message, a PR body built with
`$(cat <<'EOF' ... EOF)`, a doc written through `cat >` -- has to stay data.

`parse_stages` splits the string into stages (one simple command each),
expands variables and `~` the way the shell would, attaches heredoc and
here-string bodies to the stage that reads them, records which stage a pipe
feeds, and walks into `$(...)`, backticks, and process substitution, because
those run too.
"""
from __future__ import annotations

import os
import re

ASSIGN_RE = re.compile(r"^[A-Za-z_]\w*=")
NAME_RE = re.compile(r"[A-Za-z_]\w*")
BODY_VAR_RE = re.compile(r"\$\{([A-Za-z_]\w*)\}|\$([A-Za-z_]\w*)")
DECLARERS = {"export", "declare", "local", "readonly", "typeset"}
TWO_CHAR_OPS = ("&&", "||", ";;", "|&")
REDIRECT_OPS = ("<<<", "<<-", "<<", "<>", "<&", "<(", ">>", ">&", ">|", ">(", "<", ">")
UNRESOLVED = "$()"


class Stage:
    """One simple command: expanded words, redirects, stdin bodies, pipe source."""

    __slots__ = ("words", "redirects", "stdin_texts", "piped_from")

    def __init__(self, piped_from=None):
        self.words = []
        self.redirects = []
        self.stdin_texts = []
        self.piped_from = piped_from

    def is_empty(self):
        return not (self.words or self.redirects or self.stdin_texts)


class _State:
    __slots__ = ("stage", "word", "redirect_op", "docs", "last", "depth")

    def __init__(self, stage):
        self.stage = stage
        self.word = None
        self.redirect_op = None
        self.docs = []
        self.last = None
        self.depth = 0


class _Lexer:
    def __init__(self, text, env):
        self.text = text
        self.env = env
        self.stages = []

    def expand_name(self, name):
        value = self.env.get(name)
        return value if value is not None else "$" + name

    def open_stage(self, piped_from):
        stage = Stage(piped_from)
        self.stages.append(stage)
        return stage

    def add(self, st, chars):
        if st.word is None:
            st.word = []
        st.word.append(chars)

    def tilde_position(self, st):
        if st.word is None:
            return True
        so_far = "".join(st.word)
        return bool(ASSIGN_RE.match(so_far)) and so_far.endswith(("=", ":"))

    def end_word(self, st):
        if st.word is None:
            return
        word = "".join(st.word)
        st.word = None
        if st.redirect_op == "<<<":
            st.stage.stdin_texts.append(word)
        elif st.redirect_op:
            st.stage.redirects.append((st.redirect_op, word))
        else:
            st.stage.words.append(word)
        st.redirect_op = None

    def close_stage(self, st):
        self.end_word(st)
        self.record_assignments(st.stage)
        st.last = st.stage

    def record_assignments(self, stage):
        words = list(stage.words)
        if words and words[0] in DECLARERS:
            words = [w for w in words[1:] if not w.startswith("-")]
        for word in words:
            if not ASSIGN_RE.match(word):
                break
            name, value = word.split("=", 1)
            self.env[name] = value

    def parse(self, i, closer):
        text = self.text
        n = len(text)
        st = _State(self.open_stage(None))
        while i < n:
            c = text[i]
            if c == ")" and st.depth == 0 and closer == ")":
                self.close_stage(st)
                return i + 1
            if c in " \t\r":
                self.end_word(st)
                i += 1
            elif c == "\n":
                self.close_stage(st)
                i = self.read_heredocs(i + 1, st)
                st.stage = self.open_stage(None)
            elif c == "#" and st.word is None:
                end = text.find("\n", i)
                i = n if end < 0 else end
            elif c == "\\":
                if text[i + 1:i + 2] != "\n":
                    self.add(st, text[i + 1:i + 2])
                i += 2
            elif c == "'":
                end = text.find("'", i + 1)
                end = n if end < 0 else end
                self.add(st, text[i + 1:end])
                i = end + 1
            elif c == '"':
                i = self.double_quoted(i + 1, st)
            elif c == "$":
                i = self.dollar(i, st)
            elif c == "`":
                i = self.backtick(i, st)
            elif c == "~" and self.tilde_position(st) and (i + 1 >= n or text[i + 1] in "/ \t\n;|&)"):
                self.add(st, self.expand_name("HOME"))
                i += 1
            elif c == "&" and text[i + 1:i + 2] == ">":
                self.end_word(st)
                op = "&>>" if text[i + 2:i + 3] == ">" else "&>"
                st.redirect_op = op
                i += len(op)
            elif c in ";&|()":
                self.end_word(st)
                op = next((o for o in TWO_CHAR_OPS if text.startswith(o, i)), c)
                i += len(op)
                if op == "(":
                    st.depth += 1
                elif op == ")" and st.depth:
                    st.depth -= 1
                self.close_stage(st)
                st.stage = self.open_stage(st.last if op in ("|", "|&") else None)
            elif c in "<>":
                if st.word is not None and "".join(st.word).isdigit():
                    st.word = None
                self.end_word(st)
                op = next(o for o in REDIRECT_OPS if text.startswith(o, i))
                i += len(op)
                if op in ("<(", ">("):
                    i = self.parse(i, ")")
                    self.add(st, UNRESOLVED)
                elif op in ("<<", "<<-"):
                    i, tag, quoted = self.heredoc_tag(i)
                    st.docs.append((st.stage, tag, op == "<<-", quoted))
                else:
                    st.redirect_op = op
            else:
                self.add(st, c)
                i += 1
        self.close_stage(st)
        return i

    def double_quoted(self, i, st):
        text = self.text
        n = len(text)
        self.add(st, "")
        while i < n:
            c = text[i]
            if c == '"':
                return i + 1
            if c == "\\" and text[i + 1:i + 2] in ('"', "\\", "$", "`", "\n"):
                if text[i + 1] != "\n":
                    self.add(st, text[i + 1])
                i += 2
            elif c == "$":
                i = self.dollar(i, st)
            elif c == "`":
                i = self.backtick(i, st)
            else:
                self.add(st, c)
                i += 1
        return n

    def dollar(self, i, st):
        text = self.text
        nxt = text[i + 1:i + 2]
        if text.startswith("((", i + 1):
            end = text.find("))", i + 3)
            self.add(st, UNRESOLVED)
            return len(text) if end < 0 else end + 2
        if nxt == "(":
            end = self.parse(i + 2, ")")
            self.add(st, UNRESOLVED)
            return end
        if nxt == "{":
            end = text.find("}", i + 2)
            end = len(text) if end < 0 else end
            self.add(st, self.braced(text[i + 2:end]))
            return end + 1
        if nxt == "'":
            end = text.find("'", i + 2)
            end = len(text) if end < 0 else end
            self.add(st, text[i + 2:end])
            return end + 1
        match = NAME_RE.match(text, i + 1)
        if match:
            self.add(st, self.expand_name(match.group(0)))
            return match.end()
        if nxt and (nxt.isdigit() or nxt in "@*#?$!-"):
            self.add(st, UNRESOLVED)
            return i + 2
        self.add(st, "$")
        return i + 1

    def braced(self, inner):
        match = re.match(r"([A-Za-z_]\w*)(?::?[-=](.*))?$", inner, re.DOTALL)
        if not match:
            return UNRESOLVED
        name, default = match.group(1), match.group(2)
        if name in self.env:
            return self.env[name]
        if default is not None:
            return self.expand_body(default)
        return "${" + name + "}"

    def backtick(self, i, st):
        end = self.text.find("`", i + 1)
        end = len(self.text) if end < 0 else end
        self.stages.extend(parse_stages(self.text[i + 1:end], self.env))
        self.add(st, UNRESOLVED)
        return end + 1

    def heredoc_tag(self, i):
        text = self.text
        n = len(text)
        while i < n and text[i] in " \t":
            i += 1
        chars = []
        quoted = False
        while i < n and text[i] not in " \t\n;|&<>()":
            if text[i] in "'\"\\":
                quoted = True
            else:
                chars.append(text[i])
            i += 1
        return i, "".join(chars), quoted

    def read_heredocs(self, i, st):
        text = self.text
        n = len(text)
        for stage, tag, strip_tabs, quoted in st.docs:
            body = []
            while i < n:
                end = text.find("\n", i)
                line = text[i:] if end < 0 else text[i:end]
                i = n if end < 0 else end + 1
                if (line.lstrip("\t") if strip_tabs else line) == tag:
                    break
                body.append(line)
            joined = "\n".join(body) + "\n"
            stage.stdin_texts.append(joined if quoted else self.expand_body(joined))
        st.docs = []
        return i

    def expand_body(self, text):
        return BODY_VAR_RE.sub(
            lambda m: self.env.get(m.group(1) or m.group(2), m.group(0)), text
        )


def parse_stages(text, env):
    """Every non-empty stage in `text`, nested substitutions included.

    `env` maps variable names to values and is updated in place by the
    assignments the text makes, so a later stage sees an earlier `DB=...`.
    An unset variable stays literal (`$DB`), which callers read as a path
    they could not resolve.
    """
    lexer = _Lexer(text or "", env)
    lexer.parse(0, None)
    return [stage for stage in lexer.stages if not stage.is_empty()]


def default_env():
    env = dict(os.environ)
    env.setdefault("HOME", os.path.expanduser("~"))
    return env
