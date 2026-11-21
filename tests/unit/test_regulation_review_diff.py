"""Whole CLI results: missing evidence must never masquerade as agreement."""
import json
import shlex
import socket
import subprocess
import sys

import pytest

from skippercast.pipeline import regulation_review as review
from tests._support import ROOT


OLD = 'a' * 64
NEW = 'b' * 64
HTML = 'text-and-links-v4'
PDF = 'pdf-bytes-v1'
ECFR = 'ecfr-section-text-v1'


def _record(digest: str | int = OLD, normalization: str | None = HTML, status='ok'):
    return {'status': status, 'data': {'content_sha256': digest, 'normalization': normalization}}


def _packet(folder, sources):
    folder.mkdir(parents=True)
    (folder / 'packet.json').write_text(json.dumps({'schema_version': 1, 'sources': sources}), encoding='utf-8')
    return folder


@pytest.fixture
def diff(tmp_path, monkeypatch, capsys):
    def run(old, new, *options):
        _packet(tmp_path / 'old', old)
        _packet(tmp_path / 'new', new)
        return invoke(*options)

    def invoke(*options):
        monkeypatch.setattr(sys, 'argv', ['regulation_review', 'diff', '--old', str(tmp_path / 'old'),
                                        '--new', str(tmp_path / 'new'), *options])
        code = review.main()
        return code, *capsys.readouterr()

    return run, invoke


def test_c1_source_union_in_sorted_order(diff):
    # Looking at only one packet would lose a removal or addition.
    run, _ = diff
    assert run({'removed-page': _record(), 'same-page': _record()},
               {'same-page': _record(), 'added-page': _record()}) == (
        0, 'added-page: added\nremoved-page: removed\nsame-page: unchanged\n', '')


@pytest.mark.parametrize(('source', 'output'), [('added-page', 'added-page: added\n'), ('unknown-page', '')])
def test_c1_source_filter(diff, source, output):
    # Filtering must also allow an ID that exists only in the new packet.
    run, _ = diff
    assert run({'removed-page': _record()}, {'added-page': _record()}, '--source', source) == (0, output, '')


@pytest.mark.parametrize(('new', 'reason'), [
    ({'status': 'failed', 'data': None}, "status 'failed'"),
    (_record(status='retained'), "status 'retained'"),
    ({'status': 'ok', 'data': None}, 'no data'),
    ({'status': 'ok', 'data': {'normalization': HTML}}, 'missing or invalid content_sha256'),
    (_record(digest='A' * 64), 'missing or invalid content_sha256'),
    (_record(digest='a' * 63), 'missing or invalid content_sha256'),
    (_record(digest=123), 'missing or invalid content_sha256'),
    (_record(normalization=None), 'missing or invalid normalization'),
])
def test_c1_unavailable_evidence_precedes_hash_comparison(diff, new, reason):
    # A retained matching hash or an unusable replacement is not a successful reread.
    run, _ = diff
    assert run({'page': _record()}, {'page': new}) == (0, f'page: unavailable: new {reason}\n', '')


def test_c1_equal_hash_with_different_normalization_is_incomparable(diff):
    run, _ = diff
    assert run({'page': _record()}, {'page': _record(normalization=PDF)}) == (
        0, 'page: incomparable: normalization text-and-links-v4 vs pdf-bytes-v1\n', '')


def test_c2_changed_html_prints_unified_diff(tmp_path, diff):
    # Hash-only output would hide the changed terms even though the text was saved.
    _, invoke = diff
    old_dir = _packet(tmp_path / 'old', {'page': _record()})
    new_dir = _packet(tmp_path / 'new', {'page': _record(NEW)})
    (old_dir / 'page.txt').write_text('Limit: two\nDOCUMENT LINKS', encoding='utf-8')
    (new_dir / 'page.txt').write_text('Limit: one\nDOCUMENT LINKS', encoding='utf-8')
    assert invoke() == (0, 'page: changed\n--- old/page.txt\n+++ new/page.txt\n'
                        '@@ -1,2 +1,2 @@\n-Limit: two\n+Limit: one\n DOCUMENT LINKS\n', '')


@pytest.mark.parametrize('n', [98, 99])
def test_c2_truncates_only_above_200_diff_lines(tmp_path, diff, n):
    # The cap counts diff headers, not the verdict, and must not cut a 200-line diff short.
    _, invoke = diff
    old_dir = _packet(tmp_path / 'old', {'page': _record()})
    new_dir = _packet(tmp_path / 'new', {'page': _record(NEW)})
    (old_dir / 'page.txt').write_text('old line\n' * n, encoding='utf-8')
    (new_dir / 'page.txt').write_text('new line\n' * (n + 1), encoding='utf-8')
    expected = ('page: changed\n--- old/page.txt\n+++ new/page.txt\n'
                f'@@ -1,{n} +1,{n + 1} @@\n' + '-old line\n' * n
                + '+new line\n' * (197 - n) + ('truncated\n' if n == 99 else ''))
    assert invoke() == (0, expected, '')


