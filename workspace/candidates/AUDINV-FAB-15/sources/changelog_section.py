"""Print one release's section of CHANGELOG.md, for GitHub release notes.

Usage: python scripts/changelog_section.py v0.3.0 [--changelog CHANGELOG.md]

The version may carry a leading "v". The section runs from its "## <version>"
heading (for example "## 0.3.0 — 2026-09-20") to the next "## " heading and
includes any "### Internal" subsection. Exits 1 when the section is missing or
empty, so a release is never published with blank notes, and when the version
has two headings or the changelog cannot be read. Lines inside a ``` or ~~~
code fence are body text, never headings; an unclosed fence is refused.
"""
import argparse
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
FENCE = re.compile(r'^ {0,3}(`{3,}|~{3,})(.*)$')


def fenced_lines(lines):
    fenced, close, start = [], None, 0
    for number, line in enumerate(lines, 1):
        match = None if close else FENCE.match(line)
        if match and not (match[1][0] == '`' and '`' in match[2]):
            close, start = re.compile(r' {0,3}' + re.escape(match[1][0]) + r'{%d,}\s*' % len(match[1])), number
            fenced.append(True)
        else:
            fenced.append(bool(close))
            close = None if close and close.fullmatch(line) else close
    if close:
        raise LookupError(f'CHANGELOG has an unclosed code fence at line {start}')
    return fenced


def section(text, version):
    version = version[1:] if version.startswith('v') else version
    if not re.fullmatch(r'\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?', version):
        raise ValueError(f'Not a release version: {version}')
    heading = re.compile(r'^## v?' + re.escape(version) + r'(?:\s|$)')
    lines, body, inside = text.splitlines(), [], False
    fenced = fenced_lines(lines)
    count = sum(1 for line, code in zip(lines, fenced) if not code and heading.match(line))
    if count > 1:
        raise LookupError(f'CHANGELOG has {count} sections for {version}; merge them')
    for line, code in zip(lines, fenced):
        if not code and line.startswith('## '):
            if inside:
                break
            inside = bool(heading.match(line))
            continue
        if inside:
            body.append(line)
    notes = '\n'.join(body).strip()
    if not notes:
        raise LookupError(f'No CHANGELOG section for {version}')
    return notes


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('version')
    parser.add_argument('--changelog', type=Path, default=ROOT / 'CHANGELOG.md')
    args = parser.parse_args(argv)
    try:
        text = args.changelog.read_text(encoding='utf-8')
    except UnicodeDecodeError:
        print(f'::error::{args.changelog} is not UTF-8', file=sys.stderr)
        return 1
    except OSError as error:
        print(f'::error::cannot read {args.changelog} ({type(error).__name__})', file=sys.stderr)
        return 1
    try:
        print(section(text, args.version))
    except (ValueError, LookupError) as error:
        print(f'::error::{error}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
