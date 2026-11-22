import json
import subprocess
import sys

import pytest

from scripts.relief import central_input_compare
from tests._support import ROOT


def record(tmp_path, **fields):
    return {'schema': 'sc-run-inputs/1', 'region': 'central', 'inputs': {},
            'coarse_source': None, 'coarse_date': None, 'norm': str(tmp_path / 'norm'),
            **fields}


def write(path, doc):
    path.write_text(json.dumps(doc), encoding='utf-8')
    return str(path)


def binding(tmp_path, name, digit):
    # No referenced file exists: a byte-checking implementation cannot compare these records.
    return {'path': str(tmp_path / name), 'sha256': digit * 64}


def test_reports_binding_kinds_and_independent_metadata(tmp_path):
    # Protect retry-review semantics: neither a moved identical pin nor a
    # metadata-only change should be reported as a content change.
    old_coarse = binding(tmp_path, 'old-coarse.tif', 'a')
    new_coarse = binding(tmp_path, 'new-coarse.tif', 'a')
    old_water = binding(tmp_path, 'water.tif', 'b')
    new_water = binding(tmp_path, 'water.tif', 'c')
    census = binding(tmp_path, 'census.json', 'd')
    basemap = binding(tmp_path, 'basemap.pmtiles', 'e')
    support = binding(tmp_path, 'qa-support.tif', 'f')
    before = record(tmp_path, inputs={'water': old_water, 'qa_support': support,
                                     'coarse': old_coarse, 'census': census},
                    coarse_source='synthetic-v1')
    after = record(tmp_path, inputs={'qa_support': support, 'coarse': new_coarse,
                                     'water': new_water, 'basemap': basemap},
                   coarse_source='synthetic-v2', coarse_date='2026-01-01', norm=None)
    result = subprocess.run(
        [sys.executable, str(ROOT / 'scripts/relief/central_input_compare.py'),
         write(tmp_path / 'before.json', before), write(tmp_path / 'after.json', after)],
        capture_output=True, text=True, check=True,
    )
    report = json.loads(result.stdout)
    assert list(report['inputs']) == ['basemap', 'census', 'coarse', 'water']
    assert report == {
        'region': 'central',
        'inputs': {
            'basemap': {'kind': 'added', 'before': None, 'after': basemap},
            'census': {'kind': 'removed', 'before': census, 'after': None},
            'coarse': {'kind': 'path-only', 'before': old_coarse, 'after': new_coarse},
            'water': {'kind': 'changed', 'before': old_water, 'after': new_water},
        },
        'coarse': {
            'coarse_source': {'before': 'synthetic-v1', 'after': 'synthetic-v2'},
            'coarse_date': {'before': None, 'after': '2026-01-01'},
        },
        'norm': {'before': str(tmp_path / 'norm'), 'after': None},
    }


def test_hex_case_does_not_change_pin_identity(tmp_path, capsys):
    # A textual comparison would report different content for the same digest.
    coarse = binding(tmp_path, 'coarse.tif', 'a')
    before = record(tmp_path, inputs={'coarse': coarse})
    after = record(tmp_path, inputs={'coarse': {**coarse, 'sha256': 'A' * 64}})
    assert central_input_compare.main([write(tmp_path / 'before.json', before),
                                       write(tmp_path / 'after.json', after)]) == 0
    assert json.loads(capsys.readouterr().out) == {
        'region': 'central', 'inputs': {}, 'coarse': {}, 'norm': None,
    }


@pytest.mark.parametrize(('fields', 'reason'), [
    ({'region': 'north'}, 'different regions'),
    ({'schema': 'sc-run-inputs/2'}, 'expected a sc-run-inputs/1 record'),
    ({'inputs': {'coarse': {'path': 'coarse.tif', 'sha256': 'g' * 64}}}, 'coarse: sha256'),
], ids=['cross-region', 'unsupported-schema', 'bad-pin'])
def test_refuses_incomparable_or_unusable_record(tmp_path, capsys, fields, reason):
    # No report for mismatched regions, guessed schema versions or bogus pins:
    # treating any of them as a valid diff would give a misleading retry review.
    before = write(tmp_path / 'before.json', record(tmp_path))
    after = write(tmp_path / 'after.json', record(tmp_path, **fields))
    with pytest.raises(SystemExit) as exc:
        central_input_compare.main([before, after])
    captured = capsys.readouterr()
    assert exc.value.code == 2
    assert captured.out == ''
    assert reason in captured.err
