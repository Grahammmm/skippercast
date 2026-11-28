"""Runtime acceptance for the read-only catalog pairing check."""
import json
from pathlib import Path
import shutil

import pytest

from scripts.relief.morro_stage_preview import TERRAIN_ONLY_REGIONS
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


STYLE = {'baked': 'f' * 64, 'contours': None, 'habitat': None, 'built_with': 'fixture-v1'}
MISSING = 'missing catalog/depth-contours/test-bay.geojson'
TERRAIN = frozenset({'test-bay'})


@pytest.fixture
def terrain(tree):
    """test-bay with a pointer that pins no contour style (designated terrain-only via TERRAIN in each call)."""
    write_json(tree / POINTER, {**pointer(), 'style': STYLE})
    return tree


def test_c1_terrain_only_pointer_needs_no_contours(terrain):
    """C1: A designated terrain-only region with a null contour style passes without a contour file."""
    assert check_catalog(terrain, terrain_only=TERRAIN) == expected()


@pytest.mark.parametrize('content, reason', [
    (json.dumps(contours('test-bay')), None),
    (json.dumps(contours('other-bay')), WRONG_CONTOURS),
    ('{', 'cannot read contours object for test-bay'),
], ids=['matching', 'wrong provenance', 'corrupt'])
def test_c1_terrain_only_pointer_still_checks_a_present_contour_file(terrain, content, reason):
    """C1: Only an absent file is excused; contours that are there must still match the region."""
    (terrain / CONTOURS).parent.mkdir(parents=True)
    (terrain / CONTOURS).write_text(content, encoding='utf-8')
    assert check_catalog(terrain, terrain_only=TERRAIN) == (expected(contours=reason) if reason else expected())


def test_c1_terrain_only_dangling_contour_link_is_missing(terrain):
    """C1: A contour path that is a broken link is not an absent file."""
    (terrain / CONTOURS).parent.mkdir(parents=True)
    (terrain / CONTOURS).symlink_to(terrain / 'nowhere.geojson')
    assert check_catalog(terrain, terrain_only=TERRAIN) == expected(contours=MISSING)


@pytest.mark.parametrize('style', [{**STYLE, 'contours': '9' * 64}, None, {k: v for k, v in STYLE.items()
                                                                          if k != 'contours'}],
                         ids=['contour style pinned', 'no style', 'style without contours key'])
def test_c1_designated_region_still_needs_an_explicit_null_contour_style(terrain, style):
    """C1: Designation alone is not enough: the pointer must pin style.contours null explicitly."""
    write_json(terrain / POINTER, pointer() if style is None else {**pointer(), 'style': style})
    rows = check_catalog(terrain, terrain_only=TERRAIN)
    assert [row for row in rows if row['check'] == 'contours'] == [
        {'region': 'test-bay', 'check': 'contours', 'status': 'FAIL', 'reason': MISSING}]


@pytest.mark.parametrize('designated', [(), ('other-bay',), ('test-bay-2',)],
                         ids=['none designated (default)', 'another region designated', 'similar id'])
def test_c1_null_style_alone_does_not_excuse_an_undesignated_region(terrain, designated):
    """C1: Nothing in the checked tree can make a region terrain-only; only the caller's designation can."""
    assert check_catalog(terrain, terrain_only=designated) == expected(contours=MISSING)
    if designated == ():
        assert check_catalog(terrain) == expected(contours=MISSING)


def test_c1_designation_must_be_a_collection_of_ids(terrain):
    """C1: One string would match by substring ('test-bay' in 'test-bay-x'), so it is refused."""
    with pytest.raises(TypeError):
        check_catalog(terrain, terrain_only='test-bay')


