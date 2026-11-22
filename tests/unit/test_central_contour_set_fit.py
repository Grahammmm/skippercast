"""Exercise the attended pickup boundary with synthetic, shipping-encoded GeoJSON."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import pytest

from scripts.relief import central_contour_set_fit as fit
from skippercast import style
from skippercast.platform import depth_contours as dc
from skippercast.platform.contracts import atomic_json
from skippercast.relief import envelope, package


CLI = Path(fit.__file__).resolve()
SOURCE = 'synthetic-grid'
FULL_CAP, OVERVIEW_CAP = 3_000_000, 300_000


def _write(root, name, value):
    serialized = atomic_json(root / name, value)
    return {'path': name, 'sha256': serialized['sha256']}


def _pair(region, version, *, y=0.2, sizes=None):
    common = {'source_id': SOURCE, 'vertical_datum': 'MLLW', 'survey_date': '2020'}
    provenance = {'set': version, 'region_id': region['id'], 'bounds': region['bounds'],
                  'features': 2, 'shelf_limit_ft': 300, 'units': 'ft', 'sources_omitted': [],
                  'sources': [{**common, 'sha256': '1' * 64, 'native_cell_m': 2}]}
    if version == dc.FT_V2:
        provenance.update(intervals=dc.v2_intervals(), index_depths_ft=list(dc.V2_INDEX_FT))
        zooms = [{'depth_ft': 60, 'minzoom': 8, 'index': True},
                 {'depth_ft': 60, 'minzoom': 14, 'index': True}]
    else:
        view = style.load('nearshore-v1.0.0').view('contours')
        provenance['contours'] = view.digest('contours')
        tiers = list(dc.v3_tiers(view, 2, certified=False))
        zooms = []
        for tier, stop in (tiers[0], tiers[-1]):
            depth, index = next(iter(dc.v3_levels(tier).items()))
            zooms.append({'tier': tier['name'], 'minzoom': tier['min_zoom'], 'depth_ft': depth,
                          'index': index, **({'maxzoom': stop} if stop is not None else {})})
    features = [
        {'type': 'Feature', 'id': name, 'geometry': {'type': 'LineString', 'coordinates': [[0.1, y], [0.6, y]]},
         'properties': {**common, **zoom, 'kind': 'contour', 'estimated': True, 'native_cell_m': 2, 'pad': ''}}
        for name, zoom in zip(('shelf', 'detail'), zooms)
    ]
    full = {'type': 'FeatureCollection', 'features': features, 'provenance': provenance}
    if sizes:
        # The writer uses compact UTF-8 with final LF. Pad a property with Unicode
        # so a text-character count cannot substitute for the delivered byte count.
        for feature, doc, cap in ((features[0], dc.overview_contours(full), sizes[1]),
                                  (features[1], full, sizes[0])):
            encoded_size = len(json.dumps(doc, ensure_ascii=False, separators=(',', ':')).encode()) + 1
            count, extra = divmod(cap - encoded_size, 2)
            feature['properties']['pad'] = 'é' * count + 'x' * extra
    return full, dc.overview_contours(full)


def _candidate(root, name, pair):
    return {'id': name, **{role: _write(root, f'{name}/{role}.geojson', doc)
                          for role, doc in zip(('full', 'overview'), pair)}}


@pytest.fixture
def inputs(tmp_path):
    region = {'id': 'synthetic-central', 'bounds': [0, 0, 1, 1], 'source_bindings': {'bathymetry': []}}
    sources = {SOURCE: {'id': SOURCE, 'needs': ['bathymetry'], 'review_status': 'approved',
                        'rights': {'public_display': 'allowed', 'license': 'public-domain'}}}
    pointer = {'schema': 'sc-relief-pointer/1', 'status': 'reviewed', 'private': False,
               'region': region['id'], 'sources': [{'id': SOURCE}]}
    _write(tmp_path, 'region.json', region)
    _write(tmp_path, 'catalog/sources.json', {'sources': list(sources.values())})
    _write(tmp_path, 'pointer.json', pointer)
    argv = ['--scratch', str(tmp_path.resolve()), '--region', 'region.json', '--catalog', 'catalog/sources.json',
            '--pointer', 'pointer.json', '--manifest', 'manifest.json']
    return region, sources, pointer, argv


def _run(argv, *args):
    result = subprocess.run([sys.executable, '-B', str(CLI), *argv, *args], capture_output=True, text=True, check=False)
    assert not result.stderr, result.stderr
    return result.returncode, json.loads(result.stdout)


def _hashes(candidate):
    return {role: candidate[role]['sha256'] for role in ('full', 'overview')}


@pytest.mark.parametrize('version', [dc.FT_V2, dc.FT_V3])
def test_exact_limits_and_attended_pick(tmp_path, inputs, version):
    # Catches a legacy or exclusive cap, missing UTF-8/newline bytes, automatic
    # selection and choosing the first passing pair instead of the named one.
    region, _, _, argv = inputs
    small = _candidate(tmp_path, 'small', _pair(region, version))
    exact = _candidate(tmp_path, 'exact', _pair(region, version, sizes=(FULL_CAP, OVERVIEW_CAP)))
    _write(tmp_path, 'manifest.json', {'candidates': [small, exact]})
    status, report = _run(argv)
    assert status == 0 and 'pickup' not in report and 'sha256' not in json.dumps(report)
    assert [row['fits'] for row in report['candidates']] == [True, True]
    files = report['candidates'][1]['files']
    for role, cap in [('full', FULL_CAP), ('overview', OVERVIEW_CAP)]:
        assert files[role] == dict(bytes=cap, cap_bytes=cap, within_cap=True, binding='external-pin-not-R8-proven')
    assert _run(argv, '--pick', 'exact') == (0, report | {'pickup': {
        'candidate': 'exact', 'sha256': _hashes(exact), 'binding': 'external-pin-not-R8-proven'}})


@pytest.mark.parametrize('over', ['full', 'overview'])
def test_one_more_byte_refuses_only_that_role(tmp_path, inputs, over):
    # Catches skipped/swapped budgets or repairing a failing pair with another
    # candidate's passing file. Both files are generated at exact target sizes.
    region, _, _, argv = inputs
    candidate = _candidate(tmp_path, 'oversize', _pair(
        region, dc.FT_V2, sizes=(FULL_CAP + (over == 'full'), OVERVIEW_CAP + (over == 'overview'))))
    other = _candidate(tmp_path, 'passing', _pair(region, dc.FT_V2))
    _write(tmp_path, 'manifest.json', {'candidates': [candidate, other]})
    status, report = _run(argv, '--pick', 'oversize')
    assert status == 1 and 'pickup' not in report and report['candidates'][1]['fits']
    row = report['candidates'][0]
    assert not row['fits'] and set(row['errors']) == {over}
    for role, cap in [('full', FULL_CAP), ('overview', OVERVIEW_CAP)]:
        assert row['files'][role]['bytes'] == cap + (role == over)
        assert row['files'][role]['within_cap'] is (role != over)


def test_valid_alternate_overview_cannot_replace_accepted_bytes(tmp_path, inputs):
    # Same shape and provenance, different valid geometry. Catches a digest
    # check against the full file only, or adopting the overview's observed hash.
    region, sources, pointer, argv = inputs
    original = _candidate(tmp_path, 'original', _pair(region, dc.FT_V2))
    alternate_pair = _pair(region, dc.FT_V2, y=0.3)
    assert dc.check_catalog_contours(alternate_pair[1], region, sources, pointer) == {SOURCE}
    alternate = _candidate(tmp_path, 'alternate', alternate_pair)
    assert alternate['overview']['sha256'] != original['overview']['sha256']
    original['overview']['path'] = alternate['overview']['path']
    _write(tmp_path, 'manifest.json', {'candidates': [original, alternate]})
    status, report = _run(argv, '--pick', 'original')
    assert status == 1 and 'pickup' not in report and report['candidates'][1]['fits']
    assert report['candidates'][0]['errors'] == {'overview': 'accepted SHA-256 mismatch'}


def test_valid_pins_do_not_bypass_the_real_catalog_validator(tmp_path, inputs):
    # A hash-only or full-only validator would accept wrong contour zoom in a
    # pinned overview. Keep the full file valid so the right check decides.
    region, _, _, argv = inputs
    full, overview = _pair(region, dc.FT_V2)
    # Projection shares properties with the full; replace this copy only.
    feature = overview['features'][0]
    overview['features'][0] = {**feature, 'properties': {**feature['properties'], 'minzoom': 10}}
    candidate = _candidate(tmp_path, 'bad-zoom', (full, overview))
    _write(tmp_path, 'manifest.json', {'candidates': [candidate]})
    status, report = _run(argv, '--pick', 'bad-zoom')
    assert status == 1 and 'pickup' not in report
    assert 'invalid ft-v2 depth, index or zoom' in report['candidates'][0]['errors']['overview']


def test_individually_valid_but_different_sets_cannot_form_a_pair(tmp_path, inputs):
    # A per-file-only verdict would allow pinning a v3 overview alongside a
    # v2 full artifact even though their tier contracts are incompatible.
    region, _, _, argv = inputs
    full, _ = _pair(region, dc.FT_V2)
    _, overview = _pair(region, dc.FT_V3)
    mixed = _candidate(tmp_path, 'mixed-sets', (full, overview))
    _write(tmp_path, 'manifest.json', {'candidates': [mixed]})
    status, report = _run(argv, '--pick', 'mixed-sets')
    assert status == 1 and 'pickup' not in report
    assert set(report['candidates'][0]['errors']) == {'pair'}


@pytest.mark.parametrize('symlink', [False, True])
def test_unenveloped_file_must_be_scratch_local_and_pinned(tmp_path, inputs, symlink):
    # A valid GeoJSON file is not accepted just because its bytes are readable:
    # catch unpinned admission and symlink traversal despite a correct hash.
    region, _, _, argv = inputs
    candidate = _candidate(tmp_path, 'unsafe', _pair(region, dc.FT_V2))
    if symlink:
        (tmp_path / 'linked.geojson').symlink_to(tmp_path / candidate['overview']['path'])
        candidate['overview']['path'] = 'linked.geojson'
    else:
        candidate['overview'].pop('sha256')
    _write(tmp_path, 'manifest.json', {'candidates': [candidate]})
    status, report = _run(argv, '--pick', 'unsafe')
    assert status == 1 and 'pickup' not in report
    assert ('symlink' if symlink else 'needs an accepted SHA-256') in report['candidates'][0]['errors']['overview']


def test_generation_inventory_does_not_bind_external_overview(tmp_path, inputs, monkeypatch, capsys):
    # Future mixed inventory control: catch ignoring a bound file, bypassing a
    # changed package with an external pin, or extending envelope proof to an
    # unlisted overview. The envelope verifier is real; only its catalog root
    # is redirected to the explicit synthetic catalog used by this test.
    region, _, _, argv = inputs
    monkeypatch.setattr(envelope, 'repo_root', lambda: tmp_path)
    region_dir = tmp_path / region['id']
    full, overview = _pair(region, dc.FT_V2)
    bound_path = 'layers/public/contours.geojson'
    bound = _write(region_dir, bound_path, full)
    for layer in (package.ARCHIVE, package.DIGEST_ROOT):
        path = region_dir / layer
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'synthetic layer')
    layers = [package.layer_record(region_dir, name) for name in sorted((package.ARCHIVE, package.DIGEST_ROOT, bound_path))]
    generation = 'a' * 64
    release = _write(region_dir, f'release/{generation}/release.json', {
        'schema': package.RELEASE_SCHEMA, 'region': region['id'], 'generation': generation,
        'code_sha': 'c' * 40, 'private': False, 'disclaimer': package.DISCLAIMER,
        'bounds': region['bounds'], 'minzoom': 8, 'maxzoom': 8, 'layers': layers,
        'digest_root_sha256': next(row['sha256'] for row in layers if row['path'] == package.DIGEST_ROOT),
        'sources': [{'id': SOURCE, 'attribution': 'Synthetic survey', 'rights_class': 'public',
                     'label': 'estimated', 'vertical_datum': 'MLLW', 'survey_dates': ['2020'],
                     'rights': {'public_display': 'allowed', 'license': 'public-domain'}}],
        'detail_summary': {'mask': 'transparent-nodata', 'depth_bands': [
            {'source_id': SOURCE, 'min_depth_m': 0, 'max_depth_m': 20, 'resolution_m': 2, 'support_class': 2}]},
        'native_support_by_zoom': {'8': {'tiles': 1, 'limit_m': 91.44, 'sources': []}},
    })
    qa = _write(region_dir, f'qa/{generation}/qa.json', {'status': 'PASS', 'release_sha256': release['sha256']})
    env = _write(region_dir, f'review/{generation}/envelope.json', {
        'schema': envelope.ENVELOPE_SCHEMA, 'region': region['id'], 'generation': generation,
        'release': release, 'qa': qa, 'layers': layers,
    })
    env['path'] = f"{region['id']}/{env['path']}"
    candidate = {'id': 'mixed', 'full': {'path': f"{region['id']}/{bound_path}"},
                 'overview': _write(tmp_path, 'external.geojson', overview)}
    manifest = {'candidates': [candidate], 'envelope': env}
    _write(tmp_path, 'manifest.json', manifest)
    selection = [*argv, '--pick', 'mixed']
    assert fit.main(selection) == 0
    report = json.loads(capsys.readouterr().out)
    assert report['generation'] == generation
    assert report['candidates'][0]['files']['full']['binding'] == 'generation-bound'
    assert report['pickup'] == {'candidate': 'mixed', 'binding': 'external-pin-not-R8-proven',
                                'sha256': {'full': bound['sha256'], 'overview': candidate['overview']['sha256']}}

    changed = (region_dir / bound_path).read_bytes() + b' '
    (region_dir / bound_path).write_bytes(changed)
    candidate['full']['sha256'] = hashlib.sha256(changed).hexdigest()
    _write(tmp_path, 'manifest.json', manifest)
    with pytest.raises(SystemExit) as error:
        fit.main(selection)
    output = capsys.readouterr()
    assert error.value.code == 2 and not output.out and 'layer hash or size changed' in output.err
