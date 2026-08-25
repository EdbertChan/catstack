#!/usr/bin/env python3
"""Enforce engine / corpus / product layout boundaries.

Rules (fail closed):
1. No top-level skills/ or hooks/ package trees (moved under engine|corpus|product).
2. Every */skills/*/SKILL.md lives under engine/, corpus/, or product/.
3. engine/skills/ allowlist only (factory skills).
4. corpus/skills/ must not contain engine allowlist names; principle-* / *-mode only in corpus.
5. No Python under engine/ may reference corpus/skills or product/skills path strings.
6. hooks/ only under engine/hooks/.
7. Product skills with a domains/ directory: SKILL.md MUST include the domain
   selector phrase; generic SKILL.md MUST NOT name repo CLIs; each domains/<type>.md
   MUST NOT name CLIs owned by a different domain type.

Usage:
    python3 scripts/check_ecosystem_boundaries.py
"""
from __future__ import annotations

import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

ENGINE_SKILL_ALLOWLIST = frozenset(
    {
        "reflect",
        "automate-me",
        "create-skill",
        "draft-pr",
        "make-pr",
        "thrash-reflect-automate",
    }
)

SKILL_BUCKETS = ("engine", "corpus", "product")

# Paste this into every domain-aware product SKILL.md (see create-skill).
DOMAIN_SELECTOR_PHRASE = "read **at most one** sibling `domains/<type>.md`"

# Must not appear in generic SKILL.md when domains/ exists.
GENERIC_BANNED_REPO_CLIS = (
    "run_sandbox.sh",
    "run_company.sh",
    "grade_holdings_sheet.py",
    "export_equity_holdings_sheets.py",
    "normalize_parent",
)

# CLIs owned by one domain — other domains' files must not mention them.
DOMAIN_OWNED_CLIS: dict[str, tuple[str, ...]] = {
    "equities": (
        "grade_holdings_sheet.py",
        "export_equity_holdings_sheets.py",
        "normalize_parent",
    ),
    "coding": (
        "run_all_tests.sh",
    ),
}


def _skill_dirs(bucket: str, repo_root: str) -> list[str]:
    root = os.path.join(repo_root, bucket, "skills")
    if not os.path.isdir(root):
        return []
    return sorted(
        name
        for name in os.listdir(root)
        if os.path.isdir(os.path.join(root, name)) and not name.startswith(".")
    )


def _py_files_under(root: str) -> list[str]:
    out: list[str] = []
    for dirpath, _dirnames, filenames in os.walk(root):
        if "__pycache__" in dirpath or "/.worktrees/" in dirpath.replace("\\", "/"):
            continue
        for name in filenames:
            if name.endswith(".py"):
                out.append(os.path.join(dirpath, name))
    return out


def _read_text(path: str) -> str:
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def check_product_domains(repo_root: str) -> list[str]:
    """Validate domains/ layout for product skills that opt in."""
    errors: list[str] = []
    product_root = os.path.join(repo_root, "product", "skills")
    if not os.path.isdir(product_root):
        return errors

    for name in _skill_dirs("product", repo_root):
        skill_dir = os.path.join(product_root, name)
        domains_dir = os.path.join(skill_dir, "domains")
        if not os.path.isdir(domains_dir):
            continue

        skill_md = os.path.join(skill_dir, "SKILL.md")
        if not os.path.isfile(skill_md):
            continue
        try:
            skill_text = _read_text(skill_md)
        except OSError as exc:
            errors.append(f"product/skills/{name}/SKILL.md: {exc}")
            continue

        if DOMAIN_SELECTOR_PHRASE not in skill_text:
            errors.append(
                f"product/skills/{name}/SKILL.md: domain-aware skill missing "
                f"selector phrase {DOMAIN_SELECTOR_PHRASE!r}"
            )

        for cli in GENERIC_BANNED_REPO_CLIS:
            if cli in skill_text:
                errors.append(
                    f"product/skills/{name}/SKILL.md: generic skill must not "
                    f"name repo CLI {cli!r} (put it under domains/)"
                )

        for domain_file in sorted(os.listdir(domains_dir)):
            if not domain_file.endswith(".md"):
                continue
            domain_type = domain_file[: -len(".md")]
            path = os.path.join(domains_dir, domain_file)
            try:
                domain_text = _read_text(path)
            except OSError as exc:
                errors.append(f"product/skills/{name}/domains/{domain_file}: {exc}")
                continue

            for other_type, clis in DOMAIN_OWNED_CLIS.items():
                if other_type == domain_type:
                    continue
                for cli in clis:
                    if cli in domain_text:
                        errors.append(
                            f"product/skills/{name}/domains/{domain_file}: "
                            f"must not name {other_type}-owned CLI {cli!r}"
                        )

    return errors


