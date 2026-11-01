#!/usr/bin/env python3
"""Packs a page's data and adds a Save-for-everyone button that keeps the page's settings in the artifact database."""
from __future__ import annotations

import argparse
import base64
import gzip
import json
import re
import sys
from pathlib import Path

TEMPLATES = Path(__file__).resolve().parent / "templates"
ARTIFACT_LIMIT_BYTES = 16 * 1024 * 1024
BRIDGE_REGION = ("<!-- saveable-artifact:bridge:start -->", "<!-- saveable-artifact:bridge:end -->")
DATA_REGION = ("<!-- saveable-artifact:data:start -->", "<!-- saveable-artifact:data:end -->")
BUTTON_REGION = ("<!-- saveable-artifact:button:start -->", "<!-- saveable-artifact:button:end -->")
BUTTON_ANCHOR = '<span data-saveable-artifact="button"></span>'
BUTTON_HTML = (
    '<button type="button" id="saveable-button" title="Save these settings for everyone who opens this page">Save for everyone</button> '
    '<span id="saveable-note" role="status"></span>'
)
UNPACK_LOADER = (
    "<script>\n"
    "async function unpackDataBlock(blockId) {\n"
    "  const bytes = Uint8Array.from(atob(document.getElementById(blockId).textContent), character => character.charCodeAt(0));\n"
    '  return JSON.parse(await new Response(new Blob([bytes]).stream().pipeThrough(new DecompressionStream("gzip"))).text());\n'
    "}\n"
    "</script>"
)
DATA_BLOCK = re.compile(r'<script id="([^"]+)" type="text/plain">([A-Za-z0-9+/=]*)</script>')
FIXED_WAIT = re.compile(r"setTimeout|setInterval|\bsleep\s*\(")
SAVED_PAGE_CONTRACT = re.compile(r"window\.savedPage\s*=")
PRESET_GUARD = "window.savedPageSettings"


def pack_block(name: str, document) -> str:
    raw = json.dumps(document, separators=(",", ":")).encode("utf-8")
    encoded = base64.b64encode(gzip.compress(raw, 9)).decode("ascii")
    return f'<script id="{name}" type="text/plain">{encoded}</script>'


def unpack_block(encoded: str):
    return json.loads(gzip.decompress(base64.b64decode(encoded)))


def replace_region(page: str, region: tuple[str, str], body: str, anchor: str) -> str:
    start, end = region
    block = f"{start}\n{body}\n{end}"
    if start in page:
        if page.count(start) != 1 or page.count(end) != 1:
            raise SystemExit(f"saveable-artifact: expected one {start} region, found {page.count(start)}")
        before, rest = page.split(start, 1)
        return before + block + rest.split(end, 1)[1]
    position = page.rfind(anchor)
    if position < 0:
        raise SystemExit(f"saveable-artifact: no {anchor} in the page to place the region before")
    return page[:position] + block + "\n" + page[position:]


def add_data_blocks(page: str, blocks: dict) -> str:
    if not blocks:
        raise SystemExit("saveable-artifact: no data blocks given")
    body = UNPACK_LOADER + "\n" + "\n".join(pack_block(name, document) for name, document in blocks.items())
    return replace_region(page, DATA_REGION, body, "<script")


def template_text(name: str, **values: str) -> str:
    text = (TEMPLATES / name).read_text(encoding="utf-8")
    for key, value in values.items():
        placeholder = f"__{key.upper()}__"
        if placeholder not in text:
            raise SystemExit(f"saveable-artifact: {name} has no {placeholder}")
        text = text.replace(placeholder, value)
    leftover = re.findall(r"__[A-Z_]+__", text)
    if leftover:
        raise SystemExit(f"saveable-artifact: {name} still has {leftover[0]}")
    return text


def add_bridge(page: str, mode: str, settings_path: str, ready_function: str) -> str:
    if mode == "standalone":
        script = template_text("standalone_bridge.js", settings_path=settings_path, ready_function=ready_function)
    elif mode == "hosted":
        script = template_text("hosted_bridge.js", ready_function=ready_function)
    else:
        raise SystemExit(f"saveable-artifact: mode must be standalone or hosted, not {mode}")
    with_button = place_button(page)
    return replace_region(with_button, BRIDGE_REGION, f"<script>\n{script}</script>", "</body>")


def place_button(page: str) -> str:
    if BUTTON_ANCHOR in page:
        start, end = BUTTON_REGION
        return page.replace(BUTTON_ANCHOR, f"{start}\n{BUTTON_HTML}\n{end}", 1)
    return replace_region(page, BUTTON_REGION, BUTTON_HTML, "</body>")


