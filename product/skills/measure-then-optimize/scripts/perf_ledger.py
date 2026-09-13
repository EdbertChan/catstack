import argparse
import json
import subprocess
import sys
import time
from pathlib import Path


def number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def valid_entry(entry):
    if not isinstance(entry, dict):
        return entry is None
    required = ("metric", "cmd", "settings", "runs")
    if any(key not in entry for key in required):
        return False
    return (isinstance(entry["metric"], str) and isinstance(entry["cmd"], str)
            and isinstance(entry["settings"], dict) and isinstance(entry["runs"], list)
            and bool(entry["runs"]) and all(number(value) for value in entry["runs"]))


def judge(ledger):
    if not isinstance(ledger, dict) or "symptom_metric" not in ledger:
        return "unchecked", ["unreadable-entry"]
    baseline = ledger.get("baseline")
    after = ledger.get("after")
    if not valid_entry(baseline) or not valid_entry(after):
        return "unchecked", ["unreadable-entry"]
    symptom = ledger["symptom_metric"]
    reasons = []
    if baseline is None:
        reasons.append("no-baseline")
    if after is None:
        reasons.append("no-real-after")
    for entry in (baseline, after):
        if entry is not None and entry["metric"] != symptom:
            reasons.append("proxy-metric")
    if baseline is not None and after is not None and baseline["metric"] == symptom and after["metric"] == symptom:
        if baseline["cmd"] != after["cmd"] or baseline["settings"] != after["settings"]:
            reasons.append("different-conditions")
    for entry in (baseline, after):
        if entry is not None and len(entry["runs"]) < 3:
            reasons.append("single-run")
    limit_change = ledger.get("limit_change")
    if (isinstance(limit_change, dict) and number(limit_change.get("old"))
            and limit_change.get("old") is not None and number(limit_change.get("new"))
            and limit_change.get("new") is not None and limit_change["new"] > limit_change["old"]):
        reasons.append("limit-loosened")
    if not ledger.get("lever_path"):
        reasons.append("no-lever")
    reasons = sorted(set(reasons))
    return ("fail" if reasons else "pass"), reasons


def record(args):
    values = []
    for _ in range(args.runs):
        started = time.monotonic()
        result = subprocess.run(args.program, capture_output=True, text=True)
        if result.returncode:
            sys.stderr.write(result.stderr)
            return 2
        if args.from_stdout:
            value = None
            for line in reversed(result.stdout.splitlines()):
                try:
                    candidate = float(line.strip())
                except ValueError:
                    continue
                value = int(candidate) if candidate.is_integer() else candidate
                break
            if value is None:
                sys.stderr.write("no numeric stdout value\n")
                return 2
        else:
            value = time.monotonic() - started
        values.append(value)
    path = Path(args.ledger)
    if path.exists():
        data = json.loads(path.read_text())
    else:
        data = {}
    if not isinstance(data, dict):
        data = {}
    data[args.phase] = {"metric": args.metric, "cmd": " ".join(args.program), "settings": dict(item.split("=", 1) for item in args.setting), "runs": values}
    if args.symptom_metric is not None:
        data["symptom_metric"] = args.symptom_metric
    if args.lever_path is not None:
        data["lever_path"] = args.lever_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n")
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    judge_parser = subparsers.add_parser("judge")
    judge_parser.add_argument("ledger")
    record_parser = subparsers.add_parser("record")
    record_parser.add_argument("--ledger", required=True)
    record_parser.add_argument("--phase", choices=("baseline", "after"), required=True)
    record_parser.add_argument("--metric", required=True)
    record_parser.add_argument("--runs", type=int, default=5)
    record_parser.add_argument("--setting", action="append", default=[])
    record_parser.add_argument("--from-stdout", action="store_true")
    record_parser.add_argument("--symptom-metric")
    record_parser.add_argument("--lever-path")
    record_parser.add_argument("program", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    if args.command == "judge":
        try:
            data = json.loads(Path(args.ledger).read_text())
        except (OSError, ValueError, TypeError):
            verdict, reasons = "unchecked", ["unreadable-entry"]
        else:
            verdict, reasons = judge(data)
        print(json.dumps({"verdict": verdict, "reasons": reasons}, separators=(",", ":")))
        return {"pass": 0, "fail": 1, "unchecked": 2}[verdict]
    if args.program and args.program[0] == "--":
        args.program = args.program[1:]
    if not args.program or args.runs < 1 or any("=" not in item for item in args.setting):
        parser.error("record requires a program, positive runs, and key=value settings")
    return record(args)


if __name__ == "__main__":
    raise SystemExit(main())
