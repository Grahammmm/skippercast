"""Inspect and validate portable regional data packages."""
import argparse
import json
from pathlib import Path
from .contracts import REPO, load_region, requirement_report, atomic_json, read_json
from .candidate import validate_candidate


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("needs", "validate"):
        p = sub.add_parser(name)
        p.add_argument("--region", required=True)
        p.add_argument("--root", type=Path, default=REPO)
        p.add_argument("--output", type=Path)
    p = sub.add_parser("candidate")
    p.add_argument("--file", type=Path, required=True)
    p.add_argument("--root", type=Path, default=REPO)
    args = parser.parse_args()
    if args.command == "candidate":
        print(json.dumps(validate_candidate(read_json(args.file), args.root), indent=2))
        return
    region = load_region(args.region, args.root)
    report = requirement_report(region, args.root)
    if args.output:
        atomic_json(args.output, report)
    print(json.dumps(report if args.command == "needs" else {
        "region": region["id"], "valid": True, "capabilities": report["capabilities"]
    }, indent=2))


if __name__ == "__main__":
    main()
