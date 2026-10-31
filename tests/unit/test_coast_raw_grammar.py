"""Producer-exact prefetch row/snapshot grammar and closed provenance scalars (no GIS)."""
import json

import pytest

from tests.coast_contract_factory import load_helper
from skippercast.coastal import prefetch

raw = load_helper('coast_raw')
SEG = list(prefetch.SEGMENTS)


def row(**changes):
    value = dict(url='https://records.example/a.bag', final_url='https://records.example/a.bag', bytes=3, sha256='a' * 64,
                 etag=None, last_modified=None, fetched_at=prefetch.stamp(), licence='owned synthetic', segments=SEG[:2],
                 path='/origin/raw/a.bag', review_required=True, verification='publisher-sha256')
    value.update(changes)
    return value


def line(**changes):
    return (json.dumps(row(**changes), sort_keys=True) + '\n').encode()


def test_producer_exact_rows_parse():
    assert len(raw.parse_rows(line() + line(url='https://records.example/b.bag'))) == 2
    assert raw.parse_rows(line(fetched_at='2026-10-21T01:02:03.000004+00:00'), single=True)[0]['bytes'] == 3
    assert raw.parse_rows(line(fetched_at='2026-10-21T01:02:03+00:00', segments=SEG))


@pytest.mark.parametrize('changes', [
    dict(fetched_at='2026-10-21T00:00:00Z'), dict(fetched_at='2026-10-21T00:00:00+01:00'),
    dict(fetched_at='2026-10-21T00:00:00.123+00:00'), dict(fetched_at='2026-10-21T00:00+00:00'),
    dict(fetched_at='2026-13-21T00:00:00+00:00'), dict(fetched_at=None),
    dict(segments=[]), dict(segments=[SEG[0], SEG[0]]), dict(segments=list(reversed(SEG[:2]))), dict(segments=['synthetic']),
    dict(segments=SEG[0]), dict(bytes=True), dict(bytes=-1), dict(bytes='3'), dict(sha256='A' * 64), dict(etag=5),
    dict(last_modified=[]), dict(review_required=False), dict(verification='sha256'), dict(licence=''), dict(url=''),
    dict(url={'path': 'x'}), dict(final_url=None), dict(path='a.bag'), dict(path='/'), dict(path='/origin/../a.bag'),
    dict(path='/origin//a.bag'), dict(path='/origin/a.bag/'), dict(path='/origin/a\\b.bag'), dict(path='/origin/a\x01.bag'),
    dict(extra='field'), dict(schema='coastal-prefetch-row-v1'), dict(raw={'root_id': 'raw:campaign'}),
])
def test_field_grammar_refuses(changes):
    with pytest.raises(ValueError):
        raw.parse_rows(line(**changes))


def test_missing_field_refuses():
    value = row()
    del value['etag']
    with pytest.raises(ValueError):
        raw.parse_rows((json.dumps(value, sort_keys=True) + '\n').encode())


@pytest.mark.parametrize('bytes_', [
    b'', line()[:-1], line().replace(b'\n', b'\r\n'), line() + b'\n', b'\n' + line(),
    (json.dumps(row(), sort_keys=True, indent=1) + '\n').encode(),
    (json.dumps(row()) + '\n').encode() if json.dumps(row()) != json.dumps(row(), sort_keys=True) else line() + b' \n',
    line().replace(b'"etag": null', b'"etag": null, "etag": null'),
    line(url='https://records.example/b.bag') + line(), line() + line(),
    line() + line(url='https://records.example/b.bag', fetched_at='2026-10-21T00:00:00Z'),
    b'[' + line()[:-1] + b']\n', b'"text"\n', line().replace(b'3,', b'NaN,'),
], ids=[  # explicit ids: the bytes carry prefetch.stamp(), so byte-derived ids differ per process (xdist)
    'empty', 'no-final-newline', 'crlf', 'trailing-blank-line', 'leading-blank-line',
    'indented', 'unsorted-keys-or-trailing-space', 'duplicate-key',
    'rows-unsorted', 'rows-duplicate', 'second-row-bad-stamp',
    'json-array', 'json-string', 'nan',
])
def test_snapshot_bytes_refuse(bytes_):
    with pytest.raises(ValueError):
        raw.parse_rows(bytes_)


def test_single_row_must_be_one_line():
    with pytest.raises(ValueError, match='one line'):
        raw.parse_rows(line() + line(url='https://records.example/b.bag'), single=True)


def test_inventory_subset_closed():
    value = dict(id='x', title='t', kind='bathymetry', format='bag', url='https://records.example/a.bag', sha256='a' * 64,
                 horizontal_crs='EPSG:26911', vertical_datum='MLLW')
    raw.inventory(value)
    for change in (dict(evidence=['dist/data/x.json#/a']), dict(field_evidence={}), dict(horizontal_crs='unknown'),
                   dict(kind='terrain'), dict(format='tif'), dict(sha256='nope'), dict(title=''), dict(id=None)):
        with pytest.raises(ValueError):
            raw.inventory(dict(value, **change))
    with pytest.raises(ValueError):
        raw.inventory({k: v for k, v in value.items() if k != 'title'})


def test_typed_and_origin_scalars():
    ref = dict(root_id='queue:synthetic', path='a/b.json', sha256='a' * 64, bytes=1)
    raw.typed(ref, root='queue:synthetic', suffix='.json')
    for change in (dict(root_id='queue:other'), dict(path='a/b.jsonl'), dict(bytes=True), dict(bytes=-1), dict(path='/a'),
                   dict(sha256='A' * 64), dict(extra=1), dict(root_id='raw:campaign')):
        with pytest.raises(ValueError):
            raw.typed(dict(ref, **change), root='queue:synthetic', suffix='.json')
    with pytest.raises(ValueError):
        raw.typed({k: v for k, v in ref.items() if k != 'bytes'})
    assert raw.absolute('/origin/raw') == '/origin/raw'
    for bad in ('/', 'origin', '/origin/', '/origin/./raw', '/origin\\raw', '/origin/\x7f', '', None):
        with pytest.raises(ValueError):
            raw.absolute(bad)
