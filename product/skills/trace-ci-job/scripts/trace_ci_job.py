#!/usr/bin/env python3
"""Resolve a GitLab CI job name to its YAML definition, inherited config, script
lines and needs/trigger edges, each with file:line and a GitLab blob URL.

Read-only and pinned: every file is read at an explicit commit SHA, through
`git show SHA:path` or the GitLab files API with ref=SHA. The moving working
tree is never read and no YAML is written.
"""
from __future__ import annotations

import argparse
import difflib
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from urllib.parse import quote

try:
    import yaml
except ImportError:
    yaml = None

YAML_AVAILABLE = yaml is not None
YAML_ERROR = "error: PyYAML is required (pip install pyyaml)"

DEFAULT_GITLAB = os.environ.get("GITLAB_HOST", "https://gitlab.com")
DEFAULT_PROJECT = os.environ.get("GITLAB_PROJECT")
DEFAULT_ROOT = ".gitlab-ci.yml"
TOKEN_ENV = "GITLAB_TOKEN"
SHA_RE = re.compile(r"^[0-9a-f]{7,40}$")
RESERVED = {"stages", "variables", "include", "default", "workflow", "image", "services",
            "cache", "before_script", "after_script"}
SCRIPT_KEYS = ("before_script", "script", "after_script")
SH_REF_RE = re.compile(r"(?<![\w$])((?:\$\{?[A-Z_]+\}?/|\./)?[\w./-]+\.sh)\b")
FUNC_DEF_RE = re.compile(r"^\s*(?:function\s+)?([A-Za-z_][\w-]*)\s*(?:\(\))?\s*\{", re.M)

Reader = Callable[[str], str]


class JobNotFound(ValueError):
    def __init__(self, name: str, close: list[str]):
        self.name, self.close = name, close
        hint = ", ".join(close) if close else "none"
        super().__init__(f"no job named {name!r}; close matches: {hint}")


class Reference(list):
    line = 0


if YAML_AVAILABLE:
    class RefLoader(yaml.SafeLoader):
        pass
else:
    class RefLoader:
        pass


def _construct_reference(loader: RefLoader, node: yaml.Node) -> Reference:
    ref = Reference(loader.construct_sequence(node, deep=True))
    ref.line = node.start_mark.line + 1
    return ref


if YAML_AVAILABLE:
    RefLoader.add_constructor("!reference", _construct_reference)


@dataclass
class Hop:
    kind: str
    path: str
    line: int
    text: str
    end: int | None = None


@dataclass
class JobDef:
    name: str
    path: str
    key_node: yaml.Node
    node: yaml.MappingNode
    loader: RefLoader

    @property
    def line(self) -> int:
        return self.key_node.start_mark.line + 1

    @property
    def end_line(self) -> int:
        return max(self.line, self.node.end_mark.line + (0 if self.node.end_mark.column == 0 else 1))

    def entry(self, key: str):
        for k, v in self.node.value:
            if isinstance(k, yaml.ScalarNode) and k.value == key:
                return k, v
        return None

    def value(self, key: str):
        found = self.entry(key)
        return None if found is None else self.loader.construct_object(found[1], deep=True)


@dataclass
class Config:
    jobs: dict
    stages: list
    shadowed: dict
    notes: list


def blob_url(host: str, project: str, sha: str, path: str, start: int | None = None, end: int | None = None) -> str:
    if not SHA_RE.match(sha or ""):
        raise ValueError(f"sha must be a 7-40 character hex commit id, got {sha!r}")
    url = f"{host.rstrip('/')}/{project}/-/blob/{sha}/{quote(path.lstrip('/'))}"
    if start is None:
        return url
    return f"{url}#L{start}" if end is None or end == start else f"{url}#L{start}-{end}"


def _mapping_entries(loader: RefLoader, node: yaml.Node) -> list:
    if not isinstance(node, yaml.MappingNode):
        return []
    loader.flatten_mapping(node)
    return [(k.value, k, v) for k, v in node.value if isinstance(k, yaml.ScalarNode)]


