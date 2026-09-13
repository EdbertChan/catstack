from __future__ import annotations

import argparse
import ast
import tempfile
from pathlib import Path

LOGGER_METHODS = {
    "critical",
    "debug",
    "error",
    "exception",
    "info",
    "log",
    "warn",
    "warning",
}

PROMISED_CATCH = (
    "silent-exception",
    "silent-bare",
)
PROMISED_ALLOW = (
    "narrow-oserror",
    "stderr-print",
    "reraises",
    "logger-call",
)
PROMISED_FIXTURES = {
    "silent-exception": "def main():\n    try:\n        run()\n    except Exception:\n        return\n",
    "silent-bare": "def main():\n    try:\n        run()\n    except:\n        return\n",
    "narrow-oserror": "def main():\n    try:\n        run()\n    except OSError:\n        return\n",
    "stderr-print": (
        "import sys\n\n"
        "def main():\n"
        "    try:\n"
        "        run()\n"
        "    except Exception as exc:\n"
        "        print(f\"catstack-hook-error demo: {type(exc).__name__}: {exc}\", file=sys.stderr)\n"
        "        return\n"
    ),
    "reraises": "def main():\n    try:\n        run()\n    except Exception:\n        raise\n",
    "logger-call": (
        "import logging\n\n"
        "LOGGER = logging.getLogger(__name__)\n\n"
        "def main():\n"
        "    try:\n"
        "        run()\n"
        "    except Exception as exc:\n"
        "        LOGGER.exception(\"hook failed: %s\", exc)\n"
    ),
}


class HandlerResult:
    def __init__(self, path: Path, handler: ast.ExceptHandler) -> None:
        self.path = path
        self.handler = handler


class ScanResult:
    def __init__(self, checked: int, silent: list[HandlerResult], unchecked: list[str]) -> None:
        self.checked = checked
        self.silent = silent
        self.unchecked = unchecked

    def exit_code(self) -> int:
        if self.silent:
            return 1
        if self.unchecked:
            return 2
        return 0


def hook_files(root: Path) -> list[Path]:
    hooks = root / "engine" / "hooks"
    if not hooks.is_dir():
        return []
    found = []
    for path in sorted(hooks.rglob("*.py")):
        parts = path.relative_to(hooks).parts
        if "tests" in parts or parts[0] == "_runner":
            continue
        found.append(path)
    return found


def flags_exemplar(exemplar: str) -> bool:
    source = PROMISED_FIXTURES[exemplar]
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        path = root / "engine" / "hooks" / "demo" / "hook.py"
        path.parent.mkdir(parents=True)
        path.write_text(source, encoding="utf-8")
        return bool(scan(root).silent)


def is_broad_type(node: ast.AST | None) -> bool:
    if node is None:
        return True
    if isinstance(node, ast.Name):
        return node.id in {"BaseException", "Exception"}
    if isinstance(node, ast.Tuple):
        return any(is_broad_type(elt) for elt in node.elts)
    return False


def logging_names(tree: ast.Module) -> tuple[set[str], set[str]]:
    modules = set()
    loggers = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "logging":
                    modules.add(alias.asname or alias.name)
        elif isinstance(node, ast.Assign) and is_logging_get_logger(node.value, modules | {"logging"}):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    loggers.add(target.id)
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            if is_logging_get_logger(node.value, modules | {"logging"}) and isinstance(node.target, ast.Name):
                loggers.add(node.target.id)
    return modules | {"logging"}, loggers


def is_logging_get_logger(node: ast.AST, modules: set[str]) -> bool:
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "getLogger"
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id in modules
    )


class BodySignalVisitor(ast.NodeVisitor):
    def __init__(self, logging_modules: set[str], logger_names: set[str]) -> None:
        self.logging_modules = logging_modules
        self.logger_names = logger_names
        self.has_signal = False

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        return

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        return

    def visit_Lambda(self, node: ast.Lambda) -> None:
        return

    def visit_Raise(self, node: ast.Raise) -> None:
        self.has_signal = True

    def visit_Call(self, node: ast.Call) -> None:
        if is_stderr_print(node) or is_stderr_write(node) or is_logger_call(
            node, self.logging_modules, self.logger_names
        ):
            self.has_signal = True
            return
        self.generic_visit(node)


def is_sys_stderr(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Attribute)
        and node.attr == "stderr"
        and isinstance(node.value, ast.Name)
        and node.value.id == "sys"
    )


def is_stderr_print(node: ast.Call) -> bool:
    if not isinstance(node.func, ast.Name) or node.func.id != "print":
        return False
    return any(keyword.arg == "file" and is_sys_stderr(keyword.value) for keyword in node.keywords)


def is_stderr_write(node: ast.Call) -> bool:
    return (
        isinstance(node.func, ast.Attribute)
        and node.func.attr == "write"
        and is_sys_stderr(node.func.value)
    )


