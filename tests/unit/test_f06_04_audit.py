"""F06-04 / SCA-261: finish a fully receipted download after a crash, without a request.

Contract: a complete .part whose size, reviewed publisher digest, URL, final path and both
receipts (manifest and .part.json) agree is promoted locally with NO request of any kind,
even when the publisher sent no strong ETag. Any missing/contradictory receipt, or a truly
partial file, still holds exactly as before. Range stitching, plan identity, capacity and the
existing-final collision hold are untouched. Offline: the server double records every call.
"""
import hashlib
import json
from pathlib import Path

import pytest

from skippercast.coastal import prefetch as p
from tests.unit.test_coast_prefetch import DATA, Server, isolated_retry_state, receipt, row, runner  # noqa: F401


def crash_before_rename(tmp_path, validator=None):
    """Real run killed at the .part -> final rename (both receipts already saved); no ETag."""
    server = Server(validator=validator)
    run = runner(tmp_path, server)
    real = p.os.replace

    def crash(src, dst, *args, **kwargs):
        if Path(src).suffix == '.part':
            raise OSError('synthetic crash between receipt and rename')
        return real(src, dst, *args, **kwargs)

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(p.os, 'replace', crash)
        assert run.run() == 2
    partial = run.root / 'noaa-nos' / (p.filename(row()) + '.part')
    meta = partial.with_name(partial.name + '.json')
    assert partial.read_bytes() == DATA and meta.exists() and not partial.with_suffix('').exists()
    assert (run.mirror / 'noaa-nos.jsonl').read_bytes() == (run.root / 'noaa-nos/manifest.jsonl').read_bytes()
    server.calls.clear()
    return server, run, partial, meta


def edit_receipts(run, **changes):
    """Rewrite the one manifest record in the primary and mirror copies (they stay equal)."""
    primary = run.root / 'noaa-nos/manifest.jsonl'
    record = {**json.loads(primary.read_text()), **changes}
    text = json.dumps(record, sort_keys=True) + '\n'
    primary.write_text(text)
    (run.mirror / 'noaa-nos.jsonl').write_text(text)


def test_complete_receipted_part_is_promoted_with_no_request(tmp_path):
    # Positive control; fails if a crash after receipts leaves operator work (the cited F06-04 bug).
    server, run, partial, meta = crash_before_rename(tmp_path)
    before = receipt(run)
    restarted = runner(tmp_path, server)
    assert restarted.run() == 0
    assert server.calls == []  # no HEAD, no GET: the bytes were already verified
    final = Path(before['path'])
    assert final.read_bytes() == DATA
    assert not partial.exists() and not meta.exists()
    after = receipt(restarted)
    assert after['sha256'] == hashlib.sha256(DATA).hexdigest() and after['fetched_at'] == before['fetched_at']
    assert (restarted.mirror / 'noaa-nos.jsonl').read_bytes() == (restarted.root / 'noaa-nos/manifest.jsonl').read_bytes()


@pytest.mark.parametrize('case', [
    'no-part-receipt', 'no-manifest-receipt', 'manifest-digest', 'manifest-size', 'manifest-path',
    'manifest-not-publisher-verified', 'part-receipt-digest', 'part-receipt-url', 'part-final-url',
    'corrupt-same-size', 'truncated-part', 'plan-without-digest', 'plan-other-digest'])
def test_missing_or_contradictory_receipts_still_hold(tmp_path, case):
    # Negative controls; each fails if recovery trusts a single fact instead of all of them.
    server, run, partial, meta = crash_before_rename(tmp_path)
    plan_row = row()
    if case == 'no-part-receipt':
        meta.unlink()
    elif case == 'no-manifest-receipt':
        (run.root / 'noaa-nos/manifest.jsonl').write_text('')
        (run.mirror / 'noaa-nos.jsonl').write_text('')
    elif case == 'manifest-digest':
        edit_receipts(run, sha256='0' * 64)
    elif case == 'manifest-size':
        edit_receipts(run, bytes=len(DATA) + 1)
    elif case == 'manifest-path':
        edit_receipts(run, path=str(tmp_path / 'elsewhere.bin'))
    elif case == 'manifest-not-publisher-verified':
        edit_receipts(run, verification='http-size-and-local-sha256')
    elif case in ('part-receipt-digest', 'part-receipt-url', 'part-final-url'):
        data = json.loads(meta.read_text())
        key = {'part-receipt-digest': 'sha256', 'part-receipt-url': 'url', 'part-final-url': 'final_url'}[case]
        data[key] = '1' * 64 if key == 'sha256' else 'https://pubs.usgs.gov/other'
        meta.write_text(json.dumps(data))
    elif case == 'corrupt-same-size':
        partial.write_bytes(b'x' * len(DATA))
    elif case == 'truncated-part':
        partial.write_bytes(DATA[:4])
    elif case == 'plan-without-digest':
        del plan_row['sha256']
    else:
        plan_row['sha256'] = '2' * 64
    kept = partial.read_bytes()
    restarted = runner(tmp_path, server, {'schema_version': 1, 'files': [plan_row], 'unresolved': []})
    assert restarted.run() == 2
    assert [call[1] for call in server.calls] == ['HEAD']  # held at identity check; never a body request
    assert partial.read_bytes() == kept  # preserved for the operator
    assert not (restarted.root / 'noaa-nos' / p.filename(row())).exists()


