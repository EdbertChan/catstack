"""Render one self-contained review page for a stack of branches: per slice its claim block, real commits, file stat and full diff.

Usage: python3 stack_review_page.py <repo> <out.html> [--title=...] [--intro=...] [--slices=<meta.json>] [<label>=<base>..<head> ...]

Slices come from --slices, the meta.json build_review_stack.py wrote (its branch list plus one entry per slice with
"label", "base", "head" and the prose fields "summary", "justification", "lane", "claim", "safety", "rationale",
"effect", "alternatives", "non_goals", "technique", "test_plan", "revert_plan", "mr_url"; every field but label, base
and head is optional, and the block shows the ones present in that order, so a page can carry exactly the sections
its merge requests carry), and/or from positional label=base..head specs for a one-off range. A slice from the build
record is refused when its head is not a branch that build printed, when its base is not the previous head, or when
its base is not an ancestor of its head; a positional spec gets the ancestor check and its membership is reported
as unchecked. A hand-written list with no branch record is refused. An empty claim, safety, rationale or
alternatives field renders as "not stated" rather than disappearing. Each slice is diffed against its own base with
renames off, so a moved file shows as a deletion and a creation. Lines longer than MAX_LINE characters are cut with
a marker; files with more than FOLD_LINES diff lines start folded; commits whose subject starts with a SKIP_SUBJECT
prefix (task markers, merges) are left out of the commit list. Each slice carries a file list on its left, folders first, that jumps to the file's diff and unfolds it.
"""
import html
import json
import re
import subprocess
import sys

MAX_LINE = 320
FOLD_LINES = 400
SKIP_SUBJECT = ("invoker: ", "Merge ")
META_FIELDS = (("Summary", "summary"), ("Justification", "justification"), ("Review claim", "claim"), ("Review lane", "lane"),
               ("Safety invariant (proposed)", "safety"), ("Slice rationale", "rationale"), ("Architectural effect", "effect"),
               ("Alternative considerations", "alternatives"), ("Non-goals", "non_goals"), ("Technique", "technique"),
               ("Test plan", "test_plan"), ("Revert plan", "revert_plan"))
REQUIRED_FIELDS = ("claim", "safety", "rationale", "alternatives")
NOT_STATED = "not stated"


def git(repo, *args):
    return subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True, check=True).stdout


def parse_diff(text):
    files, cur = [], None
    for raw in text.splitlines():
        if raw.startswith("diff --git "):
            cur = {"name": raw.split(" b/", 1)[-1], "lines": [], "adds": 0, "dels": 0, "binary": False, "new": False, "deleted": False}
            files.append(cur)
            continue
        if cur is None:
            continue
        if raw.startswith("Binary files"):
            cur["binary"] = True
        if raw.startswith("new file mode"):
            cur["new"] = True
        if raw.startswith("deleted file mode"):
            cur["deleted"] = True
        if raw.startswith("+") and not raw.startswith("+++"):
            cur["adds"] += 1
        elif raw.startswith("-") and not raw.startswith("---"):
            cur["dels"] += 1
        cur["lines"].append(raw)
    return files


def render_line(raw):
    cut = len(raw) > MAX_LINE
    shown = raw[:MAX_LINE] + (f" … [{len(raw) - MAX_LINE} more characters]" if cut else "")
    cls = "ctx"
    if raw.startswith(("+++", "---")):
        cls = "meta"
    elif raw.startswith("@@"):
        cls = "hunk"
    elif raw.startswith("+"):
        cls = "add"
    elif raw.startswith("-"):
        cls = "del"
    elif raw.startswith(("index ", "new file", "deleted file", "similarity", "rename")):
        cls = "meta"
    return f'<div class="l {cls}">{html.escape(shown)}</div>'


def parse_args(args):
    title, intro, records, adhoc = "Review Stack", None, [], []
    for a in args:
        if a.startswith("--title="):
            title = a[len("--title="):]
        elif a.startswith("--intro="):
            intro = a[len("--intro="):]
        elif a.startswith("--slices="):
            meta_path = a[len("--slices="):]
            loaded = json.load(open(meta_path))
            if not isinstance(loaded, dict) or "branches" not in loaded:
                raise SystemExit(f"refused: {meta_path} carries no branch record; render from the meta.json "
                                 f"build_review_stack.py wrote, or pass label=base..head for a one-off range")
            records.append(loaded)
        else:
            label, rng = a.split("=", 1)
            base, head = rng.split("..", 1)
            adhoc.append({"label": label, "base": base, "head": head})
    if not records and not adhoc:
        raise SystemExit(__doc__)
    return title, intro, records, adhoc


