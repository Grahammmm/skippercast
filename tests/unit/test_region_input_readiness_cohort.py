"""Fixture-only tests of the offline relief declaration preflight."""

import json
from pathlib import Path
import subprocess
import sys

import pytest

from scripts.coast_diagnostics import region_input_readiness as readiness
from tests._support import ROOT


BOUNDS = [-124, 36, -123, 37]
ZONE = {'coarse': 'unused/grid.tif', 'water': 'unused/water.geojson', 'coarse-source': 'sample-grid'}


def config(root, region, doc=None):
    path = root / 'regions' / region / 'region.json'
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({'id': region, 'bounds': BOUNDS} if doc is None else doc), encoding='utf-8')
    return path


def bindings(root, rows):
    path = root / 'operator-inputs.json'
    path.write_text(json.dumps(rows), encoding='utf-8')
    return path


def cli(root, through, *ids, binding=None):
    args = ['--repo-root', str(root), '--through', through]
    for region in ids:
        args.extend(['--region', region])
    if binding is not None:
        args.extend(['--bindings', str(binding)])
    return args


def test_mixed_cohort_preserves_rows_and_reports_independent_gaps(tmp_path):
    # Drive the file entry point: a reporter that iterates binding keys or aborts on
    # the first bad config cannot preserve the requested order and all gaps.
    for region in ('complete', 'partial', 'omitted'):
        config(tmp_path, region)
    path = bindings(tmp_path, {'complete': ZONE, 'absent': {}, 'partial': {'water': ' '}, 'unrequested': ZONE})
    command = [sys.executable, str(ROOT / 'scripts/coast_diagnostics/region_input_readiness.py'),
               *cli(tmp_path, 'zone', 'partial', 'absent', 'complete', 'omitted', binding=path)]
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    assert result.returncode == 1, result.stderr
    assert result.stderr == ''
    report = json.loads(result.stdout)
    assert report['binding_file'] == 'read'
    assert 'not run or release approval' in report['qualification']
    partial, absent, complete, omitted = report['regions']
    assert [row['region'] for row in report['regions']] == ['partial', 'absent', 'complete', 'omitted']
    assert partial['issues'] == ['missing_declaration:coarse', 'malformed_declaration:water',
                                 'missing_declaration:coarse-source']
    assert 'config_missing' in absent['issues'] and 'missing_declaration:water' in absent['issues']
    assert complete['structurally_complete'] and not complete['issues']
    assert complete['declarations'] == {'coarse': 'declared_unverified', 'water': 'declared_unverified',
                                        'coarse-source': 'declared'}
    assert not omitted['structurally_complete'] and 'binding_row_missing' in omitted['issues']
    assert 'unused/' not in result.stdout


@pytest.mark.parametrize(('stage', 'expected'), [
    ('select', ()), ('mosaic', ()), ('tiles', ()),
    ('zone', ('coarse', 'coarse-source', 'water')),
    ('digests', ('coarse', 'coarse-source', 'water')),
    ('inventory', ('coarse', 'coarse-source', 'water')),
    ('contours', ('coarse', 'coarse-source', 'water')),
    ('package', ('coarse', 'coarse-source', 'water')),
    ('shots', ('basemap', 'coarse', 'coarse-source', 'water')),
    ('qa', ('basemap', 'coarse', 'coarse-source', 'water')),
    ('envelope', ('basemap', 'coarse', 'coarse-source', 'water')),
])
def test_stage_cutoffs_and_optional_coarse_date(tmp_path, capsys, stage, expected):
    # A target-only or off-by-one lookup would lose inherited declarations or
    # pull shots inputs into earlier stages. No fixture supplies a coarse date.
    config(tmp_path, 'sample')
    path = bindings(tmp_path, {'sample': ZONE})
    assert readiness.main(cli(tmp_path, stage, 'sample', binding=path)) == int('basemap' in expected)
    row, = json.loads(capsys.readouterr().out)['regions']
    assert tuple(row['declarations']) == expected
    assert row['issues'] == (['missing_declaration:basemap'] if 'basemap' in expected else [])


