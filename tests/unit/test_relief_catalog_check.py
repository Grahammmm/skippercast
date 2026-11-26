"""Runtime acceptance for the read-only catalog pairing check."""
import json
from pathlib import Path
import shutil

import pytest

from skippercast.relief.catalog_check import check_catalog, main
from tests._support import ROOT

RELIEF = Path('catalog/relief')
POINTER = RELIEF / 'test-bay.json'
CONTOURS = Path('catalog/depth-contours/test-bay.geojson')
INDEX = Path('dist/regions/index.json')
CHECKS = ('schema', 'filename', 'release-region', 'contours', 'lineage')
NOT_LISTED = 'pointer region not listed in dist/regions/index.json'
WRONG_CONTOURS = 'contours provenance.region_id does not match pointer region'
BAD_LINEAGE = 'previous must be null or match the pointer lineage schema'
PREVIOUS = dict(generation='1' * 64, release_sha256='2' * 64, envelope_sha256='3' * 64, sha256='4' * 64)


def write_json(path, doc):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc), encoding='utf-8')


def pointer(previous=None):
    return {
        'schema': 'sc-relief-pointer/1', 'status': 'reviewed', 'private': False,
        'region': 'test-bay', 'generation': 'a' * 64, 'release_sha256': 'b' * 64,
        'envelope_sha256': 'c' * 64, 'sha256': 'd' * 64, 'bytes': 128,
        'digest_root_sha256': 'e' * 64, 'previous': previous,
        'bounds': [-122, 36, -121, 37], 'minzoom': 8, 'maxzoom': 8,
        'sources': [{'id': 'fixture', 'label': 'Fixture', 'attribution': 'Fixture',
                     'vertical_datum': 'Fixture datum', 'survey_dates': ['2020'], 'rights_class': 'public',
                     'rights': {'public_display': 'allowed', 'license': 'Fixture license'}}],
        'detail_summary': {'mask': 'transparent-nodata', 'depth_bands': [
            {'source_id': 'fixture', 'min_depth_m': 0, 'max_depth_m': 20, 'resolution_m': 2}]},
        'native_support_by_zoom': {'8': {'tiles': 1, 'sources': []}},
    }


def contours(region):
    return {'type': 'FeatureCollection', 'features': [], 'provenance': {'schema_version': 1, 'region_id': region}}


@pytest.fixture
def tree(tmp_path):
    (tmp_path / RELIEF).mkdir(parents=True)
    schema = RELIEF / 'pointer.schema.json'
    shutil.copyfile(ROOT / schema, tmp_path / schema)
    write_json(tmp_path / INDEX, {'regions': [{'id': 'test-bay'}, {'id': 'other-bay'}]})
    return tmp_path


@pytest.fixture
def pair(tree):
    write_json(tree / POINTER, pointer())
    write_json(tree / CONTOURS, contours('test-bay'))
    return tree


def expected(region='test-bay', **failures):
    return [{'region': region, 'check': check, 'status': 'FAIL' if check in failures else 'PASS',
             'reason': failures.get(check, 'ok')} for check in CHECKS]


@pytest.mark.parametrize('previous', [None, PREVIOUS, {**PREVIOUS, 'style': {
    'baked': 'f' * 64, 'contours': None, 'habitat': None, 'built_with': 'fixture-v1',
}}], ids=['C1: null lineage', 'C1: complete lineage', 'C1: optional valid lineage style'])
def test_c1_good_pair(pair, previous):
    """C1: Accept both first-release and replacement pointers."""
    write_json(pair / POINTER, pointer(previous))
    assert check_catalog(str(pair)) == expected()


def test_c1_missing_contours_and_multiple_pointers(pair):
    """C1: Visit every pointer, even if it sorts before the good pair and has no contours."""
    write_json(pair / RELIEF / 'other-bay.json', {**pointer(), 'region': 'other-bay'})
    assert check_catalog(pair) == (
        expected('other-bay', contours='missing catalog/depth-contours/other-bay.geojson') + expected()
    )


def test_c1_filename_region_mismatch(pair):
    """C1: A listed region with its own contours cannot be filed under a different id."""
    write_json(pair / POINTER, {**pointer(), 'region': 'other-bay'})
    write_json(pair / 'catalog/depth-contours/other-bay.geojson', contours('other-bay'))
    assert check_catalog(pair) == expected(
        filename='filename id does not match pointer region', contours=WRONG_CONTOURS,
    )


@pytest.mark.parametrize('content, reason', [
    (json.dumps(contours('other-bay')), WRONG_CONTOURS),
    (json.dumps({'type': 'FeatureCollection', 'features': []}), WRONG_CONTOURS),
    ('{', 'cannot read contours object for test-bay'),
], ids=['C1: wrong provenance', 'C1: absent provenance', 'C1: corrupt contours'])
def test_c1_contours_refusals(pair, content, reason):
    """C1: An existing contours path is not enough without readable matching provenance."""
    (pair / CONTOURS).write_text(content, encoding='utf-8')
    assert check_catalog(pair) == expected(contours=reason)


@pytest.mark.parametrize('index', [{'regions': [{'id': 'other-bay'}]}, {'regions': None}],
                         ids=['C1: unlisted region', 'C1: unusable index'])
