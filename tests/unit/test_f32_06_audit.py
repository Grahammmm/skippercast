"""F32-06: the emitted method must name the same denominator as the duplicate screen."""
import json

import pytest

pytestmark = pytest.mark.gis


@pytest.mark.parametrize('small_addition', [True, False], ids=['small-inside-large', 'large-around-small'])
def test_duplicate_threshold_measures_the_proposed_addition(tmp_path, small_addition):
    from shapely.geometry import box, mapping

    from research.scripts.merge_nbs_hard_research_context import merge

    def feature(name, geometry):
        return {
            'type': 'Feature', 'geometry': mapping(geometry),
            'properties': dict.fromkeys((
                'fishing_target', 'exportable', 'legal_clearance', 'fish_confirmed',
                'depth_qualified_for_target',
            ), False) | {'id': name},
        }

    small, large = box(0.2, 0.2, 0.3, 0.3), box(0, 0, 1, 1)
    proposed, existing = (small, large) if small_addition else (large, small)
    shared = {
        'type': 'FeatureCollection', 'coast_id': 'central', 'scope': 'synthetic',
        'method': 'Synthetic fixture.', 'compiled_at': '2020-01-01T00:00:00Z',
        'mpa_screened_at': '2020-01-01', 'federal_screened_at': '2020-01-01',
        'maximum_screen_uncertainty_m': 1,
    }
    layers = {
        'primary': dict(shared, sector_ids=['first'], features=[]),
        'addition': dict(shared, sector_ids=['second'], features=[feature('proposed', proposed)]),
        'native': dict(shared, scope='central-native-noaa-usgs-hard-bottom-context',
                       features=[feature('existing', existing)]),
    }
    paths = []
    for name, layer in layers.items():
        path = tmp_path / f'{name}.geojson'
        path.write_text(json.dumps(layer))
        paths.append(path)

    merged = merge(*paths)
    assert [item['properties']['id'] for item in merged['features']] == ([] if small_addition else ['proposed'])
    screen = merged['native_duplicate_screen']
    assert screen['overlap_threshold_fraction'] == 0.5
    assert screen['held_additions'] == (
        [{'outline_id': 'proposed', 'maximum_overlap_fraction': 1.0}] if small_addition else []
    )
    assert 'proposed outlines with at least 50% of their own area overlapping any single existing polygon' in merged['method']
