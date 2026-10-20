"""Read-only source inventory for SC-4 (2026-10-20); never import snapshot code.

Compare the coastal Python subtree with an explicit Git revision. JSON output
contains relative source paths, sizes and hashes only, not host paths or data.
Use --check to reproduce a committed inventory without writing any files.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import subprocess

PREFIX = "src/skippercast/coastal/"
SKILL_COUNTERPARTS = {
    "discover.py": "skills/skippercast-discover-coastal-sources/scripts/discover.py",
    "formats.py": "skills/skippercast-discover-coastal-sources/scripts/formats.py",
    "gsf_resume.py": "skills/skippercast-discover-coastal-sources/scripts/gsf_resume.py",
    "quality.py": "skills/skippercast-discover-coastal-sources/scripts/quality.py",
    "run_bounded.py": "skills/skippercast-map-coast/scripts/run_bounded.py",
    "validate_handoff.py": "skills/skippercast-map-coast/scripts/validate_handoff.py",
}


def git(repo, *args):
    return subprocess.check_output(["git", "-C", str(repo), *args])


def identity(data):
    return {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def inventory(repo, snapshot, main_ref):
    revision = git(repo, "rev-parse", "--verify", main_ref + "^{commit}").decode().strip()
    tracked = set(git(repo, "ls-tree", "-r", "--name-only", revision).decode().splitlines())
    base = snapshot / PREFIX
    if not base.is_dir():
        raise ValueError("snapshot coastal source directory missing")
    rows = []
    # Only Python source is read. No imports, caches, receipts or native arrays.
    for path in sorted(base.rglob("*.py")):
        relative = path.relative_to(snapshot).as_posix()
        if any(parent.is_symlink() for parent in (path, *path.parents)):
            raise ValueError("symlink source refused: " + relative)
        data = path.read_bytes()
        row = {"path": relative, "snapshot": identity(data)}
        if relative in tracked:
            current = git(repo, "show", revision + ":" + relative)
            row.update(main=identity(current), comparison="identical" if current == data else "different")
        else:
            row.update(main=None, comparison="snapshot-only")
        counterpart = SKILL_COUNTERPARTS.get(path.relative_to(base).as_posix())
        if counterpart and counterpart in tracked:
            other = git(repo, "show", revision + ":" + counterpart)
            row["skill_counterpart"] = {
                "path": counterpart, **identity(other), "byte_identical_to_snapshot": other == data,
            }
        rows.append(row)
    if not rows:
        raise ValueError("empty snapshot source inventory")
    source_pin = "".join(row["path"] + "\t" + row["snapshot"]["sha256"] + "\n" for row in rows)
    resources = []
    for path in sorted((base / "resources").iterdir()):
        if path.suffix not in {".json", ".c"}:
            continue
        relative = path.relative_to(snapshot).as_posix()
        if relative in tracked:
            continue
        if path.is_symlink() or not path.is_file():
            raise ValueError("nonregular resource refused: " + relative)
        resources.append({"path": relative, **identity(path.read_bytes())})
    return {
        "schema": "coastal-snapshot-inventory-v1",
        "snapshot_locator": "work/source-reuse-admission-20261011",
        "main_revision": revision,
        "scope": PREFIX + "**/*.py",
        "source_manifest_sha256": hashlib.sha256(source_pin.encode()).hexdigest(),
        "source_manifest_encoding": "sorted relative path + TAB + snapshot sha256 + LF; UTF-8",
        "counts": dict(sorted(Counter(row["comparison"] for row in rows).items())),
        "modules": rows,
        "snapshot_only_resources": resources,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--main-ref", required=True)
    parser.add_argument("--check", type=Path, help="Compare with an existing inventory; do not write")
    args = parser.parse_args()
    observed = inventory(args.repo, args.snapshot, args.main_ref)
    if args.check:
        expected = json.loads(args.check.read_text())
        if observed != expected:
            raise SystemExit("FAIL: source inventory differs from committed evidence")
        print("PASS: source inventory matches; " + json.dumps(observed["counts"], sort_keys=True))
    else:
        print(json.dumps(observed, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
