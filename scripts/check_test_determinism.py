#!/usr/bin/env python3
"""Deterministic-test lint (SC-CI-5): block new clock, port and interpreter-version dependence in Python tests.

Python test files (every directory in pyproject's pytest testpaths) must not gain a line that

  clock    reads the wall clock (datetime.now/utcnow/today, date.today, time.time/time_ns) in a file with no
           frozen clock (freezegun, time_machine, or a patched/monkeypatched time/datetime/clock/now);
  port     listens on a hard-coded port (bind((host, 8080)), HTTPServer((host, 8080)), port=8080, --port 8080;
           use port 0 and read the port back);
  version  asserts something about the Python version in a file that never mentions sys.version_info.

Clock reads for durations (time.monotonic, perf_counter) are not flagged. A line that is meant as written ends with
`# determinism-ok: <reason>` (or has that comment on the line above).

Modes. `--base REF`: only lines ADDED between REF and --head (default HEAD) fail; hits on existing lines are counted
and reported as warnings. No `--base`: the whole tree is scanned, every hit is a warning and the exit code is 0
(the weekly hit count). `--warn-only` turns a failure into a warning (the roll-back switch). Standard library only.
"""
import argparse
import os
import re
import subprocess
import sys
import tomllib

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# The directories pytest collects (pyproject [tool.pytest.ini_options] testpaths), so a new test root is covered at once.
with open(os.path.join(ROOT, "pyproject.toml"), "rb") as _handle:
    TEST_DIRS = tuple(tomllib.load(_handle)["tool"]["pytest"]["ini_options"]["testpaths"])
PRAGMA = re.compile(r"#\s*determinism-ok:\s*\S{3,}")

CLOCK = re.compile(r"\b(?:datetime|date)\.(?:now|utcnow|today)\(|\btime\.(?:time|time_ns)\(")
FROZEN = re.compile(
    r"freezegun|freeze_time|time[_-]machine|\bfreeze_?clock\b|\bfrozen_(?:now|clock|time)\b|\bfixed_(?:now|clock)\b"
    r"|\bpatch(?:\.object)?\(\s*[\"'][\w.]*\b(?:time|datetime|date|clock|now)\b"
    r"|\bsetattr\([^)\n]*\b(?:time|datetime|date|clock|now)\b"
)
PORT = re.compile(
    r"\.bind\(\(\s*[^,()]+,\s*[1-9]\d*\s*\)\)"
    r"|(?:HTTPServer|TCPServer|UDPServer|create_server)\(\(?\s*[^,()]+,\s*[1-9]\d*\s*\)"
    r"|\bport\s*=\s*[1-9]\d{3,4}\b|[\"']port[\"']\s*:\s*[1-9]\d{3,4}\b|--port(?:=|[\"']?\s*,?\s*[\"']?)[1-9]\d{3,4}\b"
)
PYTHON_WORD = re.compile(r"python|cpython|\bpy3|sys\.version\b|python_version", re.I)
PYTHON_NUMBER = re.compile(r"\b3[._]?(?:9|1\d)(?:\.\d+)?\b")
ASSERTING = re.compile(r"\bassert|\bexpect\b|==")
VERSION_GUARD = re.compile(r"sys\.version_info|(?:setattr|patch)\([^)\n]*python_version")


def classify(lines):
    """[(1-based line number, kind)] for the lines of one file that carry a hit and no pragma."""
    text = "\n".join(lines)
    frozen = bool(FROZEN.search(text))
    guarded = bool(VERSION_GUARD.search(text))
    hits = []
    for number, line in enumerate(lines, 1):
        code = line.strip()
        if not code or code.startswith("#") or "version_info" in code:
            continue
        if PRAGMA.search(line) or (number > 1 and lines[number - 2].strip().startswith("#") and PRAGMA.search(lines[number - 2])):
            continue
        if not frozen and CLOCK.search(line):
            hits.append((number, "clock"))
        elif PORT.search(line):
            hits.append((number, "port"))
        elif not guarded and ASSERTING.search(line) and PYTHON_WORD.search(line) and PYTHON_NUMBER.search(line):
            hits.append((number, "version"))
    return hits


def test_files():
    for top in TEST_DIRS:
        for base, dirs, names in os.walk(os.path.join(ROOT, top)):
            dirs[:] = sorted(d for d in dirs if d not in ("__pycache__", "node_modules"))
            for name in sorted(names):
                if name.endswith(".py"):
                    yield os.path.relpath(os.path.join(base, name), ROOT).replace(os.sep, "/")


def git(*args):
    return subprocess.run(["git", "-c", "core.quotepath=off", *args], cwd=ROOT, check=True, capture_output=True, text=True).stdout


def added_lines(base, head):
    """{path: set(line numbers added between base and head)} for Python files under the test directories."""
    out, path = {}, None
    diff = git("diff", "-U0", "-M", "--no-color", "--diff-filter=AMR", base, head, "--", *TEST_DIRS)
    for row in diff.splitlines():
        if row.startswith("+++ "):
            path = row[6:] if row.startswith("+++ b/") else None
            if path is not None and not path.endswith(".py"):
                path = None
        elif row.startswith("@@") and path:
            match = re.match(r"@@ -\S+ \+(\d+)(?:,(\d+))? @@", row)
            if match:
                start, count = int(match.group(1)), int(match.group(2) or 1)
                out.setdefault(path, set()).update(range(start, start + count))
    return out


def main(argv=None):
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    parser.add_argument("--base", help="fail only for lines added since this ref (e.g. HEAD^1 in CI)")
    parser.add_argument("--head", default="HEAD")
    parser.add_argument("--warn-only", action="store_true", help="report new lines as warnings; exit 0")
    args = parser.parse_args(argv)
    try:
        added = added_lines(args.base, args.head) if args.base else {}
    except subprocess.CalledProcessError as error:
        print(f"::error::determinism lint cannot diff against {args.base}: {error.stderr.strip()}")
        return 2
    new, old = [], []
    for path in test_files():
        with open(os.path.join(ROOT, path), encoding="utf-8", errors="replace") as handle:
            lines = handle.read().splitlines()
        for number, kind in classify(lines):
            (new if number in added.get(path, ()) else old).append((path, number, kind, lines[number - 1].strip()))
    for path, number, kind, source in new:
        level = "warning" if args.warn_only else "error"
        print(f"::{level} file={path},line={number},title=Deterministic-test lint ({kind})::{kind}: {source[:120]}  "
              f"[fix it, or end the line with '# determinism-ok: <reason>'; docs/engineering/testing.md]")
    by_kind = {}
    for _, _, kind, _ in old:
        by_kind[kind] = by_kind.get(kind, 0) + 1
    print(f"determinism lint: new={len(new)} existing={len(old)} "
          f"({', '.join(f'{k}={v}' for k, v in sorted(by_kind.items())) or 'none'}) "
          f"mode={'warn-only' if args.warn_only or not args.base else 'fail-on-new'}")
    for path, number, kind, source in old[:60]:
        print(f"  existing (warning) {path}:{number} {kind}: {source[:100]}")
    return 1 if new and not args.warn_only else 0


if __name__ == "__main__":
    sys.exit(main())