def is_logger_call(node: ast.Call, logging_modules: set[str], logger_names: set[str]) -> bool:
    if not isinstance(node.func, ast.Attribute) or node.func.attr not in LOGGER_METHODS:
        return False
    if isinstance(node.func.value, ast.Name):
        return node.func.value.id in logging_modules or node.func.value.id in logger_names
    return False


def has_signal(handler: ast.ExceptHandler, logging_modules: set[str], logger_names: set[str]) -> bool:
    visitor = BodySignalVisitor(logging_modules, logger_names)
    for node in handler.body:
        visitor.visit(node)
    return visitor.has_signal


def scan(root: Path) -> ScanResult:
    silent = []
    unchecked = []
    checked = 0
    for path in hook_files(root):
        checked += 1
        try:
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(path))
        except (OSError, SyntaxError) as exc:
            unchecked.append(f"unchecked: {path}: {exc}")
            continue
        logging_modules, logger_names = logging_names(tree)
        for node in ast.walk(tree):
            if isinstance(node, ast.ExceptHandler) and is_broad_type(node.type):
                if not has_signal(node, logging_modules, logger_names):
                    silent.append(HandlerResult(path, node))
    return ScanResult(checked, silent, unchecked)


def print_result(result: ScanResult) -> None:
    for hit in result.silent:
        print(f"{hit.path}:{hit.handler.lineno}: silent broad exception handler")
    for item in result.unchecked:
        print(item)
    print(f"checked {result.checked} file(s)")


def has_import_sys(tree: ast.Module) -> bool:
    for node in tree.body:
        if isinstance(node, ast.Import):
            if any(alias.name == "sys" and alias.asname is None for alias in node.names):
                return True
    return False


def import_sys_index(tree: ast.Module, lines: list[str]) -> int:
    index = 0
    if lines and lines[0].startswith("#!"):
        index = 1
    body = list(tree.body)
    if body and isinstance(body[0], ast.Expr):
        value = body[0].value
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            index = max(index, body[0].end_lineno or body[0].lineno)
            body = body[1:]
    for node in body:
        if isinstance(node, ast.ImportFrom) and node.module == "__future__":
            index = max(index, node.end_lineno or node.lineno)
            continue
        break
    return index


def find_header_colon(line: str, col: int) -> int:
    colon = line.find(":", col)
    if colon < 0:
        raise ValueError("except header has no colon")
    return colon


def bound_header(line: str, handler: ast.ExceptHandler) -> tuple[str, str]:
    colon = find_header_colon(line, handler.col_offset)
    head = line[:colon].rstrip()
    tail = line[colon + 1 :]
    if handler.name:
        return line[: colon + 1], tail
    if handler.type is None:
        replacement = line[: handler.col_offset] + "except BaseException as exc"
    else:
        replacement = head + " as exc"
    return replacement + ":", tail


def body_indent(lines: list[str], handler: ast.ExceptHandler) -> str:
    first = handler.body[0]
    if first.lineno != handler.lineno:
        line = lines[first.lineno - 1]
        return line[: len(line) - len(line.lstrip())]
    return lines[handler.lineno - 1][: handler.col_offset] + "    "


def hook_name(root: Path, path: Path) -> str:
    hooks = root / "engine" / "hooks"
    return path.relative_to(hooks).parts[0]


def fix_file(root: Path, path: Path, handlers: list[ast.ExceptHandler]) -> None:
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))
    lines = source.splitlines(keepends=True)
    for handler in sorted(handlers, key=lambda item: (item.lineno, item.col_offset), reverse=True):
        line_index = handler.lineno - 1
        header, tail = bound_header(lines[line_index], handler)
        indent = body_indent(lines, handler)
        exc_name = handler.name or "exc"
        text = f'{indent}print(f"catstack-hook-error {hook_name(root, path)}: {{type({exc_name}).__name__}}: {{{exc_name}}}", file=sys.stderr)\n'
        if tail.strip():
            ending = "\n" if lines[line_index].endswith("\n") else ""
            original_tail = tail.strip()
            lines[line_index] = header + ending
            lines.insert(line_index + 1, text)
            lines.insert(line_index + 2, f"{indent}{original_tail}\n")
        else:
            lines[line_index] = header + tail
            insert_at = handler.body[0].lineno - 1
            lines.insert(insert_at, text)
    if not has_import_sys(tree):
        lines.insert(import_sys_index(tree, lines), "import sys\n")
    path.write_text("".join(lines), encoding="utf-8")


def apply_fix(root: Path, result: ScanResult) -> None:
    by_path: dict[Path, list[ast.ExceptHandler]] = {}
    for hit in result.silent:
        by_path.setdefault(hit.path, []).append(hit.handler)
    for path, handlers in by_path.items():
        fix_file(root, path, handlers)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fix", action="store_true")
    parser.add_argument("--root", default=Path(__file__).resolve().parents[1])
    args = parser.parse_args(argv)
    root = Path(args.root).resolve()
    result = scan(root)
    if args.fix and result.silent:
        apply_fix(root, result)
        result = scan(root)
    print_result(result)
    return result.exit_code()


if __name__ == "__main__":
    raise SystemExit(main())
