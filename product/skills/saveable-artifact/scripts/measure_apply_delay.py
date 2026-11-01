#!/usr/bin/env python3
"""Measures, in headless Chrome, how long a saved setting takes to show once the page has it."""
from __future__ import annotations

import argparse
import functools
import http.server
import json
import re
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

CHROME_MACOS = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
RESULT = re.compile(r'<pre id="saveable-result">([^<]*)</pre>')
POLL_MILLISECONDS = 10
POLL_COUNT = 1200

HOSTED_PARENT = """<!doctype html><meta charset="utf-8"><body><iframe id="frame" style="width:1200px;height:800px"></iframe><pre id="saveable-result">running</pre>
<script>
const query = new URLSearchParams(location.search), arrival = Number(query.get("arrival")), page = query.get("page");
const SAVED = __SAVED__;
const frame = document.getElementById("frame");
let sentAt = null, appliedAt = null, polls = 0;
window.addEventListener("message", event => {
  if (event.source !== frame.contentWindow || !event.data || event.data.kind !== "saveable-load-request") return;
  if (arrival < 0) { frame.contentWindow.postMessage({ kind: "saveable-none" }, "*"); return; }
  setTimeout(() => { sentAt = performance.now(); frame.contentWindow.postMessage({ kind: "saveable-loaded", saved: SAVED, savedAt: "2026-01-01T00:00:00Z" }, "*"); }, arrival);
});
function check() {
  polls++;
  let applied = null;
  try { applied = frame.contentWindow.eval(__EXPRESSION_TEXT__); } catch (error) { applied = "error: " + error.message; }
  if (sentAt !== null && applied === true && appliedAt === null) appliedAt = performance.now();
  if (polls < __POLLS__) setTimeout(check, __POLL__);
  else document.getElementById("saveable-result").textContent = JSON.stringify({ arrival, appliedAfter: sentAt === null || appliedAt === null ? null : Math.round(appliedAt - sentAt), finalApplied: applied });
}
frame.src = page;
setTimeout(check, __POLL__);
</script>"""

STANDALONE_STUB = """<script>
(function () {
  const query = new URLSearchParams(location.search), arrival = Number(query.get("arrival"));
  const SAVED = __SAVED__;
  window.claude = { use: async () => ({ doc: () => ({
    get: async () => {
      if (arrival < 0) return { exists: false };
      await new Promise(resolve => setTimeout(resolve, arrival));
      window.sentAtForMeasure = performance.now();
      return { exists: true, data: () => ({ saved: SAVED, savedAt: "2026-01-01T00:00:00Z" }) };
    },
    set: async () => {} }) }) };
})();
</script>"""

STANDALONE_POLLER = """<pre id="saveable-result">running</pre><script>
(function () {
  const query = new URLSearchParams(location.search);
  let polls = 0, appliedAt = null, applied = null;
  function tick() {
    polls++;
    try { applied = __EXPRESSION__; } catch (error) { applied = "error: " + error.message; }
    if (window.sentAtForMeasure !== undefined && applied === true && appliedAt === null) appliedAt = performance.now();
    if (polls < __POLLS__) setTimeout(tick, __POLL__);
    else document.getElementById("saveable-result").textContent = JSON.stringify({ arrival: Number(query.get("arrival")), appliedAfter: appliedAt === null || window.sentAtForMeasure === undefined ? null : Math.round(appliedAt - window.sentAtForMeasure), finalApplied: applied });
  }
  setTimeout(tick, __POLL__);
})();
</script>"""


def fill(template: str, saved: dict, expression: str) -> str:
    replacements = {
        "__SAVED__": json.dumps(saved),
        "__EXPRESSION_TEXT__": json.dumps(expression),
        "__EXPRESSION__": expression,
        "__POLLS__": str(POLL_COUNT),
        "__POLL__": str(POLL_MILLISECONDS),
    }
    for placeholder, value in replacements.items():
        template = template.replace(placeholder, value)
    return template


def hosted_files(page: str, saved: dict, expression: str) -> dict[str, str]:
    return {"parent.html": fill(HOSTED_PARENT, saved, expression), "page.html": page}