def is_ancestor(repo, base, head):
    return subprocess.run(["git", "-C", repo, "merge-base", "--is-ancestor", base, head], capture_output=True).returncode == 0


def check_record(repo, record):
    built = record["branches"]
    previous = record["base"]
    for entry in record["slices"]:
        if entry["head"] not in built:
            raise SystemExit(f"refused: head {entry['head']} of {entry['label']} is not a branch the build printed "
                             f"({', '.join(built)}); rebuild and render from the meta.json it wrote")
        if entry["base"] != previous:
            raise SystemExit(f"refused: base {entry['base']} of {entry['label']} is not the previous head {previous}")
        if not is_ancestor(repo, entry["base"], entry["head"]):
            raise SystemExit(f"refused: {entry['base']} is not an ancestor of {entry['head']}; the stack under it was rebuilt")
        previous = entry["head"]
    return list(record["slices"])


def check_adhoc(repo, specs):
    for spec in specs:
        if not is_ancestor(repo, spec["base"], spec["head"]):
            raise SystemExit(f"refused: {spec['base']} is not an ancestor of {spec['head']}")
        print(f"unchecked: {spec['head']} has no build record, so its membership in a build is not checked")
    return specs


def meta_block(s):
    rows = []
    for heading, field in META_FIELDS:
        value = s.get(field) or (NOT_STATED if field in REQUIRED_FIELDS else "")
        if value:
            rows.append((heading, value))
    if not rows:
        return ""
    return '<dl class="meta">' + "".join(f"<dt>{html.escape(k)}</dt><dd>{linked(v)}</dd>" for k, v in rows) + "</dl>"


def linked(text):
    """Escaped text with markdown links [name](url) turned into anchors and `code` into code."""
    out = html.escape(text)
    out = re.sub(r"\[([^\]]+)\]\((https?://[^)\s]+)\)", r'<a href="\2">\1</a>', out)
    return re.sub(r"`([^`]+)`", r"<code>\1</code>", out)


def file_tree(files, anchor):
    """The slice's changed files as a folder tree, folders first, each file a link to its diff block."""
    root = {}
    for j, f in enumerate(files, 1):
        parts = f["name"].split("/")
        node = root
        for part in parts[:-1]:
            node = node.setdefault(part + "/", {})
        node[parts[-1]] = (j, f)

    def render_node(node):
        out = []
        for name, value in sorted(node.items(), key=lambda kv: (not kv[0].endswith("/"), kv[0])):
            if name.endswith("/"):
                out.append(f'<li class="dir"><span>{html.escape(name)}</span><ul>{render_node(value)}</ul></li>')
            else:
                j, f = value
                kind = "new" if f["new"] else "del" if f["deleted"] else "mod"
                out.append(f'<li><a href="#{anchor}-f{j}" class="{kind}" title="{html.escape(f["name"])}"><span class="fn">{html.escape(name)}</span>'
                           f'<span class="pm"><span class="a">+{f["adds"]}</span> <span class="d">-{f["dels"]}</span></span></a></li>')
        return "".join(out)

    return f'<aside class="tree"><div class="tree-head">{len(files)} file{"" if len(files) == 1 else "s"}</div><ul>{render_node(root)}</ul></aside>'