def add_parent_bridge(host_page: str, frame_id: str, settings_path: str) -> str:
    script = template_text("parent_bridge.js", frame_id=frame_id, settings_path=settings_path)
    return replace_region(host_page, ("<!-- saveable-artifact:parent:start -->", "<!-- saveable-artifact:parent:end -->"), f"<script>\n{script}</script>", "</body>")


def outside_region(page: str, region: tuple[str, str]) -> str:
    start, end = region
    if start not in page:
        return page
    before, rest = page.split(start, 1)
    return before + rest.split(end, 1)[1]


def problems(page: str, limit_bytes: int = ARTIFACT_LIMIT_BYTES, expect_preset_guard: bool = True) -> list[str]:
    found: list[str] = []
    size = len(page.encode("utf-8"))
    if size > limit_bytes:
        found.append(f"the page is {size} bytes, over the {limit_bytes} byte limit")
    if page.count('id="saveable-button"') != 1 or page.count('id="saveable-note"') != 1:
        found.append("the page needs exactly one saveable-button and one saveable-note")
    start, end = BRIDGE_REGION
    if page.count(start) != 1 or page.count(end) != 1:
        found.append("the page needs exactly one saveable-artifact bridge region")
    else:
        bridge = page.split(start, 1)[1].split(end, 1)[0]
        wait = FIXED_WAIT.search(bridge)
        if wait:
            found.append(f"the bridge uses a timer ({wait.group(0)}); saved settings must apply the moment the page is ready")
    rest = outside_region(page, BRIDGE_REGION)
    if not SAVED_PAGE_CONTRACT.search(rest):
        found.append("the page never sets window.savedPage = { snapshot, apply }")
    if expect_preset_guard and PRESET_GUARD not in rest:
        found.append("no page code reads window.savedPageSettings; code that applies defaults must return when it is set")
    for name, encoded in DATA_BLOCK.findall(page):
        try:
            unpack_block(encoded)
        except (ValueError, OSError, EOFError) as error:
            found.append(f"data block {name} does not unpack: {error}")
    return found


def read_page(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


def write_page(path: str, page: str) -> None:
    Path(path).write_text(page, encoding="utf-8")
    print(f"wrote {path}: {len(page.encode('utf-8'))} bytes")


def parse_blocks(specs: list[str]) -> dict:
    blocks = {}
    for spec in specs:
        name, separator, path = spec.partition("=")
        if not separator or not name or not path:
            raise SystemExit(f"saveable-artifact: --data wants NAME=path.json, got {spec}")
        blocks[name] = json.loads(Path(path).read_text(encoding="utf-8"))
    return blocks


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    pack = commands.add_parser("pack", help="embed JSON files as gzip+base64 data blocks")
    pack.add_argument("--page", required=True)
    pack.add_argument("--data", action="append", default=[], metavar="NAME=path.json")
    pack.add_argument("--out", required=True)
    bridge = commands.add_parser("bridge", help="add the save button and the save/load script to the page")
    bridge.add_argument("--page", required=True)
    bridge.add_argument("--mode", choices=("standalone", "hosted"), required=True)
    bridge.add_argument("--settings-path", default="page/settings")
    bridge.add_argument("--ready-function", required=True, help="global function the page calls once its board is drawn")
    bridge.add_argument("--out", required=True)
    parent = commands.add_parser("parent", help="add the database bridge to the page that embeds the hosted page")
    parent.add_argument("--page", required=True)
    parent.add_argument("--frame-id", required=True)
    parent.add_argument("--settings-path", default="page/settings")
    parent.add_argument("--out", required=True)
    check = commands.add_parser("check", help="fail when the page breaks the saveable-artifact rules")
    check.add_argument("--page", required=True)
    check.add_argument("--max-bytes", type=int, default=ARTIFACT_LIMIT_BYTES)
    check.add_argument("--no-preset", action="store_true", help="the page has no defaults that could overwrite saved settings")
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    if arguments.command == "pack":
        write_page(arguments.out, add_data_blocks(read_page(arguments.page), parse_blocks(arguments.data)))
    elif arguments.command == "bridge":
        write_page(arguments.out, add_bridge(read_page(arguments.page), arguments.mode, arguments.settings_path, arguments.ready_function))
    elif arguments.command == "parent":
        write_page(arguments.out, add_parent_bridge(read_page(arguments.page), arguments.frame_id, arguments.settings_path))
    else:
        found = problems(read_page(arguments.page), arguments.max_bytes, not arguments.no_preset)
        for line in found:
            print(f"PROBLEM {line}")
        print(f"checked {arguments.page}: {len(found)} problem(s)")
        return 1 if found else 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