def check(repo_root: str | None = None) -> list[str]:
    root = repo_root or REPO_ROOT
    errors: list[str] = []

    flat_skills = os.path.join(root, "skills")
    if os.path.isdir(flat_skills):
        kids = [
            n
            for n in os.listdir(flat_skills)
            if os.path.isdir(os.path.join(flat_skills, n)) and not n.startswith(".")
        ]
        if kids:
            errors.append(
                "top-level skills/ must not contain skill packages (use engine|corpus|product)"
            )

    flat_hooks = os.path.join(root, "hooks")
    if os.path.isdir(flat_hooks):
        kids = [
            n
            for n in os.listdir(flat_hooks)
            if os.path.isdir(os.path.join(flat_hooks, n)) and not n.startswith(".")
        ]
        if kids:
            errors.append("top-level hooks/ must not contain hook packages (use engine/hooks/)")

    for bucket in SKILL_BUCKETS:
        sroot = os.path.join(root, bucket, "skills")
        if not os.path.isdir(sroot):
            errors.append(f"missing {bucket}/skills/")
            continue
        for name in _skill_dirs(bucket, root):
            skill_md = os.path.join(sroot, name, "SKILL.md")
            if not os.path.isfile(skill_md):
                errors.append(f"{bucket}/skills/{name}: missing SKILL.md")

    engine_names = set(_skill_dirs("engine", root))
    extra = engine_names - ENGINE_SKILL_ALLOWLIST
    if extra:
        errors.append(f"engine/skills/ has non-allowlisted packages: {sorted(extra)}")
    missing = ENGINE_SKILL_ALLOWLIST - engine_names
    if missing:
        errors.append(f"engine/skills/ missing required packages: {sorted(missing)}")

    corpus_names = set(_skill_dirs("corpus", root))
    overlap = corpus_names & ENGINE_SKILL_ALLOWLIST
    if overlap:
        errors.append(f"corpus/skills/ must not contain engine packages: {sorted(overlap)}")

    product_names = set(_skill_dirs("product", root))
    bad_prod = product_names & ENGINE_SKILL_ALLOWLIST
    if bad_prod:
        errors.append(f"product/skills/ must not contain engine packages: {sorted(bad_prod)}")
    for name in product_names:
        if name.startswith("principle-") or name.endswith("-mode"):
            errors.append(f"product/skills/{name}: principle-* and *-mode belong in corpus/")

    for name in corpus_names:
        if name in product_names or name in engine_names:
            errors.append(f"skill name {name!r} appears in more than one bucket")

    hooks_root = os.path.join(root, "engine", "hooks")
    if not os.path.isdir(hooks_root):
        errors.append("missing engine/hooks/")

    for eroot in (
        os.path.join(root, "engine", "hooks"),
        os.path.join(root, "engine", "skills"),
    ):
        if not os.path.isdir(eroot):
            continue
        for path in _py_files_under(eroot):
            try:
                with open(path, encoding="utf-8") as handle:
                    text = handle.read()
            except OSError as exc:
                errors.append(f"{path}: {exc}")
                continue
            if "corpus/skills" in text or "product/skills" in text:
                rel = os.path.relpath(path, root).replace("\\", "/")
                # auto-pr watches those path prefixes; that is not a runtime import.
                if rel.endswith("auto-pr/detect.py") and "RELEVANT_PREFIXES" in text:
                    continue
                errors.append(
                    f"{rel}: engine Python must not reference corpus/skills or product/skills"
                )

    errors.extend(check_product_domains(root))
    return errors


def main() -> int:
    errors = check()
    if errors:
        for err in errors:
            print(f"fail  {err}", file=sys.stderr)
        return 1
    print("ok      ecosystem boundaries")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
