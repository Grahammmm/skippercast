"""Offline regressions at the repository contour publication boundary."""
from copy import deepcopy
from dataclasses import dataclass
import json
from pathlib import Path

import pytest

from skippercast import style
from skippercast.platform import depth_contours as dc
from skippercast.platform.contracts import OWNER_DISPLAY_BASIS, read_json
from tests._support import ROOT

STATIC = ('static-a', 'static-b', 'static-c', 'static-d')
SELECTED = ('blue-grid', 'native-grid', 'topobathy-grid')
OWNER = {'decision': 'allowed', 'basis': OWNER_DISPLAY_BASIS}
NAMES = ('depth-contours.geojson', 'depth-contours-overview.geojson')


def _pointer(region_id, ids):
    return {'schema': 'sc-relief-pointer/1', 'status': 'reviewed', 'private': False,
            'region': region_id, 'sources': [{'id': ident} for ident in ids]}


def _write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding='utf-8')


@dataclass
class Catalog:
    root: Path
    region: dict
    sources: dict

    @property
    def pointer_path(self):
        return self.root / 'catalog/relief/synthetic-bay.json'

    @property
    def outputs(self):
        return [self.root / 'dist' / name for name in NAMES]

    def publish(self, value):
        _write(self.root / 'catalog/depth-contours/synthetic-bay.geojson', value)
        return dc.publish_depth_contours(self.root, self.region, self.root / 'dist', self.sources)

    def collection(self, listed, selected, version=dc.FT_V2):
        features, entries = [], []
        provenance = {'region_id': self.region['id'], 'bounds': self.region['bounds'], 'units': 'ft',
                      'features': len(listed), 'shelf_limit_ft': 300}
        if version is not None:
            provenance['set'] = version
        if version == dc.FT_V3:
            view = style.load().view('contours')
            provenance['contours'] = view.digest('contours')
            tier, stop = next(dc.v3_tiers(view, 2, certified=False))
            depth, index = next(iter(dc.v3_levels(tier).items()))
            contour = {'depth_ft': depth, 'index': index, 'estimated': True, 'native_cell_m': 2,
                       'tier': tier['name'], 'minzoom': tier['min_zoom']}
            if stop is not None:
                contour['maxzoom'] = stop
        elif version == dc.FT_V2:
            provenance.update(intervals=dc.v2_intervals(), index_depths_ft=list(dc.V2_INDEX_FT))
            contour = {'depth_ft': 60, 'index': True, 'estimated': True, 'minzoom': 8}
        else:
            provenance.update(interval_ft=30, shelf_limit_ft=600)
            contour = {'depth_ft': 30, 'index': False}
        for ident in listed:
            labels = {'source_id': ident, 'survey_date': dc.selected_survey_date(self.sources[ident]),
                      'vertical_datum': dc.UNVERIFIED_DATUM}
            entries.append({**labels, 'sha256': 'a' * 64, 'native_cell_m': 2})
            features.append({'id': f'{ident}-line', 'type': 'Feature',
                             'properties': {**labels, **contour, 'kind': 'contour'},
                             'geometry': {'type': 'LineString', 'coordinates': [[0.1, 0.1], [0.2, 0.2]]}})
        provenance.update(sources=entries, sources_omitted=dc.omitted_selected_sources(selected, self.sources, listed))
        return {'type': 'FeatureCollection', 'provenance': provenance, 'features': features}

    def assert_pair(self, value):
        assert self.publish(value) == tuple(f'regions/synthetic-bay/{name}' for name in NAMES)
        for path in self.outputs:
            provenance = read_json(path)['provenance']
            assert provenance['sources_omitted'] == value['provenance']['sources_omitted']
            stamps = ['review_expires', 'review_days', 'sources_omitted']
            assert [key for key in provenance if key in stamps] == stamps
            assert provenance['review_expires'] == '2027-01-02'
            assert provenance['review_days'] == 365