def standalone_files(page: str, saved: dict, expression: str) -> dict[str, str]:
    if "<body>" not in page or "</body>" not in page:
        raise SystemExit("measure-apply-delay: the page needs <body> and </body> to place the stand-in database and the poller")
    stub = fill(STANDALONE_STUB, saved, expression)
    poller = fill(STANDALONE_POLLER, saved, expression)
    return {"page.html": page.replace("<body>", "<body>" + stub, 1).replace("</body>", poller + "</body>")}


def parse_result(rendered_page: str) -> dict:
    match = RESULT.search(rendered_page)
    if not match:
        raise SystemExit("measure-apply-delay: the page never wrote a result; the page or Chrome failed before the poll finished")
    return json.loads(match.group(1).replace("&quot;", '"'))


def run_chrome(chrome: str, url: str) -> str:
    profile = tempfile.mkdtemp()
    completed = subprocess.run(
        [chrome, "--headless=new", "--disable-gpu", f"--user-data-dir={profile}", "--virtual-time-budget=40000", "--dump-dom", url],
        capture_output=True, text=True, timeout=300, check=False,
    )
    if completed.returncode != 0:
        raise SystemExit(f"measure-apply-delay: Chrome exited {completed.returncode}: {completed.stderr[-300:]}")
    return completed.stdout


class QuietHandler(http.server.SimpleHTTPRequestHandler):
    """Serves the harness files without printing a line per request."""

    def log_message(self, format, *arguments):
        return None


def serve(directory: str) -> tuple[http.server.ThreadingHTTPServer, int]:
    handler = functools.partial(QuietHandler, directory=directory)
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, server.server_address[1]


def page_url(mode: str, port: int, arrival: int) -> str:
    if mode == "hosted":
        return f"http://127.0.0.1:{port}/parent.html?page=page.html&arrival={arrival}"
    return f"http://127.0.0.1:{port}/page.html?arrival={arrival}"


def measure(page_path: str, mode: str, saved: dict, expression: str, arrivals: list[int], chrome: str) -> list[dict]:
    page = Path(page_path).read_text(encoding="utf-8")
    files = hosted_files(page, saved, expression) if mode == "hosted" else standalone_files(page, saved, expression)
    directory = tempfile.mkdtemp()
    for name, text in files.items():
        (Path(directory) / name).write_text(text, encoding="utf-8")
    server, port = serve(directory)
    try:
        return [parse_result(run_chrome(chrome, page_url(mode, port, arrival))) for arrival in arrivals]
    finally:
        server.shutdown()
        server.server_close()


def slow_arrivals(results: list[dict], limit: int) -> list[int]:
    return [result["arrival"] for result in results if result["arrival"] >= 0 and (result["appliedAfter"] is None or result["appliedAfter"] > limit)]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--page", required=True)
    parser.add_argument("--mode", choices=("standalone", "hosted"), required=True)
    parser.add_argument("--saved", required=True, help="JSON file holding the saved settings to hand the page")
    parser.add_argument("--applied-expression", required=True, help="JavaScript that is true once the page shows the saved settings")
    parser.add_argument("--arrivals", type=int, nargs="+", default=[0, 300, 3000], help="milliseconds before the saved settings reach the page; -1 sends none")
    parser.add_argument("--chrome", default=CHROME_MACOS)
    parser.add_argument("--limit", type=int, default=100, help="fail when a saved setting takes longer than this many milliseconds to show")
    arguments = parser.parse_args(argv)
    saved = json.loads(Path(arguments.saved).read_text(encoding="utf-8"))
    results = measure(arguments.page, arguments.mode, saved, arguments.applied_expression, arguments.arrivals, arguments.chrome)
    for result in results:
        print(json.dumps(result))
    slow = slow_arrivals(results, arguments.limit)
    if slow:
        print(f"SLOW or never applied when the settings arrive at {slow} ms (limit {arguments.limit} ms)")
        return 1
    print(f"every saved setting showed within {arguments.limit} ms")
    return 0


if __name__ == "__main__":
    sys.exit(main())
