"""Inert candidate: aggregate synthetic/reviewed fragments to stdout, never install."""
import argparse
import importlib.util
import os
from pathlib import Path
import re
import stat
import sys

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location('candidate_section', ROOT / 'sources/changelog_section.py')
extractor = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(extractor)
NAME = re.compile(r'([0-9]{4})\.(user|internal)\.md')
INJECTION = re.compile(
    r'^ {0,3}#{1,6}[ \t]+(?:Unreleased|Internal|v?\d+\.\d+\.\d+'
    r'(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?)(?:\s|$)', re.I)
BULLET = re.compile(r'^ {0,3}(?:[-+*]|[0-9]+[.)])[ \t]+\S')


def checked_path(path):
    path = Path(path)
    if '..' in path.parts:
        raise ValueError('Traversal is not allowed')
    path = path.absolute()
    for ancestor in reversed((path, *path.parents)):
        if ancestor.is_symlink():
            raise ValueError('Symlink paths are not allowed')
    return path


def read_regular(path):
    # O_NONBLOCK prevents a swapped FIFO hanging; fstat checks the opened inode.
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise ValueError('Expected a regular file')
        return stream.read().decode('utf-8')


def aggregate(base_text, fragment_dir):
    """Keep released bytes; normalize only modified Unreleased boundaries to LF.

    Existing category bodies keep their order and interior whitespace. Trim only
    boundary newlines; separate header, bodies and fragments with one blank line;
    finish Unreleased with one blank line (one final LF when it is the last section).
    Empty directories return the original text, including its newline convention.
    """
    lines = base_text.splitlines(keepends=True)
    code = extractor.fenced_lines(base_text.splitlines())
    heads = [i for i, line in enumerate(lines) if not code[i] and line.startswith('## ')]
    starts = [i for i in heads if lines[i].strip() == '## Unreleased']
    if len(starts) != 1:
        raise ValueError('Expected exactly one Unreleased section')
    start = starts[0]
    end = next((i for i in heads if i > start), len(lines))
    internal = [i for i in range(start + 1, end)
                if not code[i] and lines[i].strip() == '### Internal']
    if len(internal) > 1:
        raise ValueError('Duplicate Internal subsection')
    directory = checked_path(fragment_dir)
    if not directory.is_dir():
        raise ValueError('Expected a fragment directory')
    entries, orders = [], set()
    for path in directory.iterdir():
        match = NAME.fullmatch(path.name)
        if not match or not stat.S_ISREG(path.lstat().st_mode):
            raise ValueError('Invalid fragment name or type: ' + path.name)
        if match[1] in orders:
            raise ValueError('Duplicate fragment order: ' + match[1])
        orders.add(match[1])
        entries.append((int(match[1]), match[2], path))
    additions = {'user': [], 'internal': []}
    for _, category, path in sorted(entries):
        text = read_regular(path)
        body = text.strip('\r\n')
        flags = extractor.fenced_lines(body.splitlines())
        if not body or not BULLET.match(body.splitlines()[0]):
            raise ValueError('Fragment must start with nonempty Markdown list content')
        if any(INJECTION.match(line) for line, fenced in zip(body.splitlines(), flags) if not fenced):
            raise ValueError('Fragment heading injection')
        additions[category].append(body)
    if not entries:
        return base_text
    cut = internal[0] if internal else end
    user = ''.join(lines[start + 1:cut]).strip('\r\n')
    private = ''.join(lines[cut + 1:end]).strip('\r\n') if internal else ''
    blocks = ['## Unreleased', *filter(None, [user]), *additions['user']]
    if internal or additions['internal']:
        blocks += ['### Internal', *filter(None, [private]), *additions['internal']]
    return (''.join(lines[:start]) + '\n\n'.join(blocks) + '\n' +
            ('\n' if end < len(lines) else '') + ''.join(lines[end:]))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('base', type=Path)
    parser.add_argument('fragment_dir', type=Path)
    args = parser.parse_args(argv)
    try:
        result = aggregate(read_regular(checked_path(args.base)), args.fragment_dir)
    except (OSError, UnicodeError, ValueError, LookupError) as error:
        print(str(error), file=sys.stderr)
        return 1
    sys.stdout.buffer.write(result.encode('utf-8'))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
