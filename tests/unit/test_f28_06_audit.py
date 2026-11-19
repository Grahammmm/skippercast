"""F28-06: chart hazard counts use metric distance, not just envelope hits."""
from types import SimpleNamespace

import pytest

pytestmark = pytest.mark.gis


@pytest.mark.parametrize(('point', 'expected'), [
    pytest.param((199, 199), (0, 1), id='140m-corner'),
    pytest.param((349, 349), (0, 0), id='outside-250m-corner'),
    pytest.param((100, 50), (1, 1), id='touching'),
    pytest.param((200, 50), (1, 1), id='exactly-100m'),
    pytest.param((350, 50), (0, 1), id='exactly-250m'),
])
def test_enc_proximity_counts_only_blocks_within_margin(monkeypatch, point, expected):
    from shapely.geometry import Point, box, mapping

    from research.scripts import audit_point_buchon_private_block_access as screen

    # Use an invented metre grid to keep threshold distances exact. Only the
    # projection is stubbed; the real audit computes both counts with STRtree.
    monkeypatch.setattr(screen, 'Transformer', SimpleNamespace(
        from_crs=lambda *args, **kwargs: SimpleNamespace(transform=lambda x, y: (x, y)),
    ))
    bounds = (-1000, -1000, 2500, 2500)
    monkeypatch.setattr(screen, 'MPA_QUERY_BOUNDS', bounds)
    block = {'geometry': mapping(box(0, 0, 100, 100))}
    far_block = {'geometry': mapping(box(1000, 1000, 1100, 1100))}
    inputs = {
        'rov_blocks': {'crs': 'EPSG:32610', 'features': [block] + [far_block] * 25},
        'terrain_blocks': {'crs': 'EPSG:32610', 'features': [far_block] * 181},
        'cdfw_mpas': {
            'crs': {'properties': {'name': 'EPSG:4326'}},
            'features': [{'properties': {'NAME': name}, 'geometry': mapping(box(800, 800, 900, 900))}
                         for name in screen.EXPECTED_MPAS],
            'checked_at': 'synthetic', 'source_url': 'https://example.test/mpa',
        },
        'noaa_enc': {
            'scope_id': 'point-buchon-open-reference-hard-context',
            'bounds': bounds,
            'query_receipts': [{'count': 1}] + [{'count': 0}] * 17,
            'features': [{'geometry': mapping(Point(*point))}],
            'checked_at': 'synthetic', 'source_url': 'https://example.test/enc',
        },
    }

    groups = screen.audit(inputs)['groups']
    keys = ('any_enc_feature_within_100m', 'any_enc_feature_within_250m')
    assert tuple(groups['rov_blocks'][key] for key in keys) == expected