def test_only_named_documents_are_read(tmp_path, monkeypatch, capsys):
    # A filesystem existence check of even one payload, repo scan, attempted
    # output write or hidden runner subprocess must fail this complete QA case.
    allowed = {config(tmp_path, 'sample'), config(tmp_path, 'other')}
    path = bindings(tmp_path, {'sample': {**ZONE, 'basemap': 'absent.pmtiles'},
                               'other': {**ZONE, 'basemap': 'other.pmtiles'}})
    allowed.add(path)
    opened = []
    original_open = Path.open

    def only_inputs(self, mode='r', *args, **kwargs):
        assert self in allowed and mode == 'r', (self, mode)
        opened.append(self)
        return original_open(self, mode, *args, **kwargs)

    def unexpected(*args, **kwargs):
        pytest.fail(f'unexpected I/O: {args}')

    with monkeypatch.context() as patch:
        patch.setattr(Path, 'open', only_inputs)
        patch.setattr(Path, 'stat', unexpected)
        patch.setattr(Path, 'iterdir', unexpected)
        patch.setattr(subprocess, 'Popen', unexpected)
        code = readiness.main(cli(tmp_path, 'qa', 'sample', 'other', binding=path))
    assert code == 0
    assert sorted(opened) == sorted(allowed)
    rows = json.loads(capsys.readouterr().out)['regions']
    assert all(row['declarations']['basemap'] == 'declared_unverified' for row in rows)


@pytest.mark.parametrize('bad_bounds', [None, 'WGS84', [1, 2, 3], [1, 2, 3, 4, 5],
                                       [False, 0, 1, 1], ['-1', 0, 1, 1],
                                       [-181, 0, 1, 1], [-1, -91, 1, 1], [-1, 0, 181, 1], [-1, 0, 1, 91],
                                       [1, 0, -1, 1], [0, 0, 0, 1], [-1, 1, 1, 0], [-1, 0, 1, 0],
                                       [-1, 0, float('inf'), 1], [-1, 0, 1, float('nan')], [-1, 0, 10**400, 1]])
def test_invalid_wgs84_does_not_crash_or_hide_identity_errors(tmp_path, capsys, bad_bounds):
    # Invalid coordinates can otherwise pass via bool/string coercion, ordering
    # bugs or unchecked geographic limits; a huge int must not abort the report.
    config(tmp_path, 'sample', {'id': 'wrong-id', 'bounds': bad_bounds})
    config(tmp_path, 'control', {'id': 'control', 'bounds': [-180, -90, 180, 90]})
    assert readiness.main(cli(tmp_path, 'select', 'sample', 'control')) == 1
    bad, good = json.loads(capsys.readouterr().out)['regions']
    assert bad['issues'] == ['config_id_mismatch', 'invalid_wgs84_bounds']
    assert good['structurally_complete']


def test_config_errors_distinguish_bad_json_unreadable_and_bad_ids(tmp_path, capsys):
    # A file I/O error or non-object JSON must not disappear or mask other rows;
    # the traversal spelling must fail identity validation, not load a config.
    config(tmp_path, 'broken').write_bytes(b'\xff')
    config(tmp_path, 'syntax').write_text('{', encoding='utf-8')
    config(tmp_path, 'array', [])
    config(tmp_path, 'invalid-id', {'id': 1, 'bounds': BOUNDS})
    (tmp_path / 'regions' / 'unreadable' / 'region.json').mkdir(parents=True)
    config(tmp_path, 'valid')
    assert readiness.main(cli(tmp_path, 'select', 'broken', 'syntax', 'array', 'unreadable',
                              '../regions/valid', 'invalid-id', 'valid')) == 1
    assert [row['issues'] for row in json.loads(capsys.readouterr().out)['regions']] == [
        ['config_malformed'], ['config_malformed'], ['config_malformed'], ['config_unreadable'],
        ['invalid_region_id'], ['invalid_config_id'], [],
    ]


def test_binding_failures_do_not_replace_cohort_rows(tmp_path, capsys):
    # Distinguish no named file, a missing file, bad top-level JSON, a bad row,
    # and malformed declarations while preserving independently checked configs.
    config(tmp_path, 'sample')
    config(tmp_path, 'other')
    cases = [
        (None, 'not_supplied', ('not_supplied', 'not_supplied')),
        (tmp_path / 'absent.json', 'missing', ('unavailable', 'unavailable')),
        (tmp_path, 'unreadable', ('unavailable', 'unavailable')),
        (bindings(tmp_path, []), 'malformed', ('unavailable', 'unavailable')),
    ]
    for path, status, expected in cases:
        assert readiness.main(cli(tmp_path, 'zone', 'sample', 'other', binding=path)) == 1
        report = json.loads(capsys.readouterr().out)
        assert report['binding_file'] == status
        assert tuple(row['binding_row'] for row in report['regions']) == expected
        assert all('missing_declaration:coarse' in row['issues'] for row in report['regions'])
    path = bindings(tmp_path, {'sample': None, 'other': {'coarse': True, 'water': 'bad\0path', 'coarse-source': []}})
    assert readiness.main(cli(tmp_path, 'zone', 'sample', 'other', binding=path)) == 1
    bad_row, bad_fields = json.loads(capsys.readouterr().out)['regions']
    assert 'binding_row_malformed' in bad_row['issues']
    assert bad_fields['issues'] == ['malformed_declaration:coarse', 'malformed_declaration:water',
                                    'malformed_declaration:coarse-source']
