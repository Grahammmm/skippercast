"""Planet refresh receipts: a failed run keeps the last good receipt; a corrupt receipt is skipped.

Everything is offline: `kelp._metadata` is replaced (by a raising function for the failure
cases, by canned Zenodo JSON/HTML for the no_change control) and no archive is ever fetched.
"""
from datetime import date
import hashlib
import json

import pytest

from skippercast.relief import kelp
from tests.gis.test_relief_kelp import BASE, NAME, PAGE, RIGHTS, VERSION

SOURCE = 'Zenodo Planet polygons'
MD5 = 'a' * 32
SIZE = 1234
OLD = {'source': SOURCE, 'status': 'updated', 'version': '1', 'checked_date': '2026-11-18'}
NEW = {'source': SOURCE, 'status': 'updated', 'version': '2', 'checked_date': '2026-11-19'}


def write(directory, day, body):
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f'2026-11-{day}-planet.json'
    path.write_text(body if isinstance(body, str) else json.dumps(body), encoding='utf-8')
    return path


def refresh(root, day, **kwargs):
    return kelp.refresh_planet(archive_root=root / 'archives', out=root / 'out', waters=root / 'waters.geojson',
                               receipt_dir=root / 'receipts', date=date(2026, 11, day), **kwargs)


def broken_metadata(_url):
    raise RuntimeError('Zenodo is down')


@pytest.mark.parametrize('prior', ['updated', 'no_change'])
def test_failed_same_day_run_keeps_the_good_receipt(tmp_path, monkeypatch, prior):
    # Bug caught: the failure receipt replaces today's good one, so _last_success falls back
    # to an older identity and the next run downloads and rebuilds the layer for nothing.
    receipts = tmp_path / 'receipts'
    write(receipts, '18', OLD)
    good = write(receipts, '19', {**NEW, 'status': prior})
    before = good.read_bytes()
    monkeypatch.setattr(kelp, '_metadata', broken_metadata)
    result = refresh(tmp_path, 19)
    assert result['status'] == 'access_failed' and result['error'] == 'RuntimeError'
    assert good.read_bytes() == before
    assert kelp._last_success(receipts)['version'] == '2'
    failed = receipts / '2026-11-19-planet-failed.json'  # the failure is still recorded, elsewhere
    assert json.loads(failed.read_text(encoding='utf-8')) == result


@pytest.mark.parametrize('prior', [None, {**NEW, 'status': 'access_failed'}, {**NEW, 'status': 'rights_changed'}])
def test_failure_still_replaces_a_same_day_non_success_receipt(tmp_path, monkeypatch, prior):
    # Bug caught (over-correction): the guard moves every failure aside, so the usual dated
    # failure receipt is never written when there is no good same-day receipt to protect.
    receipts = tmp_path / 'receipts'
    write(receipts, '18', OLD)
    if prior:
        write(receipts, '19', prior)
    monkeypatch.setattr(kelp, '_metadata', broken_metadata)
    result = refresh(tmp_path, 19)
    assert json.loads((receipts / '2026-11-19-planet.json').read_text(encoding='utf-8')) == result
    assert not (receipts / '2026-11-19-planet-failed.json').exists()
    assert kelp._last_success(receipts)['version'] == '1'


@pytest.mark.parametrize('body', [
    '{"status": "upda',            # truncated write
    '[]',                          # not an object
    'null',
    '{"source": "%s"}' % SOURCE,   # no status
    '{"status": "updated"}',       # no source
    '{"status": ["updated"], "source": "%s"}' % SOURCE,  # unhashable status
    '{"status": "updated", "source": "Landsat"}',        # another source's receipt
    '',
])
def test_unusable_newer_receipt_is_skipped_for_the_newest_valid_success(tmp_path, body):
    # Bug caught: one bad dated file raises (JSONDecodeError/TypeError/KeyError), which
    # refresh_planet reports as access_failed on every later run until a human deletes it.
    write(tmp_path, '18', OLD)
    write(tmp_path, '19', {**NEW, 'status': 'access_failed'})
    write(tmp_path, '20', body)
    assert kelp._last_success(tmp_path) == OLD


def test_unreadable_receipt_bytes_and_directory_are_skipped(tmp_path):
    write(tmp_path, '18', OLD)
    (tmp_path / '2026-11-19-planet.json').write_bytes(b'\xff\xfe\x00{')
    (tmp_path / '2026-11-20-planet.json').mkdir()
    assert kelp._last_success(tmp_path) == OLD


def test_healthy_receipts_are_unchanged_controls(tmp_path):
    # Bug caught: the skip rule also skips a legitimate success and forces a rebuild.
    assert kelp._last_success(tmp_path) == {}
    write(tmp_path, '18', OLD)
    assert kelp._last_success(tmp_path) == OLD
    write(tmp_path, '19', {**NEW, 'status': 'no_change'})
    assert kelp._last_success(tmp_path) == {**NEW, 'status': 'no_change'}
    write(tmp_path, '20', {**NEW, 'status': 'access_failed'})
    assert kelp._last_success(tmp_path)['checked_date'] == '2026-11-19'


def test_refresh_with_a_corrupt_old_receipt_still_reports_no_change(tmp_path, monkeypatch):
    # Bug caught: a corrupt dated receipt turns an otherwise clean refresh into access_failed,
    # and a same-day no_change rerun is wrongly diverted to the -failed file.
    waters = b'{"synthetic": "mask"}'
    (tmp_path / 'waters.geojson').write_bytes(waters)
    output = tmp_path / 'out/_kelp/planet-2024/kelp.pmtiles'
    output.parent.mkdir(parents=True)
    output.write_bytes(b'tiles')
    digest = hashlib.sha256(b'tiles').hexdigest()
    previous = {**NEW, 'version': VERSION, 'md5': MD5, 'size': SIZE, 'newest_september': '2024-09',
                'waters_sha256': hashlib.sha256(waters).hexdigest(), 'output_sha256': digest}
    receipts = tmp_path / 'receipts'
    write(receipts, '19', previous)
    write(receipts, '20', '{"status": "upda')
    record = {'id': int(VERSION), 'conceptdoi': kelp.POLYGON_CONCEPT, 'metadata': {'license': {'id': 'cc-by-4.0'}},
              'files': [{'key': NAME, 'checksum': 'md5:' + MD5, 'size': SIZE}]}
    pages = {kelp.LATEST: json.dumps(record), PAGE: RIGHTS}
    monkeypatch.setattr(kelp, '_metadata', pages.__getitem__)
    result = refresh(tmp_path, 19)
    assert BASE in PAGE and result['status'] == 'no_change' and result['output_sha256'] == digest
    assert json.loads((receipts / '2026-11-19-planet.json').read_text(encoding='utf-8')) == result
    assert not (receipts / '2026-11-19-planet-failed.json').exists()