def test_c1_release_region_refusal(pair, index):
    """C1: Admit a region only through the release index, not through paired files alone."""
    write_json(pair / INDEX, index)
    assert check_catalog(pair) == expected(**{'release-region': NOT_LISTED})


def test_c1_schema_refusal_with_valid_lineage(pair):
    """C1: Report bad pointer schema without masking independent successful checks."""
    write_json(pair / POINTER, {**pointer(PREVIOUS), 'status': 'draft'})
    assert check_catalog(pair) == expected(schema="invalid relief metadata at status: 'reviewed' was expected")


def test_c1_unreadable_pointer(pair):
    """C1: A corrupt pointer must be reported, not skipped as if absent."""
    (pair / POINTER).write_text('{', encoding='utf-8')
    assert check_catalog(pair) == expected(**{
        'schema': 'cannot read pointer JSON object', 'filename': 'filename id does not match pointer region',
        'release-region': NOT_LISTED, 'contours': WRONG_CONTOURS, 'lineage': BAD_LINEAGE,
    })


@pytest.mark.parametrize('field', PREVIOUS, ids=lambda field: f'C1: lineage {field}')
@pytest.mark.parametrize('bad_value', [None, 'A' * 64, '1' * 63],
                         ids=['C1: missing field', 'C1: invalid hash case', 'C1: invalid hash length'])
def test_c1_bad_lineage(pair, field, bad_value):
    """C1: No lineage field can be omitted or use a hash outside the schema format."""
    previous = dict(PREVIOUS)
    if bad_value is None:
        del previous[field]
    else:
        previous[field] = bad_value
    assert_bad_lineage(pair, previous)


@pytest.mark.parametrize('previous', [[], {**PREVIOUS, 'extra': True}, {**PREVIOUS, 'style': {
    'baked': 'f' * 64, 'contours': None, 'habitat': None, 'built_with': 'Not a version',
}}], ids=['C1: wrong lineage type', 'C1: unknown lineage key', 'C1: invalid lineage style'])
def test_c1_bad_lineage_shape(pair, previous):
    """C1: Checking only the four hashes would miss the rest of the lineage schema."""
    assert_bad_lineage(pair, previous)


def assert_bad_lineage(pair, previous):
    write_json(pair / POINTER, pointer(previous))
    assert check_catalog(pair) == expected(
        schema=f'invalid relief metadata at previous: {previous!r} is not valid under any of the given schemas',
        lineage=BAD_LINEAGE,
    )


def test_c1_absent_previous_not_null(pair):
    """C1: Omitting previous is different from an explicit first-release null."""
    doc = pointer()
    del doc['previous']
    write_json(pair / POINTER, doc)
    assert check_catalog(pair) == expected(
        schema="invalid relief metadata at document: 'previous' is a required property", lineage=BAD_LINEAGE,
    )


def test_c1_v1_contours_only(tree):
    """C1: A legacy contours-only region does not generate failures or stray rows."""
    write_json(tree / CONTOURS, contours('test-bay'))
    assert check_catalog(tree) == []


def test_c2_text_success_and_read_only(pair, capsys):
    """C2: The default text output includes every check without touching the checkout."""
    def snapshot():
        return {path.relative_to(pair): (path.stat().st_mtime_ns, path.read_bytes()) if path.is_file() else None
                for path in pair.rglob('*')}

    before = snapshot()
    assert main(['--root', str(pair)]) == 0
    assert capsys.readouterr() == (''.join(f'test-bay {check} PASS: ok\n' for check in CHECKS) + 'CATALOG OK\n', '')
    assert snapshot() == before


def test_c2_json_failure(tree, capsys):
    """C2: JSON stays machine-readable and the summary counts failed checks, not pointers."""
    write_json(tree / POINTER, {**pointer(), 'region': 'unlisted-bay'})
    assert main(['--root', str(tree), '--json']) == 1
    out, err = capsys.readouterr()
    assert json.loads(out) == expected(**{
        'filename': 'filename id does not match pointer region', 'release-region': NOT_LISTED,
        'contours': 'missing catalog/depth-contours/test-bay.geojson',
    })
    assert err == 'CATALOG FAIL 3\n'


@pytest.mark.parametrize('argv', [['--root'], ['--unknown'], ['--root', 'absent']],
                         ids=['C2: missing root argument', 'C2: unknown option', 'C2: not a checkout'])
def test_c2_usage_error(argv, tree, monkeypatch, capsys):
    """C2: Bad invocations are usage errors, not a successful empty catalog."""
    monkeypatch.chdir(tree)
    with pytest.raises(SystemExit) as exc:
        main(argv)
    assert type(exc.value) is SystemExit
    assert exc.value.code == 2
    out, err = capsys.readouterr()
    assert out == ''
    assert err.startswith('usage:')


def test_c3_current_repository(capsys, monkeypatch):
    """C3: The real checkout has no pointer before Morro v2, or one valid Morro pointer."""
    morro_pointer = ROOT / RELIEF / 'morro-bay.json'
    rows = expected('morro-bay') if morro_pointer.is_file() else []
    assert check_catalog(ROOT) == rows
    monkeypatch.setenv('SKIPPERCAST_ROOT', str(ROOT))
    assert main(['--json']) == 0
    assert capsys.readouterr() == (json.dumps(rows, indent=2) + '\n', 'CATALOG OK\n')
