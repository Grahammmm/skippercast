#!/usr/bin/env python3
"""Deterministic-test lint (SC-CI-5): block new clock, port and interpreter-version dependence in Python tests.

Python test files (every directory in pyproject's pytest testpaths) must not gain a line that

  clock    reads the wall clock (datetime.now/utcnow/today, date.today, time.time/time_ns) in a file with no
           frozen clock (freezegun, time_machine, or a patch/monkeypatch whose TARGET is time/datetime/clock/now;
           patch("time.sleep"), a comment, a docstring or a string naming a freezer excuse nothing);
  port     listens on a hard-coded port (bind((host, 8080)), HTTPServer((host, 8080)), port=8080, --port 8080;
           use port 0 and read the port back);
  version  asserts something about the Python version in a file that never mentions sys.version_info.

A statement wrapped over several lines is judged as one statement; it counts as new when a line it matches on was added
or changed. Clock reads for durations (time.monotonic, perf_counter) are not flagged. A line that is meant as written
ends with `# determinism-ok: <reason>` (on any line of the statement, or as a comment on the line above it).

Modes. `--base REF`: only lines ADDED between REF and --head (default HEAD) fail; hits on existing lines are counted
and reported as warnings. No `--base`: the whole tree is scanned, every hit is a warning and the exit code is 0
(the weekly hit count). `--warn-only` turns a failure into a warning (the roll-back switch). Standard library only.
"""
import argparse
import io
import os
import re
import subprocess
import sys
import tokenize
import tomllib

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# The directories pytest collects (pyproject [tool.pytest.ini_options] testpaths), so a new test root is covered at once.
with open(os.path.join(ROOT, "pyproject.toml"), "rb") as _handle:
    TEST_DIRS = tuple(tomllib.load(_handle)["tool"]["pytest"]["ini_options"]["testpaths"])
PRAGMA = re.compile(r"#\s*determinism-ok:\s*\S{3,}")

CLOCK = re.compile(r"\b(?:datetime|date)\.(?:now|utcnow|today)\(|\btime\.(?:time|time_ns)\(")
_CLOCK_NAMES = r"(?:time|time_ns|datetime|date|clock|now|utcnow|today)"
# Freeze evidence is read from code only (comments, docstrings and string contents are blanked), so a comment such as
# "do not use freezegun" excuses nothing; a patch counts only when its TARGET is a clock (patch("time.sleep") is not).
FROZEN_NAMES = re.compile(
    r"\bfreezegun\b|\bfreeze_time\b|\btime_machine\b|\bfreezer\b|\bfreeze_?clock\b|\bfrozen_(?:now|clock|time)\b"
    r"|\bfixed_(?:now|clock)\b"
)
TARGET_NAME = re.compile(r"[A-Za-z_][\w.]*")  # a string that can name a patch target; any other string is prose
FROZEN_PATCH = re.compile(  # run on the `calls` view: code, with only target-like strings kept (the target is a string)
    r"\bpatch\(\s*[\"'][\w.]*\b" + _CLOCK_NAMES + r"[\"']"
    r"|\bpatch\.object\(\s*[^,()]+,\s*[\"']" + _CLOCK_NAMES + r"[\"']"
    r"|\bsetattr\(\s*[\"'][\w.]*\b" + _CLOCK_NAMES + r"[\"']"
    r"|\bsetattr\(\s*[^,()]+,\s*[\"']" + _CLOCK_NAMES + r"[\"']"
    r"|\busefixtures\([^)]*[\"'](?:frozen_(?:now|clock|time)|fixed_(?:now|clock)|freeze_?clock|freezer)[\"']"
)
# A statement may span lines (black wraps long calls), so these run on a whole statement; \s matches a newline.
PORT = re.compile(
    r"\.bind\(\s*\(\s*[^,()]+,\s*[1-9]\d*\s*,?\s*\)\s*,?\s*\)"
    r"|(?:HTTPServer|TCPServer|UDPServer|create_server)\(\s*\(?\s*[^,()]+,\s*[1-9]\d*\s*,?\s*\)"
    r"|\bport\s*=\s*[1-9]\d{3,4}\b|[\"']port[\"']\s*:\s*[1-9]\d{3,4}\b|--port(?:=|[\"']?\s*,?\s*[\"']?)[1-9]\d{3,4}\b"
)
PYTHON_WORD = re.compile(r"python|cpython|\bpy3|sys\.version\b|python_version", re.I)
PYTHON_NUMBER = re.compile(r"\b3[._]?(?:9|1\d)(?:\.\d+)?\b")
ASSERTING = re.compile(r"\bassert|\bexpect\b|==")
VERSION_GUARD_CODE = re.compile(r"\bsys\.version_info\b")
VERSION_GUARD_PATCH = re.compile(r"\b(?:setattr|patch(?:\.object)?)\([^)]*python_version")
_STRING_TYPES = {tokenize.STRING, getattr(tokenize, "FSTRING_START", -1), getattr(tokenize, "FSTRING_MIDDLE", -1),
                 getattr(tokenize, "FSTRING_END", -1)}


