#!/usr/bin/env python3
"""Record local calibration evidence; summarize requested settings, not minima."""
import argparse
import collections
import datetime
import json
from pathlib import Path


def nonnegative(value):
    number = int(value)
    if number < 0:
        raise argparse.ArgumentTypeError("must be nonnegative")
    return number


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    record = commands.add_parser("record")
    record.add_argument("--ledger", type=Path, required=True)
    for name in ("task", "fingerprint", "model", "evidence"):
        record.add_argument("--" + name, required=True)
    record.add_argument("--effort", choices=("none", "minimal", "low", "medium", "high", "xhigh", "max", "ultra"), required=True)
    record.add_argument("--outcome", choices=("pass", "fail", "blocked"), required=True)
    record.add_argument("--kind", choices=("actual", "simulation"), required=True)
    record.add_argument("--rework", type=nonnegative)
    record.add_argument("--elapsed-seconds", type=nonnegative)
    record.add_argument("--tokens", type=nonnegative)
    report = commands.add_parser("report")
    report.add_argument("--ledger", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "record":
        row = {key: value for key, value in vars(args).items() if key not in ("command", "ledger") and value is not None}
        if any(not row[key].strip() for key in ("task", "fingerprint", "model", "evidence")):
            parser.error("task, fingerprint, model and evidence must be nonempty")
        row["recordedAt"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        row["modelSetting"] = "requested; not independently observed"
        args.ledger.parent.mkdir(parents=True, exist_ok=True)
        with args.ledger.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, sort_keys=True) + "\n")
        print(json.dumps({"recorded": True, "ledger": str(args.ledger)}))
        return
    groups = {}
    try:
        with args.ledger.open(encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, 1):
                try:
                    row = json.loads(line)
                    key = tuple(row[field] for field in ("task", "fingerprint", "model", "effort", "kind"))
                    if any(not isinstance(value, str) or not value for value in key):
                        raise ValueError("invalid grouping field")
                    if row["kind"] not in ("actual", "simulation"):
                        raise ValueError("invalid trial kind")
                    if row["outcome"] not in ("pass", "fail", "blocked"):
                        raise ValueError("invalid outcome")
                    counts = groups.setdefault(key, collections.Counter())
                    counts[row["outcome"]] += 1
                except (ValueError, KeyError, TypeError) as error:
                    parser.error(f"invalid trial at line {line_number}: {error}")
    except OSError as error:
        parser.error(str(error))
    result = []
    for key, counts in sorted(groups.items()):
        result.append(dict(zip(("task", "fingerprint", "model", "effort", "kind"), key), **{name: counts[name] for name in ("pass", "fail", "blocked")}))
    print(json.dumps({"minimumEstablished": False, "groups": result}, indent=2))


if __name__ == "__main__":
    main()