@pytest.fixture
def catalog(tmp_path):
    region = {'id': 'synthetic-bay', 'bounds': [0, 0, 1, 1], 'source_bindings': {'bathymetry': list(STATIC)}}
    sources = {ident: {'needs': ['bathymetry'], 'reviewed_at': '2026-01-02',
                       'review_status': 'approved', 'rights': {'public_display': 'allowed'}, 'survey_year': 2010}
               for ident in STATIC}
    for i, ident in enumerate(SELECTED):
        sources[ident] = {'needs': ['bathymetry'], 'reviewed_at': '2026-01-02', 'review_status': 'candidate',
                          'rights': {'public_display': 'allowed', 'owner_public_display': deepcopy(OWNER)}}
        if i:
            sources[ident]['publication_allowed'] = False
    return Catalog(tmp_path, region, sources)


@pytest.mark.parametrize(('ground', 'message'), [
    ('binding', 'not an approved bathymetry binding'),
    ('candidate', 'not an approved bathymetry binding'),
    ('undated', 'lacks its grid hash, survey date or datum'),
    ('denied', 'not cleared for public display'),
    ('omitted-form', 'misstate the omitted bound surveys'),
])
def test_isolated_strict_refusals_publish_via_reviewed_pointer(catalog, ground, message):
    # Reproduce each static refusal by itself; changing just the pointer must admit the same bytes.
    ident = STATIC[0]
    catalog.sources[ident]['rights']['owner_public_display'] = OWNER
    dc.check_contours(catalog.collection([ident], STATIC), catalog.region, catalog.sources)
    selected = STATIC
    if ground == 'binding':
        catalog.region['source_bindings']['bathymetry'].remove(ident)
    elif ground == 'candidate':
        catalog.sources[ident]['review_status'] = 'candidate'
    elif ground == 'undated':
        catalog.sources[ident].pop('survey_year')
    elif ground == 'denied':
        catalog.sources[ident]['publication_allowed'] = False
    else:
        selected = (ident, *SELECTED)
    value = catalog.collection([ident], selected)
    with pytest.raises(ValueError, match=message):
        catalog.publish(value)
    _write(catalog.pointer_path, _pointer(catalog.region['id'], selected))
    catalog.assert_pair(value)


@pytest.mark.parametrize('marker', [
    'absent', 'other-region', 'unreviewed', 'private', 'malformed-json', 'in-file',
    'wrong-schema', 'sources-not-list', 'private-zero', 'private-missing', 'non-object', 'unreadable',
])
def test_only_external_reviewed_region_pointer_can_enable_selected_mode(catalog, marker):
    # Fail closed to the *strict* validator, not a fallback to selected rules.
    value = catalog.collection(SELECTED[:1], SELECTED)
    pointer = _pointer(catalog.region['id'], SELECTED)
    if marker == 'in-file':
        value.update(selected=True, pointer=pointer)
        value['provenance'].update(selected=True, pointer=pointer)
    elif marker == 'unreadable':
        catalog.pointer_path.mkdir(parents=True)  # read raises OSError even under a privileged runner
    elif marker == 'malformed-json':
        catalog.pointer_path.parent.mkdir(parents=True)
        catalog.pointer_path.write_text('{', encoding='utf-8')
    elif marker != 'absent':
        change = {'other-region': {'region': 'other-bay'}, 'unreviewed': {'status': 'candidate'},
                  'private': {'private': True}, 'wrong-schema': {'schema': 'sc-relief-pointer/2'},
                  'sources-not-list': {'sources': {}}, 'private-zero': {'private': 0}}
        pointer.update(change.get(marker, {}))
        if marker == 'private-missing':
            pointer.pop('private')
        _write(catalog.pointer_path, [] if marker == 'non-object' else pointer)
    with pytest.raises(ValueError, match='blue-grid is not an approved bathymetry binding of synthetic-bay'):
        catalog.publish(value)