def blank(buffer, srow, scol, erow, ecol):
    """Overwrite the source text between two token positions (1-based rows) with spaces, keeping line lengths."""
    for row in range(srow, erow + 1):
        line = buffer[row - 1]
        begin = scol if row == srow else 0
        end = ecol if row == erow else len(line)
        buffer[row - 1] = line[:begin] + " " * max(0, min(end, len(line)) - begin) + line[end:]


def statements(lines):
    """[(first line, last line, text, code, docstring_only, calls)] for the logical statements of a file (1-based lines).

    `text` is the statement without comments; `code` is `text` with string contents blanked; `calls` is `code` with
    the strings that can name a patch target (dotted names) kept, so `patch("time.time")` survives but a sentence that
    merely contains the text patch('time.time') does not. A file that does not tokenize (a fragment) falls back to
    one statement per physical line, with `calls` = `text` minus comments."""
    text_lines = list(lines)
    code_lines = list(lines)
    calls_lines = list(lines)
    spans, current = [], None
    try:
        for token in tokenize.generate_tokens(io.StringIO("\n".join(lines) + "\n").readline):
            kind, (srow, scol), (erow, ecol) = token.type, token.start, token.end
            if kind == tokenize.COMMENT:
                text_lines[srow - 1] = text_lines[srow - 1][:scol]
                code_lines[srow - 1] = code_lines[srow - 1][:scol]
                calls_lines[srow - 1] = calls_lines[srow - 1][:scol]
            elif kind == tokenize.NEWLINE:
                if current:
                    spans.append(current)
                current = None
            elif kind not in (tokenize.NL, tokenize.INDENT, tokenize.DEDENT, tokenize.ENDMARKER):
                if current is None:
                    current = [srow, erow, True]
                current[1] = max(current[1], erow)
                current[2] = current[2] and kind in _STRING_TYPES
                if kind == tokenize.STRING or kind == getattr(tokenize, "FSTRING_MIDDLE", -1):
                    inner = token.string.lstrip("rRbBuUfF").strip("\"'") if kind == tokenize.STRING else ""
                    buffers = [code_lines] if srow == erow and TARGET_NAME.fullmatch(inner) else [code_lines, calls_lines]
                    for buffer in buffers:
                        blank(buffer, srow, scol, erow, ecol)
    except (tokenize.TokenError, SyntaxError):
        text_lines = [("" if line.lstrip().startswith("#") else line) for line in lines]
        code_lines = list(text_lines)
        calls_lines = list(text_lines)
        spans = [[number, number, False] for number in range(1, len(lines) + 1)]
    return [(first, last, "\n".join(text_lines[first - 1:last]), "\n".join(code_lines[first - 1:last]), only_string,
             "\n".join(calls_lines[first - 1:last]))
            for first, last, only_string in spans if "\n".join(text_lines[first - 1:last]).strip()]


def has_pragma(lines, first, last):
    if any(PRAGMA.search(line) for line in lines[first - 1:last]):
        return True
    return first > 1 and lines[first - 2].strip().startswith("#") and bool(PRAGMA.search(lines[first - 2]))


def classify_spans(lines):
    """[(first line, last line, kind)] for the statements of one file that carry a hit and no pragma.

    The line range is the lines the matched text covers, so an edit to any of them (the port argument of a wrapped
    `bind((` call, say) makes the hit "added"."""
    stmts = [stmt for stmt in statements(lines) if not stmt[4]]
    frozen = any(FROZEN_NAMES.search(code) or FROZEN_PATCH.search(calls) for _, _, _, code, _, calls in stmts)
    guarded = any(VERSION_GUARD_CODE.search(code) or VERSION_GUARD_PATCH.search(calls) for _, _, _, code, _, calls in stmts)
    hits = []
    for first, last, text, code, _, _ in stmts:
        if has_pragma(lines, first, last):
            continue
        found = set()
        for pattern, kind in ((CLOCK, "clock"), (PORT, "port")):
            if kind == "clock" and frozen:
                continue
            for match in pattern.finditer(text):
                begin = first + text.count("\n", 0, match.start())
                found.add((begin, first + text.count("\n", 0, max(match.end() - 1, match.start())), kind))
        if found:  # one hit per starting line and kind, so a hit in a long string statement is its own line
            hits.extend(sorted(found))
        elif (not guarded and "version_info" not in code and ASSERTING.search(text) and PYTHON_WORD.search(text)
                and PYTHON_NUMBER.search(text)):
            hits.append((first, last, "version"))
    return sorted(set(hits))


def classify(lines):
    """[(1-based line number, kind)] for the hits of one file (see classify_spans)."""
    return [(first, kind) for first, _, kind in classify_spans(lines)]


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
        for first, last, kind in classify_spans(lines):
            # A wrapped statement is new when any line it covers was added or changed.
            is_new = any(number in added.get(path, ()) for number in range(first, last + 1))
            (new if is_new else old).append((path, first, kind, lines[first - 1].strip()))
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
