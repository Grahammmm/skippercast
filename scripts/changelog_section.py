"""Print one release's section of CHANGELOG.md, for GitHub release notes.

Usage: python scripts/changelog_section.py v0.3.0 [--changelog CHANGELOG.md]

The version may carry a leading "v". The section runs from its "## <version>"
heading (for example "## 0.3.0 — 2026-09-20") to the next "## " heading and
includes any "### Internal" subsection. Exits 1 when the section is missing or
empty, so a release is never published with blank notes.
"""
import argparse
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]


def section(text, version):
    version = version[1:] if version.startswith('v') else version
    if not re.fullmatch(r'\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?', version):
        raise ValueError(f'Not a release version: {version}')
    heading = re.compile(r'^## v?' + re.escape(version) + r'(?:\s|$)')
    lines, body, inside = text.splitlines(), [], False
    for line in lines:
        if line.startswith('## '):
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
        print(section(args.changelog.read_text(encoding='utf-8'), args.version))
    except (ValueError, LookupError) as error:
        print(f'::error::{error}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