@pytest.mark.parametrize(('case', 'message'), [
    ('listed-not-released', 'blue-grid'), ('omitted-not-released', 'native-grid'),
    ('omitted-not-in-catalog', 'native-grid'), ('non-bathymetry', 'native-grid'),
    ('clearance-removed', 'native-grid'), ('not-public', 'native-grid'),
    ('bad-rights', 'native-grid'), ('bad-needs', 'native-grid'), ('missing-omissions', 'sources_omitted'),
    ('null-omissions', 'sources_omitted'), ('bad-omission-row', 'sources_omitted'),
    ('bad-omission-id', 'source ID'), ('bad-listed-row', 'must state sources'),
    ('bad-feature-source', 'Malformed depth contour import'),
    ('wrong-region', 'not its FeatureCollection'), ('outside-bounds', 'not a line inside'),
])
def test_selected_release_tie_refuses_bad_ids_and_keeps_spatial_checks(catalog, case, message):
    # Omitted IDs carry no geometry, so the producer's geometry checks cannot enforce this tie.
    value = catalog.collection(SELECTED[:1], SELECTED)
    p = value['provenance']
    pointer = _pointer(catalog.region['id'], SELECTED)
    source = catalog.sources['native-grid']
    if case == 'listed-not-released':
        pointer['sources'][0] = {'id': ['blue-grid']}
    elif case == 'omitted-not-released':
        pointer['sources'].pop(1)
    elif case == 'omitted-not-in-catalog':
        catalog.sources.pop('native-grid')
    elif case == 'non-bathymetry':
        source['needs'] = ['weather']
    elif case == 'clearance-removed':
        source['rights'].pop('owner_public_display')
    elif case == 'not-public':
        source['rights']['public_display'] = 'private'
    elif case == 'bad-rights':
        source['rights'] = []
    elif case == 'bad-needs':
        source['needs'] = None
    elif case == 'missing-omissions':
        p.pop('sources_omitted')
    elif case == 'null-omissions':
        p['sources_omitted'] = None
    elif case == 'bad-omission-row':
        p['sources_omitted'] = ['native-grid']
    elif case == 'bad-omission-id':
        p['sources_omitted'][0]['source_id'] = {}
    elif case == 'bad-listed-row':
        p['sources'] = [None]
    elif case == 'bad-feature-source':
        value['features'][0]['properties']['source_id'] = ['blue-grid']
    elif case == 'wrong-region':
        p['region_id'] = 'other-bay'
    elif case == 'outside-bounds':
        value['features'][0]['geometry']['coordinates'][0][0] = -1
    _write(catalog.pointer_path, pointer)
    with pytest.raises(ValueError, match=message) as error:
        catalog.publish(value)
    assert 'synthetic-bay' in str(error.value)
    assert not any(path.exists() for path in catalog.outputs)


@pytest.mark.parametrize('version', [dc.FT_V2, dc.FT_V3])
@pytest.mark.parametrize('listed', [SELECTED, SELECTED[:1]], ids=['all-listed', 'partly-omitted'])
def test_producer_valid_collections_publish(catalog, version, listed):
    # Candidate, undated and owner-cleared families are accepted together, with or without omissions.
    value = catalog.collection(listed, SELECTED, version)
    dc.check_selected_contours(value, catalog.region, catalog.sources, set(SELECTED))
    pointer = _pointer(catalog.region['id'], (*SELECTED, STATIC[0]))
    assert dc.check_catalog_contours(value, catalog.region, catalog.sources, pointer) == set(SELECTED)
    _write(catalog.pointer_path, pointer)
    catalog.assert_pair(value)
    assert read_json(catalog.outputs[0])['features'][0]['properties']['survey_date'] == 'unstated'


def test_hold_wins_before_selected_shape_or_release_refusal(catalog):
    # Do not let a malformed selected omission list suppress hold-triggered cleanup.
    value = catalog.collection(SELECTED[:1], SELECTED)
    _write(catalog.pointer_path, _pointer(catalog.region['id'], SELECTED))
    catalog.assert_pair(value)
    value['provenance'].pop('sources_omitted')
    value['features'][0]['properties']['publication_held'] = True
    with pytest.raises(dc._ContoursHeld, match='synthetic-bay are held'):
        catalog.publish(value)
    assert not any(path.exists() for path in catalog.outputs)