def _includes(loader: RefLoader, node: yaml.Node, notes: list, path: str) -> list:
    locals_: list[str] = []
    items = node.value if isinstance(node, yaml.SequenceNode) else [node]
    for item in items:
        if isinstance(item, yaml.ScalarNode):
            if item.value.startswith(("http://", "https://")):
                notes.append(f"{path}:{item.start_mark.line + 1} remote include not followed: {item.value}")
            else:
                locals_.append(item.value.lstrip("/"))
        elif isinstance(item, yaml.MappingNode):
            entries = {k: v for k, _, v in _mapping_entries(loader, item)}
            local = entries.get("local")
            if isinstance(local, yaml.ScalarNode):
                locals_.append(local.value.lstrip("/"))
            else:
                notes.append(f"{path}:{item.start_mark.line + 1} non-local include not followed")
    return locals_


def parse_text(path: str, text: str):
    loader = RefLoader(text)
    try:
        root = loader.get_single_node()
    except yaml.YAMLError as e:
        raise ValueError(f"{path}: invalid YAML: {e}") from None
    jobs, stages, includes, notes = {}, [], [], []
    for name, key_node, value in _mapping_entries(loader, root) if root is not None else []:
        if name == "include":
            includes = _includes(loader, value, notes, path)
        elif name == "stages" and isinstance(value, yaml.SequenceNode):
            stages = [s.value for s in value.value if isinstance(s, yaml.ScalarNode)]
        elif name not in RESERVED and isinstance(value, yaml.MappingNode):
            jobs[name] = JobDef(name, path, key_node, value, loader)
    return jobs, stages, includes, notes


def collect(read: Reader, root: str = DEFAULT_ROOT) -> Config:
    """Read `root` and its local includes (includes first, so the including file wins)."""
    cfg = Config({}, [], {}, [])
    seen: set[str] = set()

    def visit(path: str) -> None:
        if path in seen:
            return
        seen.add(path)
        try:
            text = read(path)
        except OSError as e:
            cfg.notes.append(f"{path}: not readable at the pinned sha ({e})")
            return
        jobs, stages, includes, notes = parse_text(path, text)
        cfg.notes.extend(notes)
        for inc in includes:
            if any(ch in inc for ch in "*?["):
                cfg.notes.append(f"{path}: wildcard include not followed: {inc}")
                continue
            visit(inc)
        if stages:
            cfg.stages = stages
        for name, job in jobs.items():
            if name in cfg.jobs:
                old = cfg.jobs[name]
                cfg.shadowed.setdefault(name, []).append((old.path, old.line))
            cfg.jobs[name] = job

    visit(root)
    if not cfg.jobs:
        raise ValueError(f"no jobs found starting from {root}: " + "; ".join(cfg.notes or ["file is empty"]))
    return cfg