def render(repo, title, intro, slices):
    sections, nav = [], []
    for i, s in enumerate(slices, 1):
        base, head, label = s["base"], s["head"], s["label"]
        subjects = [x for x in git(repo, "log", "--format=%s", f"{base}..{head}").splitlines() if not x.startswith(SKIP_SUBJECT)]
        stat = git(repo, "diff", "--no-renames", "--shortstat", f"{base}..{head}").strip()
        files = parse_diff(git(repo, "diff", "--no-renames", f"{base}..{head}"))
        tip = git(repo, "rev-parse", "--short", head).strip()
        anchor = f"s{i}"
        nav.append(f'<a href="#{anchor}"><b>{i}</b><span>{html.escape(label)}<small>{html.escape(stat)}</small></span></a>')
        blocks = []
        for j, f in enumerate(files, 1):
            n = len(f["lines"])
            open_attr = "" if n > FOLD_LINES or f["binary"] else " open"
            body = '<div class="muted">binary file</div>' if f["binary"] else "".join(render_line(l) for l in f["lines"])
            blocks.append(
                f'<details{open_attr} id="{anchor}-f{j}"><summary><code>{html.escape(f["name"])}</code> <span class="pm"><span class="a">+{f["adds"]}</span> <span class="d">-{f["dels"]}</span></span>'
                + (f' <span class="muted">{n} lines, folded</span>' if not open_attr else "")
                + f'</summary><div class="diff">{body}</div></details>')
        sections.append(f'''<section id="{anchor}">
  <h2><span class="num">{i}</span> {html.escape(label)}{f' <a class="mr" href="{html.escape(s["mr_url"])}">{html.escape(s["mr_url"].rsplit("/", 1)[-1].join(("!", "")))}</a>' if s.get("mr_url") else ""}</h2>
  <p class="muted">on top of <code>{html.escape(base)}</code> · tip <code>{tip}</code> · {html.escape(stat)}</p>
  {meta_block(s)}
  <ul class="commits">{"".join(f"<li>{html.escape(x)}</li>" for x in subjects) or "<li class=muted>no commits besides the task markers</li>"}</ul>
  {f'<div class="changes">{file_tree(files, anchor)}<div class="files">{"".join(blocks)}</div></div>' if files else '<p class="muted">no file changes</p>'}
</section>''')
    default_intro = (f"Each slice is shown against the one below it, built from <code>git diff base..head</code> on the local repository; "
                     f"task-marker and merge commits are left out of the commit lists. Every file is shown as its own creation, change or "
                     f"deletion; nothing is shown as a move. Long lines are cut, and files over {FOLD_LINES} diff lines start folded. "
                     f"Click a file name to fold or unfold it; the file list on the left of each slice jumps to a file.")
    intro_html = intro if intro is not None else default_intro
    return f'''<title>{html.escape(title)}</title>
<meta name="claude:viewport-fit-sides" content="cover">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Sans+Condensed:wght@500;600&family=IBM+Plex+Mono:wght@400;500&display=swap">
<style>
:root {{ --bg: #f7f6f2; --panel: #fcfcfb; --fg: #16181c; --fg-2: #52514e; --fg-3: #85837c; --line: #dddbd3; --line-soft: #ecebe5; --add-bg: #e3f3e3; --add-fg: #1a5f1a; --del-bg: #fbe5e3; --del-fg: #8f2a22; --hunk: #e9eef7; --acc: #2a78d6;
  --display: "IBM Plex Sans Condensed", "Arial Narrow", system-ui, sans-serif; --body: "IBM Plex Sans", system-ui, sans-serif; --mono: "IBM Plex Mono", ui-monospace, Menlo, monospace; }}
@media (prefers-color-scheme: dark) {{ :root:not([data-theme="light"]) {{ --bg: #141516; --panel: #1c1d1f; --fg: #f0efec; --fg-2: #c3c2b7; --fg-3: #8d8c85; --line: #34363a; --line-soft: #26282b; --add-bg: #1b3a1b; --add-fg: #a9e3a9; --del-bg: #45211e; --del-fg: #f2b2ab; --hunk: #24303f; --acc: #3987e5; color-scheme: dark; }} }}
:root[data-theme="dark"] {{ --bg: #141516; --panel: #1c1d1f; --fg: #f0efec; --fg-2: #c3c2b7; --fg-3: #8d8c85; --line: #34363a; --line-soft: #26282b; --add-bg: #1b3a1b; --add-fg: #a9e3a9; --del-bg: #45211e; --del-fg: #f2b2ab; --hunk: #24303f; --acc: #3987e5; color-scheme: dark; }}
body {{ background: var(--bg); color: var(--fg); font: 15px/1.5 var(--body); padding-block: 28px 56px; padding-left: max(16px, env(safe-area-inset-left, 0px)); padding-right: max(16px, env(safe-area-inset-right, 0px)); }}
main {{ max-width: 1400px; margin: 0 auto; display: grid; gap: 30px; }}
main > * {{ min-width: 0; }}
h1 {{ font: 600 34px/1.1 var(--display); margin: 0 0 6px; }}
h2 {{ font: 600 22px/1.2 var(--display); margin: 0 0 4px; display: flex; gap: 10px; align-items: baseline; }}
.num {{ font: 500 14px var(--mono); color: var(--acc); border: 1px solid var(--acc); border-radius: 999px; padding: 0 8px; }}
p {{ margin: 0; max-width: 80ch; }}
.muted {{ color: var(--fg-2); font-size: 13px; }}
code {{ font: 12.5px var(--mono); }}
nav {{ display: grid; gap: 6px; }}
nav a {{ display: grid; grid-template-columns: 24px 1fr; gap: 8px; align-items: baseline; color: var(--fg); text-decoration: none; background: var(--panel); border: 1px solid var(--line); border-radius: 8px; padding: 8px 12px; font: 14px var(--mono); }}
nav a small {{ display: block; color: var(--fg-3); font-size: 12px; }}
nav a b {{ color: var(--acc); }}
nav a:hover {{ border-color: var(--acc); }}
.commits {{ margin: 8px 0 12px; padding-left: 20px; max-width: 90ch; }}
.commits li {{ margin: 2px 0; }}
.meta {{ display: grid; grid-template-columns: max-content 1fr; gap: 4px 14px; margin: 10px 0 6px; max-width: 100ch; font-size: 13.5px; }}
.meta dt {{ color: var(--fg-3); font: 600 11.5px var(--display); text-transform: uppercase; letter-spacing: .04em; padding-top: 2px; }}
.meta dd {{ margin: 0; color: var(--fg-2); white-space: pre-line; }}
h2 .mr {{ font: 500 14px var(--mono); color: var(--acc); text-decoration: none; }}
details {{ background: var(--panel); border: 1px solid var(--line); border-radius: 8px; margin: 8px 0; }}
summary {{ cursor: pointer; padding: 8px 12px; font-size: 13px; display: flex; gap: 12px; align-items: baseline; flex-wrap: wrap; }}
.pm {{ font: 12px var(--mono); }} .a {{ color: var(--add-fg); }} .d {{ color: var(--del-fg); }}
.diff {{ overflow-x: auto; border-top: 1px solid var(--line-soft); padding: 6px 0; font: 12px/1.45 var(--mono); }}
.l {{ white-space: pre; padding: 0 12px; }}
.l.add {{ background: var(--add-bg); color: var(--add-fg); }}
.l.del {{ background: var(--del-bg); color: var(--del-fg); }}
.l.hunk {{ background: var(--hunk); color: var(--fg-2); margin-top: 6px; }}
.l.meta {{ color: var(--fg-3); }}
section {{ scroll-margin-top: 12px; }}
.changes {{ display: grid; grid-template-columns: minmax(240px, max-content) minmax(0, 1fr); gap: 16px; align-items: start; margin-top: 10px; }}
.files {{ min-width: 0; }}
.files details {{ margin: 0 0 8px; scroll-margin-top: 12px; }}
.tree {{ position: sticky; top: 12px; max-height: calc(100vh - 24px); overflow: auto; background: var(--panel); border: 1px solid var(--line); border-radius: 8px; padding: 8px 0; font: 12.5px/1.5 var(--mono); }}
.tree-head {{ padding: 0 12px 6px; color: var(--fg-3); font: 600 11.5px var(--display); text-transform: uppercase; letter-spacing: .04em; }}
.tree ul {{ list-style: none; margin: 0; padding-left: 14px; }}
.tree > ul {{ padding-left: 6px; }}
.tree li.dir > span {{ display: block; padding: 2px 6px; color: var(--fg-2); }}
.tree a {{ display: flex; justify-content: space-between; gap: 8px; padding: 2px 6px; color: var(--fg); text-decoration: none; border-radius: 4px; }}
.tree a .fn {{ white-space: nowrap; }}
.tree a .pm {{ flex: none; }}
.tree a:hover, .tree a:target {{ background: var(--hunk); }}
.tree a.new .fn {{ color: var(--add-fg); }} .tree a.del .fn {{ color: var(--del-fg); text-decoration: line-through; }}
@media (max-width: 900px) {{ .changes {{ grid-template-columns: 1fr; }} .tree {{ position: static; max-height: 260px; }} .meta {{ grid-template-columns: 1fr; gap: 0 0; }} .meta dd {{ margin-bottom: 6px; }} }}
</style>
<script>
document.addEventListener("click", function (e) {{ var a = e.target.closest(".tree a"); if (!a) return; var d = document.querySelector(a.getAttribute("href")); if (d) d.open = true; }});
if (location.hash) {{ var d = document.querySelector(location.hash); if (d && d.tagName === "DETAILS") d.open = true; }}
</script>
<main>
  <header>
    <h1>{html.escape(title)}</h1>
    <p class="muted">{intro_html}</p>
  </header>
  <nav>{"".join(nav)}</nav>
  {"".join(sections)}
</main>
'''


def main(repo, out, *args):
    title, intro, records, adhoc = parse_args(args)
    slices = [entry for record in records for entry in check_record(repo, record)] + check_adhoc(repo, adhoc)
    page = render(repo, title, intro, slices)
    open(out, "w").write(page)
    print(f"wrote {out}: {len(slices)} sections, {len(page) / 1e6:.2f} MB")
    return 0


if __name__ == "__main__":
    if len(sys.argv) < 4:
        raise SystemExit(__doc__)
    sys.exit(main(*sys.argv[1:]))