@pytest.mark.parametrize('malformed', [None, 'invalid', {'properties': 'invalid'}])
@pytest.mark.parametrize('hold_at', ['feature', 'properties'])
def test_hold_wins_over_malformed_feature_and_withdraws_pair(catalog, malformed, hold_at):
    value = catalog.collection(SELECTED[:1], SELECTED)
    _write(catalog.pointer_path, _pointer(catalog.region['id'], SELECTED))
    catalog.assert_pair(value)
    held = value['features'][0]
    (held if hold_at == 'feature' else held['properties'])['publication_held'] = True
    value['features'].insert(0, malformed)
    with pytest.raises(dc._ContoursHeld, match='synthetic-bay are held'):
        catalog.publish(value)
    assert not any(path.exists() for path in catalog.outputs)


@pytest.mark.parametrize('withdrawal', [None, 'clearance', 'release', 'omitted', 'static-incoming', 'no-pointer'])
def test_refusal_checks_previous_pair_under_the_current_mode(catalog, monkeypatch, withdrawal):
    # An unrelated refusal must preserve eligible candidate bytes, not reinterpret them as static.
    # Conversely the prior generation, not the incoming set, determines what is withdrawn.
    pointer = _pointer(catalog.region['id'], SELECTED)
    _write(catalog.pointer_path, pointer)
    catalog.assert_pair(catalog.collection(SELECTED[:2], SELECTED, dc.FT_V3))
    previous = [path.read_bytes() for path in catalog.outputs]
    incoming = catalog.collection(SELECTED[:1], SELECTED[:1])
    if withdrawal == 'clearance':
        catalog.sources['native-grid']['rights'].pop('owner_public_display')
    elif withdrawal in ('release', 'omitted'):
        pointer['sources'].pop(1 if withdrawal == 'release' else 2)
        _write(catalog.pointer_path, pointer)
    elif withdrawal == 'static-incoming':
        incoming = catalog.collection(STATIC[:1], STATIC, None)
    elif withdrawal == 'no-pointer':
        _write(catalog.pointer_path, None)
    monkeypatch.setattr(dc, 'V2_MAX_BYTES', 1)
    monkeypatch.setattr(dc, 'MAX_BYTES', 1)
    message = 'not an approved bathymetry binding' if withdrawal == 'no-pointer' else 'over its 1-byte budget'
    with pytest.raises(ValueError, match=message):
        catalog.publish(incoming)
    if withdrawal is None:
        assert [path.read_bytes() for path in catalog.outputs] == previous
    else:
        assert not any(path.exists() for path in catalog.outputs)


def test_legacy_without_a_set_is_strict_even_with_a_pointer(catalog):
    # A valid pointer must not switch the legacy version to selected mode.
    _write(catalog.pointer_path, _pointer(catalog.region['id'], SELECTED))
    with pytest.raises(ValueError, match='not an approved bathymetry binding'):
        catalog.publish(catalog.collection(SELECTED[:1], SELECTED, None))


@pytest.mark.parametrize('with_pointer', [False, True])
def test_morro_legacy_republish_matches_committed_pair(tmp_path, with_pointer):
    # Protect both committed byte streams, including ordering of the static publication stamps.
    region = read_json(ROOT / 'regions/morro-bay/region.json')
    sources = {row['id']: row for row in read_json(ROOT / 'catalog/sources.json')['sources']}
    root = ROOT
    if with_pointer:
        root = tmp_path
        relative = 'catalog/depth-contours/morro-bay.geojson'
        (root / relative).parent.mkdir(parents=True)
        (root / relative).write_bytes((ROOT / relative).read_bytes())
        _write(root / 'catalog/relief/morro-bay.json', _pointer('morro-bay', SELECTED))
    output = tmp_path / 'output'
    assert dc.publish_depth_contours(root, region, output, sources) == tuple(f'regions/morro-bay/{name}' for name in NAMES)
    for name in NAMES:
        assert (output / name).read_bytes() == (ROOT / 'dist/regions/morro-bay' / name).read_bytes()