def _norm(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


def resolve_job_name(cfg: Config, name: str) -> str:
    if name in cfg.jobs:
        return name
    same = [j for j in cfg.jobs if _norm(j) == _norm(name)]
    if len(same) == 1:
        return same[0]
    near = difflib.get_close_matches(name, list(cfg.jobs), n=5, cutoff=0.4)
    token = _norm(name)
    subs = [j for j in cfg.jobs if token and (token in _norm(j) or _norm(j) in token) and j not in near]
    raise JobNotFound(name, (same + near + subs)[:8])


def _extends(job: JobDef) -> list:
    found = job.entry("extends")
    if found is None:
        return []
    node = found[1]
    items = node.value if isinstance(node, yaml.SequenceNode) else [node]
    return [(i.value, i.start_mark.line + 1) for i in items if isinstance(i, yaml.ScalarNode)]


def linearize(cfg: Config, name: str, _stack: tuple = ()) -> list:
    """Base-first list of job names whose config merges into `name` (later extends win)."""
    if name in _stack:
        raise ValueError(f"extends cycle: {' -> '.join(_stack + (name,))}")
    out: list[str] = []
    for parent, _ in _extends(cfg.jobs[name]):
        if parent not in cfg.jobs:
            raise ValueError(f"{cfg.jobs[name].path}: {name} extends unknown job {parent!r}")
        for n in linearize(cfg, parent, _stack + (name,)):
            if n not in out:
                out.append(n)
    out.append(name)
    return out


def _defining_job(cfg: Config, name: str, key: str):
    for n in reversed(linearize(cfg, name)):
        if cfg.jobs[n].entry(key) is not None:
            return cfg.jobs[n]
    return None


def _walk_node_value(node: yaml.Node, keys: list) -> yaml.Node | None:
    for key in keys:
        if isinstance(node, yaml.MappingNode):
            node = next((v for k, v in node.value if isinstance(k, yaml.ScalarNode) and k.value == key), None)
        elif isinstance(node, yaml.SequenceNode) and str(key).isdigit() and int(key) < len(node.value):
            node = node.value[int(key)]
        else:
            return None
        if node is None:
            return None
    return node


def _reference_target(cfg: Config, keys: list):
    """(job, node) a !reference [job, key, ...] points at, or None when it dangles."""
    if not keys or keys[0] not in cfg.jobs:
        return None
    job = cfg.jobs[keys[0]]
    node = _walk_node_value(job.node, [str(k) for k in keys[1:]])
    return None if node is None else (job, node)


def _target_line(job: JobDef, keys: list) -> int:
    node, line = job.node, job.line
    for key in keys:
        if not isinstance(node, yaml.MappingNode):
            break
        hit = next(((k, v) for k, v in node.value if isinstance(k, yaml.ScalarNode) and k.value == str(key)), None)
        if hit is None:
            break
        node, line = hit[1], hit[0].start_mark.line + 1
    return line


def _reference_nodes(node: yaml.Node):
    if isinstance(node, yaml.SequenceNode) and node.tag == "!reference":
        yield node
    if isinstance(node, yaml.MappingNode):
        for _, v in node.value:
            yield from _reference_nodes(v)
    elif isinstance(node, yaml.SequenceNode):
        for v in node.value:
            yield from _reference_nodes(v)


def _ref_keys(node: yaml.SequenceNode) -> list:
    return [i.value for i in node.value if isinstance(i, yaml.ScalarNode)]


def _scalar_lines(node: yaml.Node):
    """(text, line) per command line of a script item; block scalars give one pair per line."""
    if not isinstance(node, yaml.ScalarNode):
        return
    base = node.start_mark.line + 1
    if node.style in ("|", ">"):
        for i, text in enumerate(node.value.splitlines()):
            if text.strip():
                yield text.strip(), base + 1 + i
    elif node.value.strip():
        yield node.value.strip(), base


def script_lines(cfg: Config, job: JobDef, key: str, _seen: tuple = ()):
    """(text, path, line) per script command, expanding !reference items to their source."""
    found = job.entry(key)
    if found is None:
        return
    node = found[1]
    items = node.value if isinstance(node, yaml.SequenceNode) and node.tag != "!reference" else [node]
    for item in items:
        if isinstance(item, yaml.SequenceNode) and item.tag == "!reference":
            keys = _ref_keys(item)
            target = _reference_target(cfg, keys)
            marker = tuple(keys)
            if target is None or marker in _seen:
                yield f"!reference {keys} (unresolved)", job.path, item.start_mark.line + 1
                continue
            tjob, tnode = target
            sub = tnode.value if isinstance(tnode, yaml.SequenceNode) else [tnode]
            for s in sub:
                if isinstance(s, yaml.SequenceNode) and s.tag == "!reference":
                    nested = _reference_target(cfg, _ref_keys(s))
                    if nested is not None and tuple(_ref_keys(s)) not in _seen + (marker,):
                        yield from _nested_lines(cfg, nested, _seen + (marker, tuple(_ref_keys(s))))
                    continue
                for text, line in _scalar_lines(s):
                    yield text, tjob.path, line
        else:
            for text, line in _scalar_lines(item):
                yield text, job.path, line


def _nested_lines(cfg: Config, target, seen: tuple):
    tjob, tnode = target
    sub = tnode.value if isinstance(tnode, yaml.SequenceNode) else [tnode]
    for s in sub:
        for text, line in _scalar_lines(s):
            yield text, tjob.path, line


def _needs(cfg: Config, name: str) -> list:
    """(needed job, optional, path, line) from the nearest needs: in the extends chain."""
    src = _defining_job(cfg, name, "needs")
    if src is None:
        return []
    node = src.entry("needs")[1]
    out = []
    for item in node.value if isinstance(node, yaml.SequenceNode) else []:
        if isinstance(item, yaml.ScalarNode):
            out.append((item.value, False, src.path, item.start_mark.line + 1))
        elif isinstance(item, yaml.MappingNode):
            fields = {k: v for k, _, v in _mapping_entries(src.loader, item)}
            job_node = fields.get("job")
            if isinstance(job_node, yaml.ScalarNode):
                opt = fields.get("optional")
                out.append((job_node.value, isinstance(opt, yaml.ScalarNode) and opt.value == "true",
                            src.path, job_node.start_mark.line + 1))
    return out


def _text(node: yaml.Node) -> str:
    return node.value if isinstance(node, yaml.ScalarNode) else ""


def _rule_hops(job: JobDef) -> list:
    found = job.entry("rules")
    if found is None or not isinstance(found[1], yaml.SequenceNode):
        return []
    hops = []
    for rule in found[1].value:
        for key, _, val in _mapping_entries(job.loader, rule):
            if key == "if":
                hops.append(Hop("rules:if", job.path, val.start_mark.line + 1, _text(val).strip()))
            elif key == "changes":
                paths = val if isinstance(val, yaml.SequenceNode) else _walk_node_value(val, ["paths"])
                for p in (paths.value if isinstance(paths, yaml.SequenceNode) else [val]):
                    hops.append(Hop("rules:changes", job.path, p.start_mark.line + 1, _text(p)))
    return hops


def _trigger_hops(job: JobDef) -> list:
    found = job.entry("trigger")
    if found is None:
        return []
    node = found[1]
    if isinstance(node, yaml.ScalarNode):
        return [Hop("trigger", job.path, node.start_mark.line + 1, f"triggers project {node.value}")]
    hops = [Hop("trigger", job.path, found[0].start_mark.line + 1, "triggers a child or downstream pipeline")]
    for key, _, val in _mapping_entries(job.loader, node):
        if key == "project":
            hops.append(Hop("trigger", job.path, val.start_mark.line + 1, f"project {_text(val)}"))
        elif key == "include":
            for inc in val.value if isinstance(val, yaml.SequenceNode) else [val]:
                if isinstance(inc, yaml.ScalarNode):
                    hops.append(Hop("trigger", job.path, inc.start_mark.line + 1, f"include {inc.value}"))
                else:
                    for k2, _, v2 in _mapping_entries(job.loader, inc):
                        if k2 in ("local", "file", "project", "artifact"):
                            hops.append(Hop("trigger", job.path, v2.start_mark.line + 1, f"include {k2}: {_text(v2)}"))
    return hops


def trace(cfg: Config, name: str) -> list:
    """Ordered hops for one job; the first hop is always its definition."""
    name = resolve_job_name(cfg, name)
    job = cfg.jobs[name]
    chain = linearize(cfg, name)
    hops = [Hop("job", job.path, job.line, name, job.end_line)]
    for prior in cfg.shadowed.get(name, []):
        hops.append(Hop("shadowed", prior[0], prior[1], f"{name} is also defined here and overridden"))
    for n in reversed(chain):
        member = cfg.jobs[n]
        for parent, line in _extends(member):
            target = cfg.jobs[parent]
            hops.append(Hop("extends", member.path, line, f"{n} extends {parent}"))
            hops.append(Hop("extends-def", target.path, target.line, parent, target.end_line))
    seen_refs: set = set()
    for n in reversed(chain):
        member = cfg.jobs[n]
        for ref in _reference_nodes(member.node):
            keys = _ref_keys(ref)
            label = "!reference [" + ", ".join(keys) + "]"
            hops.append(Hop("reference", member.path, ref.start_mark.line + 1, f"{n}: {label}"))
            target = _reference_target(cfg, keys)
            if target is None or tuple(keys) in seen_refs:
                if target is None:
                    hops.append(Hop("reference-def", member.path, ref.start_mark.line + 1, f"{label} UNRESOLVED"))
                continue
            seen_refs.add(tuple(keys))
            tjob, tnode = target
            hops.append(Hop("reference-def", tjob.path, _target_line(tjob, keys[1:]), label))
    for key in ("rules", "stage"):
        src = _defining_job(cfg, name, key)
        if src is None:
            continue
        if key == "rules":
            hops.extend(_rule_hops(src))
        else:
            k, v = src.entry("stage")
            hops.append(Hop("stage", src.path, k.start_mark.line + 1, f"stage {_text(v)}"))
    src = _defining_job(cfg, name, "trigger")
    if src is not None:
        hops.extend(_trigger_hops(src))
    needs = _needs(cfg, name)
    for need, optional, path, line in needs:
        known = "" if need in cfg.jobs else " (not defined in the YAML read; may come from an include not followed)"
        hops.append(Hop("needs-up", path, line, f"{name} needs {need}{' (optional)' if optional else ''}{known}"))
    if not needs and _defining_job(cfg, name, "needs") is None:
        hops.append(Hop("needs-up", job.path, job.line, f"no needs: {name} waits for every job in earlier stages"))
    for other in cfg.jobs:
        for need, optional, path, line in _needs(cfg, other):
            if need == name:
                hops.append(Hop("needs-down", path, line, f"{other} needs {name}"))
    for key in SCRIPT_KEYS:
        src = _defining_job(cfg, name, key)
        if src is None:
            continue
        for text, path, line in script_lines(cfg, src, key):
            hops.append(Hop(key, path, line, text))
    return hops


def shell_refs(hops: list) -> list:
    """(script path, hop) for every script line that names a .sh file."""
    out = []
    for h in hops:
        if h.kind in SCRIPT_KEYS:
            for m in SH_REF_RE.finditer(h.text):
                out.append((re.sub(r"^(?:\$\{?[A-Z_]+\}?/|\./)", "", m.group(1)), h))
    return out


def find_functions(text: str) -> dict:
    return {m.group(1): text[: m.start()].count("\n") + 1 for m in FUNC_DEF_RE.finditer(text)}


def follow_scripts(hops: list, read: Reader) -> list:
    """Hops for the shell script each script line runs and the functions those lines call."""
    out: list[Hop] = []
    done: set = set()
    for path, origin in shell_refs(hops):
        if path in done:
            continue
        done.add(path)
        try:
            text = read(path)
        except OSError as e:
            out.append(Hop("shell-missing", origin.path, origin.line, f"{path} not readable at the pinned sha ({e})"))
            continue
        out.append(Hop("shell", path, 1, f"runs {path} (from {origin.path}:{origin.line})"))
        words = {w for h in hops if h.kind in SCRIPT_KEYS for w in re.findall(r"[A-Za-z_][\w-]*", h.text)}
        for fn, line in find_functions(text).items():
            if fn in words:
                out.append(Hop("shell-fn", path, line, f"function {fn}"))
    return out


def _effective(cfg: Config, name: str) -> dict:
    out: dict = {}
    for n in linearize(cfg, name):
        job = cfg.jobs[n]
        for key, k_node, _ in _mapping_entries(job.loader, job.node):
            if key == "extends":
                continue
            out[key] = (_expand(cfg, job.value(key)), job.path, k_node.start_mark.line + 1)
    return out


def _expand(cfg: Config, value, _seen: tuple = ()):
    if isinstance(value, Reference):
        target = _reference_target(cfg, [str(k) for k in value])
        if target is None or tuple(value) in _seen:
            return f"!reference {list(value)} (unresolved)"
        tjob, _ = target
        cur = tjob.value(value[1]) if len(value) > 1 else None
        for key in value[2:]:
            cur = cur.get(key) if isinstance(cur, dict) else None
        return _expand(cfg, cur, _seen + (tuple(value),))
    if isinstance(value, list):
        out = []
        for item in value:
            exp = _expand(cfg, item, _seen)
            if isinstance(item, Reference) and isinstance(exp, list):
                out.extend(exp)
            else:
                out.append(exp)
        return out
    if isinstance(value, dict):
        return {k: _expand(cfg, v, _seen) for k, v in value.items()}
    return value


def diff_variants(cfg: Config, a: str, b: str) -> list:
    """Rows (key, a value, a path:line, b value, b path:line) where the merged configs differ."""
    a, b = resolve_job_name(cfg, a), resolve_job_name(cfg, b)
    ea, eb = _effective(cfg, a), _effective(cfg, b)
    rows = []
    for key in sorted(set(ea) | set(eb)):
        va, vb = ea.get(key), eb.get(key)
        if (va and va[0]) != (vb and vb[0]):
            rows.append((key, va and va[0], va and f"{va[1]}:{va[2]}", vb and vb[0], vb and f"{vb[1]}:{vb[2]}"))
    return rows


def render_trace(hops: list, host: str, project: str, sha: str) -> str:
    out = []
    for h in hops:
        url = blob_url(host, project, sha, h.path, h.line, h.end)
        out.append(f"{h.kind:<14} {h.path}:{h.line}  {h.text}\n{'':<14} {url}")
    return "\n".join(out)


def render_diff(rows: list, a: str, b: str) -> str:
    if not rows:
        return f"{a} and {b} have identical merged config"
    out = [f"{len(rows)} key(s) differ between {a} and {b}"]
    for key, va, la, vb, lb in rows:
        out.append(f"{key}\n  {a}: {va!r}  ({la})\n  {b}: {vb!r}  ({lb})")
    return "\n".join(out)


def cited_urls(hops: list, host: str, project: str, sha: str) -> list:
    urls: list[str] = []
    for h in hops:
        url = blob_url(host, project, sha, h.path, h.line, h.end)
        if url not in urls:
            urls.append(url)
    return urls


def open_in_chrome(urls: list, runner=subprocess.run) -> None:
    for url in urls:
        runner(["open", "-a", "Google Chrome", url], check=True)


def git_reader(repo: str, sha: str) -> Reader:
    def read(path: str) -> str:
        proc = subprocess.run(["git", "-C", repo, "show", f"{sha}:{path}"], capture_output=True, text=True)
        if proc.returncode != 0:
            raise OSError(proc.stderr.strip() or f"git show {sha}:{path} failed")
        return proc.stdout

    return read


def api_reader(host: str, project: str, sha: str, token: str) -> Reader:
    def read(path: str) -> str:
        url = (f"{host.rstrip('/')}/api/v4/projects/{quote(project, safe='')}/repository/files/"
               f"{quote(path, safe='')}/raw?ref={sha}")
        req = urllib.request.Request(url, headers={"PRIVATE-TOKEN": token})
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                return resp.read().decode()
        except urllib.error.HTTPError as e:
            raise OSError(f"HTTP {e.code} for {path} at {sha}") from None
        except urllib.error.URLError as e:
            raise OSError(f"{e.reason} for {path} at {sha}") from None

    return read


def job_proof(host: str, project: str, job: str, job_ids: list, token: str, get=None) -> dict:
    """One real run of the job (URL and duration), through ci_job_timing's GitLab reader."""
    sibling = Path(__file__).resolve().parents[2] / "ci-job-timing" / "scripts"
    sys.path.insert(0, str(sibling))
    try:
        import ci_job_timing
    except ImportError as e:
        raise OSError(f"ci-job-timing helper not found next to this skill ({sibling}): {e}") from None
    finally:
        sys.path.remove(str(sibling))
    kwargs = {"job_ids": job_ids}
    if get is not None:
        kwargs["get"] = get
    _, by_pipeline = ci_job_timing.fetch_context_inputs(host, project, job, 1, token, **kwargs)
    runs = [j for jobs in by_pipeline.values() for j in jobs if j.get("name") == job and j.get("status") == "success"]
    if not runs:
        raise ValueError(f"no successful run of {job!r} among job ids {job_ids}")
    run = max(runs, key=lambda j: j["id"])
    return {"id": run["id"], "web_url": run["web_url"], "duration_s": run.get("duration")}


def _source(a) -> tuple:
    if not SHA_RE.match(a.sha or ""):
        raise ValueError(f"--sha must be a 7-40 character hex commit id (a branch name moves), got {a.sha!r}")
    host = a.gitlab_host.rstrip("/")
    if a.repo:
        return host, git_reader(a.repo, a.sha)
    token = os.environ.get(TOKEN_ENV)
    if not token:
        raise PermissionError(f"{TOKEN_ENV} is not set; pass --repo for a local clone or export a GitLab read_api token")
    return host, api_reader(host, a.project, a.sha, token)


def main(argv: list | None = None, runner=subprocess.run) -> int:
    if not YAML_AVAILABLE:
        print(YAML_ERROR, file=sys.stderr)
        return 2
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("trace", "diff"):
        p = sub.add_parser(name)
        p.add_argument("--job", required=True)
        p.add_argument("--sha", required=True, help="commit SHA to read; branch names are refused")
        p.add_argument("--repo", help="local clone read with git show SHA:path (default: GitLab files API)")
        p.add_argument("--root", default=DEFAULT_ROOT)
        p.add_argument("--gitlab-host", default=DEFAULT_GITLAB)
        p.add_argument("--project", default=DEFAULT_PROJECT, required=DEFAULT_PROJECT is None,
                       help="GitLab project path (default: $GITLAB_PROJECT)")
    pt = sub.choices["trace"]
    pt.add_argument("--follow-scripts", action="store_true")
    pt.add_argument("--open", action="store_true", help="open every cited line in Google Chrome")
    sub.choices["diff"].add_argument("--other", required=True, help="the variant to compare against")
    pp = sub.add_parser("proof")
    pp.add_argument("--job", required=True)
    pp.add_argument("--job-ids", required=True, help="comma-separated job numbers from Datadog")
    pp.add_argument("--gitlab-host", default=DEFAULT_GITLAB)
    pp.add_argument("--project", default=DEFAULT_PROJECT, required=DEFAULT_PROJECT is None,
                       help="GitLab project path (default: $GITLAB_PROJECT)")
    a = ap.parse_args(argv)
    try:
        if a.cmd == "proof":
            token = os.environ.get(TOKEN_ENV)
            if not token:
                raise PermissionError(f"{TOKEN_ENV} is not set; export a GitLab read_api token")
            ids = [int(x) for x in a.job_ids.split(",") if x.strip()]
            r = job_proof(a.gitlab_host.rstrip("/"), a.project, a.job, ids, token)
            print(f"job {r['id']}  {r['web_url']}  duration {r['duration_s']} s")
            return 0
        host, read = _source(a)
        cfg = collect(read, a.root)
        for note in cfg.notes:
            print(f"note: {note}", file=sys.stderr)
        if a.cmd == "diff":
            print(render_diff(diff_variants(cfg, a.job, a.other), a.job, a.other))
            return 0
        hops = trace(cfg, a.job)
        if a.follow_scripts:
            hops += follow_scripts(hops, read)
        resolved = hops[0].text
        if resolved != a.job:
            print(f"resolved {a.job!r} -> {resolved!r}")
        print(render_trace(hops, host, a.project, a.sha))
        if a.open:
            open_in_chrome(cited_urls(hops, host, a.project, a.sha), runner)
        return 0
    except JobNotFound as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    except (ValueError, OSError, PermissionError, subprocess.CalledProcessError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