@pytest.mark.parametrize(('normalization', 'sidecar', 'note'), [
    (PDF, 'pdf', 'PDF bytes changed: read both files'),
    (ECFR, 'txt', 'hash-only: manual review (no saved eCFR-normalized text to diff)'),
    ('text-and-links-v3', 'txt', 'hash-only: manual review (no saved text to diff)'),
    (HTML, None, 'hash-only: manual review (no saved text to diff)'),
    (HTML, 'escaped', 'hash-only: manual review (no saved text to diff)'),
])
def test_c2_changed_sources_without_comparable_text(tmp_path, diff, normalization, sidecar, note):
    # eCFR and older normalizations must not accidentally compare generic .txt files.
    _, invoke = diff
    old_dir = _packet(tmp_path / 'old', {'page': _record(normalization=normalization)})
    new_dir = _packet(tmp_path / 'new', {'page': _record(NEW, normalization)})
    if sidecar == 'escaped':
        outside = tmp_path / 'not-a-packet-sidecar.txt'
        outside.write_text('private fixture text', encoding='utf-8')
        (old_dir / 'page.txt').symlink_to(outside)
        (new_dir / 'page.txt').write_text('new text', encoding='utf-8')
    elif sidecar:
        for folder, content in [(old_dir, b'old'), (new_dir, b'new')]:
            (folder / f'page.{sidecar}').write_bytes(b'%PDF-' + content if sidecar == 'pdf' else content)
    else:
        (old_dir / 'page.txt').write_text('one-sided text', encoding='utf-8')
    assert invoke() == (0, f'page: changed\nold sha256: {OLD}\nnew sha256: {NEW}\n{note}\n', '')


def test_c3_diff_leaves_inputs_and_review_files_untouched(tmp_path, diff, monkeypatch):
    # Catch accidental entry into the collect/apply path or a write to either packet.
    _, invoke = diff
    old_dir = _packet(tmp_path / 'old', {'page': _record()})
    new_dir = _packet(tmp_path / 'new', {'page': _record(NEW)})
    for path, content in [(tmp_path / 'registry.json', '{}'), (tmp_path / 'decision.json', '{}'),
                          (old_dir / 'page.txt', 'before'), (new_dir / 'page.txt', 'after')]:
        path.write_text(content, encoding='utf-8')
    monkeypatch.chdir(tmp_path)

    def refuse(*args, **kwargs):
        pytest.fail('diff must not connect to a source or open the review registry')

    def snapshot():
        return {path.relative_to(tmp_path): (path.stat().st_mtime_ns, path.read_bytes() if path.is_file() else None)
                for path in (tmp_path, *tmp_path.rglob('*'))}

    before = snapshot()
    with monkeypatch.context() as patch:
        patch.setattr(review, 'jurisdiction_files', refuse)
        patch.setattr(socket, 'socket', refuse)
        assert invoke() == (0, 'page: changed\n--- old/page.txt\n+++ new/page.txt\n'
                            '@@ -1 +1 @@\n-before\n+after\n', '')
    assert snapshot() == before


@pytest.mark.parametrize(('payload', 'message'), [
    (None, 'missing packet.json'),
    ('{', 'Expecting property name enclosed in double quotes: line 1 column 2 (char 1)'),
    ('[]', 'packet.sources must be an object'),
    ('{"sources": []}', 'packet.sources must be an object'),
    ('{"sources": {"page": null}}', 'packet.sources.page must be an object'),
    ('{"sources": {"page": {"data": []}}}', 'packet.sources.page.data must be an object or null'),
])
def test_c3_missing_or_malformed_packet_exits_2_without_partial_verdict(tmp_path, diff, payload, message):
    _, invoke = diff
    _packet(tmp_path / 'old', {'page': _record()})
    new_dir = tmp_path / 'new'
    new_dir.mkdir()
    if payload is not None:
        (new_dir / 'packet.json').write_text(payload, encoding='utf-8')
    assert invoke() == (2, '', f'regulation review diff refused: new: {message}\n')


def test_c4_documented_command_runs_against_saved_packets(tmp_path):
    # Exercise the actual runbook invocation so documentation cannot teach a broken command.
    _packet(tmp_path / 'var/rules/previous-review', {'page': _record()})
    _packet(tmp_path / 'var/rules/new-review', {'page': _record()})
    doc = (ROOT / 'docs/regulations.md').read_text(encoding='utf-8')
    (line,) = (line for line in doc.splitlines() if 'regulation_review diff --old' in line)
    python, *args = shlex.split(line.split('`')[1])
    assert python == 'python'
    result = subprocess.run([sys.executable, *args], cwd=tmp_path, capture_output=True, text=True)
    assert (result.returncode, result.stdout, result.stderr) == (0, 'page: unchanged\n', '')


def test_c5_matching_failures_never_count_as_unchanged(diff):
    # Distinct from a one-sided failure: two null records must not compare equal.
    run, _ = diff
    failed = {'status': 'failed', 'data': None}
    assert run({'page': failed}, {'page': failed}) == (
        0, "page: unavailable: old status 'failed'; new status 'failed'\n", '')