@pytest.mark.parametrize('config_kind', ['own config', 'symlink to a config outside dist', 'other region config'])
def test_c1_candidate_region_config_cannot_excuse_contours(terrain, tmp_path_factory, config_kind):
    """C1: A candidate tree whose index/region.json chart no contours for test-bay (in-tree, linked from
    outside, or another region's config) still cannot excuse the missing file without the designation."""
    config = 'regions/test-bay/region.json'
    no_contours = {'id': 'test-bay', 'chart_files': ['shoreline.geojson']}
    if config_kind == 'own config':
        write_json(terrain / 'dist' / config, no_contours)
    elif config_kind == 'symlink to a config outside dist':
        outside = tmp_path_factory.mktemp('outside') / 'region.json'
        write_json(outside, no_contours)
        (terrain / 'dist' / config).parent.mkdir(parents=True)
        (terrain / 'dist' / config).symlink_to(outside)
    else:
        config = 'regions/other-bay/region.json'
        write_json(terrain / 'dist' / config, {**no_contours, 'id': 'other-bay'})
    write_json(terrain / INDEX, {'regions': [{'id': 'test-bay', 'config': config}, {'id': 'other-bay'}]})
    assert check_catalog(terrain) == expected(contours=MISSING)
    assert check_catalog(terrain, terrain_only={'other-bay'}) == expected(contours=MISSING)


def test_c1_designation_needs_the_pointer_to_be_that_region(terrain):
    """C1: A pointer filed under a designated id but naming another region is not excused."""
    write_json(terrain / RELIEF / 'monterey-point-sur.json', {**pointer(), 'style': STYLE})
    rows = check_catalog(terrain, terrain_only={'monterey-point-sur'})
    assert rows == expected('monterey-point-sur', filename='filename id does not match pointer region',
                            contours='missing catalog/depth-contours/monterey-point-sur.geojson') + \
        expected(contours=MISSING)


@pytest.mark.parametrize('region, reason', [
    ('big-sur-coast', 'missing catalog/depth-contours/big-sur-coast.geojson'),
    ('morro-bay', 'missing catalog/depth-contours/morro-bay.geojson'),
    ('monterey-point-sur', None),
    ('santa-cruz-monterey-bay', None),
])
def test_c1_repository_designation_null_style_without_contours(tree, region, reason):
    """C1: With the stage tooling's TERRAIN_ONLY_REGIONS, a null contour style excuses a missing contour
    file only for Monterey and Santa Cruz; contour regions (Big Sur, Morro Bay) still fail."""
    shutil.copyfile(ROOT / INDEX, tree / INDEX)
    write_json(tree / RELIEF / f'{region}.json', {**pointer(), 'region': region, 'style': STYLE})
    rows = check_catalog(tree, terrain_only=TERRAIN_ONLY_REGIONS)
    assert rows == (expected(region, contours=reason) if reason else expected(region))


def test_c2_cli_terrain_only_option(terrain, capsys):
    """C2: The CLI is strict by default; --terrain-only REGION applies the same designation."""
    assert main(['--root', str(terrain), '--json']) == 1
    assert json.loads(capsys.readouterr().out) == expected(contours=MISSING)
    assert main(['--root', str(terrain), '--json', '--terrain-only', 'other-bay', '--terrain-only', 'test-bay']) == 0
    assert json.loads(capsys.readouterr().out) == expected()


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
    """C3: Every pointer in the real checkout passes all five checks: live Morro v2, then each Central region."""
    regions = sorted(path.stem for path in (ROOT / RELIEF).glob('*.json') if path.name != 'pointer.schema.json')
    assert 'morro-bay' in regions
    rows = [row for region in regions for row in expected(region)]
    assert check_catalog(ROOT, terrain_only=TERRAIN_ONLY_REGIONS) == rows
    monkeypatch.setenv('SKIPPERCAST_ROOT', str(ROOT))
    assert main(['--json', *(arg for region in TERRAIN_ONLY_REGIONS for arg in ('--terrain-only', region))]) == 0
    assert capsys.readouterr() == (json.dumps(rows, indent=2) + '\n', 'CATALOG OK\n')
