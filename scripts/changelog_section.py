"""Print one release's section of CHANGELOG.md, for GitHub release notes.

Usage: python scripts/changelog_section.py v0.3.0 [--changelog CHANGELOG.md]

With --tagged, resolve the exact Git tag in the current repository and read
both package.json and CHANGELOG.md from that commit, never from the checkout.

The version may carry a leading "v". The section runs from its "## <version>"
heading (for example "## 0.3.0 — 2026-09-20") to the next "## " heading and
includes any "### Internal" subsection. Exits 1 when the section is missing or
empty, so a release is never published with blank notes, and when the version
has two headings or the changelog cannot be read. Lines inside a ``` or ~~~
code fence are body text, never headings; an unclosed fence is refused.
"""
import argparse
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
FENCE = re.compile(r'^ {0,3}(`{3,}|~{3,})(.*)$')
VERSION = re.compile(r'\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+(?:\+[0-9A-Za-z.-]+)?|\+[0-9A-Za-z.-]+)?')


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
    if not VERSION.fullmatch(version):
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


def tagged_changelog(tag):
    if not tag.startswith('v') or not VERSION.fullmatch(tag[1:]):
        raise ValueError(f'Not a release tag: {tag}')

    def git_read(error, *args):
        try:
            return subprocess.run(['git', *args], check=True, capture_output=True).stdout
        except (subprocess.CalledProcessError, OSError) as exc:
            raise LookupError(error) from exc

    commit = git_read(f'Tag {tag} does not resolve to a commit',
                      'rev-parse', '--verify', '--end-of-options', f'refs/tags/{tag}^{{commit}}').strip().decode('ascii')

    def blob(path):
        data = git_read(f'Cannot read {path} at tag {tag}', 'cat-file', 'blob', f'{commit}:{path}')
        try:
            return data.decode('utf-8')
        except UnicodeDecodeError as exc:
            raise ValueError(f'{path} at tag {tag} is not UTF-8') from exc

    try:
        version = json.loads(blob('package.json'))['version']
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        raise ValueError(f'Cannot read the package.json version at tag {tag}') from exc
    if not isinstance(version, str) or f'v{version}' != tag:
        raise ValueError(f'{tag} points at a commit with a different package.json version')
    return blob('CHANGELOG.md')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('version')
    source = parser.add_mutually_exclusive_group()
    source.add_argument('--changelog', type=Path, default=ROOT / 'CHANGELOG.md')
    source.add_argument('--tagged', action='store_true', help='read release metadata and notes from the Git tag')
    args = parser.parse_args(argv)
    try:
        text = tagged_changelog(args.version) if args.tagged else args.changelog.read_text(encoding='utf-8')
        print(section(text, args.version))
    except UnicodeDecodeError:
        print(f'::error::{args.changelog} is not UTF-8', file=sys.stderr)
        return 1
    except OSError as error:
        print(f'::error::cannot read {args.changelog} ({type(error).__name__})', file=sys.stderr)
        return 1
    except (ValueError, LookupError) as error:
        print(f'::error::{error}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
