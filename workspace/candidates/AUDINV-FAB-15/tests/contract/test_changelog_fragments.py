"""Synthetic-only acceptance; explicit execution, not enrolled in canonical CI."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location('candidate_fragments', ROOT / 'scripts/changelog_fragments.py')
m = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(m)
FIX = ROOT / 'tests/fixtures/changelog'
BASE = (FIX / 'base.md').read_text(encoding='utf-8')


@pytest.fixture
def sandbox():
    with tempfile.TemporaryDirectory(prefix='.synthetic-', dir=ROOT) as directory:
        yield Path(directory)


def cli(base, directory):
    return subprocess.run([sys.executable, '-B', str(ROOT / 'scripts/changelog_fragments.py'),
                           str(base), str(directory)], capture_output=True)


def snapshot(directory):
    return {p.name: (p.lstat().st_mode, p.read_bytes() if p.is_file() and not p.is_symlink() else None)
            for p in directory.iterdir()}


def test_source_identity():
    bases = json.loads((ROOT / 'BASES.json').read_text())
    for name, digest in bases['candidate_sha256'].items():
        assert hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == digest
    helper = ROOT / 'sources/changelog_section.py'
    assert Path(m.extractor.__file__).resolve() == helper.resolve()
    assert hashlib.sha256(helper.read_bytes()).hexdigest() == bases['reused_sources'][0]['sha256']


def test_concurrent_union_order_parity_and_cli(sandbox):
    names = ['0010.user.md', '0002.internal.md', '0001.user.md']
    a, b = sandbox / 'A', sandbox / 'B'
    a.mkdir(); b.mkdir()
    for name in names[:2]:
        (a / name).write_bytes((FIX / 'fragments' / name).read_bytes())
    (b / names[2]).write_bytes((FIX / 'fragments' / names[2]).read_bytes())
    assert '- Synthetic A' in m.aggregate(BASE, b)
    assert '- Synthetic B' in m.aggregate(BASE, a)
    for order in (names, list(reversed(names))):
        union = sandbox / ('forward' if order == names else 'reverse')
        union.mkdir()
        for name in order:
            (union / name).write_bytes((FIX / 'fragments' / name).read_bytes())
        before = snapshot(union)
        with patch.object(Path, 'iterdir', return_value=iter([union / n for n in reversed(order)])):
            output = m.aggregate(BASE, union)
        assert output == (FIX / 'expected.md').read_text(encoding='utf-8')
        assert output.count('- Synthetic A') == output.count('- Synthetic B') == 1
        assert output.index('- Synthetic A') < output.index('- Synthetic B') < output.index('- Synthetic internal')
        base = sandbox / 'base.md'
        base.write_bytes(BASE.encode())
        result = cli(base, union)
        assert result.returncode == 0 and result.stderr == b''
        assert result.stdout == output.encode()
        assert m.aggregate(BASE, union) == output
        assert snapshot(union) == before and base.read_bytes() == BASE.encode()
        for version in ('1.2.0', '1.1.0'):
            assert m.extractor.section(BASE, version) == m.extractor.section(output, version)
        assert output[output.index('## 1.2.0'):] == BASE[BASE.index('## 1.2.0'):]


def test_empty_and_category_creation(sandbox):
    assert m.aggregate(BASE, sandbox) == BASE
    crlf = BASE.replace('\n', '\r\n')
    assert m.aggregate(crlf, sandbox).encode() == crlf.encode()
    (sandbox / '0002.internal.md').write_text('- New\n', encoding='utf-8')
    assert m.aggregate('## Unreleased\n', sandbox) == '## Unreleased\n\n### Internal\n\n- New\n'
    (sandbox / '0002.internal.md').unlink()
    (sandbox / '0010.user.md').write_text('- New\n', encoding='utf-8')
    assert m.aggregate('## Unreleased\n', sandbox) == '## Unreleased\n\n- New\n'
    output = m.aggregate('## Unreleased\n\n### Internal\n\n- Old\n', sandbox)
    assert output == '## Unreleased\n\n- New\n\n### Internal\n\n- Old\n'
    output = m.aggregate(crlf, sandbox)
    assert output[output.index('## 1.2.0'):].encode() == crlf[crlf.index('## 1.2.0'):].encode()


def test_numeric_order_within_each_category(sandbox):
    for category in ('user', 'internal'):
        directory = sandbox / category; directory.mkdir()
        for order in ('0010', '0002'):
            (directory / f'{order}.{category}.md').write_text(f'- Order {order}\n')
        output = m.aggregate(BASE, directory)
        assert output.index('- Order 0002') < output.index('- Order 0010')


@pytest.mark.parametrize('body', [b'', b'\n \n', b'not a list', b'- \n', b'- \xff',
    b'- ok\n```md\n## Unreleased\n', b'- ok\n## Unreleased\n',
    b'- ok\n### Internal\n', b'- ok\n## v1.2.3\n', b'- ok\n  ### Internal ###\n'])
def test_fragment_refusals_are_atomic(sandbox, body):
    fragments = sandbox / 'fragments'; fragments.mkdir()
    (fragments / '0001.user.md').write_bytes(b'- Valid first\n')
    bad = fragments / '0002.internal.md'; bad.write_bytes(body)
    base = sandbox / 'base.md'; base.write_bytes(BASE.encode())
    before = snapshot(fragments)
    with pytest.raises((ValueError, LookupError, UnicodeError)):
        m.aggregate(BASE, fragments)
    result = cli(base, fragments)
    assert result.returncode != 0 and result.stdout == b'' and result.stderr
    assert snapshot(fragments) == before and base.read_bytes() == BASE.encode()


@pytest.mark.parametrize('version', ['v1.2.3-rc.1', '1.2.3-rc.1', 'v1.2.3+build.1',
    '1.2.3+build.1', 'v1.2.3-rc.1+build.1', '1.2.3-rc.1+build.1'])
@pytest.mark.parametrize('title', ['', ' — 2026-01-01'])
def test_release_version_heading_refusal_is_atomic(sandbox, version, title):
    fragments = sandbox / 'fragments'; fragments.mkdir()
    (fragments / '0001.user.md').write_text('- Valid first\n', encoding='utf-8')
    (fragments / '0002.internal.md').write_text(
        f'- New note\n## {version}{title}\n- Injected release\n', encoding='utf-8')
    base = sandbox / 'base.md'; base.write_bytes(BASE.encode())
    before = snapshot(fragments)
    with pytest.raises(ValueError, match='Fragment heading injection'):
        m.aggregate(BASE, fragments)
    result = cli(base, fragments)
    assert result.returncode == 1 and result.stdout == b''
    assert result.stderr == b'Fragment heading injection\n'
    assert snapshot(fragments) == before and base.read_bytes() == BASE.encode()


@pytest.mark.parametrize('bad', ['0001.internal.md', '1.user.md', '0002.private.md',
    '0002.user.txt', '../0002.user.md', 'symlink', 'directory', 'fifo', 'linked-dir', 'missing-dir'])
def test_names_types_duplicates_and_traversal(sandbox, bad):
    fragments = sandbox / 'fragments'; fragments.mkdir()
    (fragments / '0001.user.md').write_text('- Valid\n')
    base = sandbox / 'base.md'; base.write_bytes(BASE.encode())
    selected = fragments
    if bad == 'symlink':
        (fragments / '0002.user.md').symlink_to(base)
    elif bad == 'directory':
        (fragments / '0002.user.md').mkdir()
    elif bad == 'fifo':
        os.mkfifo(fragments / '0002.user.md')
    elif bad == 'linked-dir':
        selected = sandbox / 'alias'; selected.symlink_to(fragments, target_is_directory=True)
    elif bad == 'missing-dir':
        selected = sandbox / 'absent'
    else:
        (fragments / bad).write_text('- Bad\n')
        if '..' in bad:
            selected = fragments / '..' / 'fragments'
    before = snapshot(fragments)
    with patch.object(m, 'read_regular', side_effect=AssertionError('must validate before any fragment read')):
        with pytest.raises((ValueError, OSError)):
            m.aggregate(BASE, selected)
    result = cli(base, selected)
    assert result.returncode != 0 and result.stdout == b'' and result.stderr
    assert snapshot(fragments) == before and base.read_bytes() == BASE.encode()


@pytest.mark.parametrize('base', ['', '## 1.2.0\n- Released\n', '## Unreleased\n## Unreleased\n',
    '## Unreleased\n### Internal\n### Internal\n', '## Unreleased\n```\n'])
def test_base_refusals(sandbox, base):
    fragments = sandbox / 'fragments'; fragments.mkdir()
    (fragments / '0001.user.md').write_text('- New\n')
    path = sandbox / 'base.md'; path.write_text(base)
    with pytest.raises((ValueError, LookupError)):
        m.aggregate(base, fragments)
    result = cli(path, fragments)
    assert result.returncode != 0 and result.stdout == b'' and result.stderr
    assert path.read_text() == base and (fragments / '0001.user.md').read_text() == '- New\n'