def test_strong_etag_does_not_repair_a_complete_part_with_bad_receipts(tmp_path):
    # Guards review return 2: a strong ETag makes offset == total, which used to rewrite the
    # manifest and promote a complete .part whose manifest receipt was absent or contradicted.
    for change in ('missing', 'digest', 'path'):
        case_dir = tmp_path / change
        case_dir.mkdir()
        server, run, partial, meta = crash_before_rename(case_dir, validator='"v1"')
        if change == 'missing':
            (run.root / 'noaa-nos/manifest.jsonl').write_text('')
            (run.mirror / 'noaa-nos.jsonl').write_text('')
        else:
            edit_receipts(run, **({'sha256': '0' * 64} if change == 'digest' else {'path': str(case_dir / 'x')}))
        restarted = runner(case_dir, server)
        assert restarted.run() == 2
        assert [call[1] for call in server.calls] == ['HEAD']
        assert partial.read_bytes() == DATA and meta.exists()
        assert not (restarted.root / 'noaa-nos' / p.filename(row())).exists()


def test_strong_etag_complete_receipted_part_is_still_promoted_without_request(tmp_path):
    server, run, partial, meta = crash_before_rename(tmp_path, validator='"v1"')
    restarted = runner(tmp_path, server)
    assert restarted.run() == 0 and server.calls == []
    assert Path(receipt(restarted)['path']).read_bytes() == DATA


@pytest.mark.parametrize('key', ['sha256', 'bytes', 'path', 'verification'])
@pytest.mark.parametrize('side', ['primary', 'mirror'])
def test_conflicting_primary_and_mirror_receipts_hold_and_are_both_preserved(tmp_path, key, side):
    # Guards review return 1: same URL, different identity facts. Neither copy may be flushed
    # over the other, and the complete .part must not be promoted.
    server, run, partial, meta = crash_before_rename(tmp_path)
    primary, mirror = run.root / 'noaa-nos/manifest.jsonl', run.mirror / 'noaa-nos.jsonl'
    target = primary if side == 'primary' else mirror
    record = json.loads(target.read_text())
    record[key] = {'sha256': '0' * 64, 'bytes': len(DATA) + 1, 'path': '/elsewhere',
                   'verification': 'http-size-and-local-sha256'}[key]
    target.write_text(json.dumps(record, sort_keys=True) + '\n')
    kept = primary.read_bytes(), mirror.read_bytes()
    with pytest.raises(p.Hold, match='contradict'):  # stops the whole run, like the lost-primary hold
        runner(tmp_path, server).run()
    assert server.calls == []
    assert (primary.read_bytes(), mirror.read_bytes()) == kept
    assert partial.read_bytes() == DATA and meta.exists()
    assert not (run.root / 'noaa-nos' / p.filename(row())).exists()


def test_licence_only_difference_between_copies_is_still_repaired(tmp_path):
    # A stale mirror that differs only in refreshable metadata is the old crash-repair case.
    server, run, partial, meta = crash_before_rename(tmp_path)
    mirror = run.mirror / 'noaa-nos.jsonl'
    record = json.loads(mirror.read_text())
    record['licence'] = 'stale'
    mirror.write_text(json.dumps(record, sort_keys=True) + '\n')
    assert runner(tmp_path, server).run() == 0 and server.calls == []


def test_existing_final_collision_hold_is_unchanged(tmp_path):
    # Guard for the "do not relax" clause: a final file without a matching receipt stays a hold.
    server, run, partial, meta = crash_before_rename(tmp_path)
    final = run.root / 'noaa-nos' / p.filename(row())
    final.write_bytes(b'someone else')
    restarted = runner(tmp_path, server)
    assert restarted.run() == 2
    assert server.calls == [] and final.read_bytes() == b'someone else' and partial.read_bytes() == DATA
