"""Synthetic controls for four-connected predicted substrate at native seams."""
from datetime import datetime, timezone
from hashlib import sha256

import pytest

pytestmark = pytest.mark.gis


@pytest.fixture
def compile_tiles(tmp_path, monkeypatch):
    import lerc
    import numpy as np
    from pyproj import Transformer
    from shapely.geometry import box, mapping, shape
    from shapely.ops import transform

    from research.scripts import build_cdfw_substrate_context as cdfw
    from research.scripts import build_usgs_statewide_context as usgs

    now = datetime(2026, 1, 1, tzinfo=timezone.utc)

    class FrozenClock(datetime):
        @classmethod
        def now(cls, tz=None):
            return now.astimezone(tz)

    monkeypatch.setattr(cdfw, 'datetime', FrozenClock)
    monkeypatch.setattr(usgs, 'datetime', FrozenClock)
    to_wgs = Transformer.from_crs(3310, 4326, always_xy=True).transform

    def compile(pieces, *, origin=(0, 0), mpa=None):
        monkeypatch.setattr(cdfw, 'ORIGIN', origin)
        tiles = []
        for row, col, ys, xs, masked in pieces:
            values = np.full((256, 256), 2, dtype='uint8')
            values[ys, xs] = 1
            valid = np.ones(values.shape, dtype=bool)
            if masked:
                valid[masked] = False
            status, size = lerc.encode(values, 1, True, valid, 0, 0)
            assert status == 0
            status, _, encoded = lerc.encode(values, 1, True, valid, 0, size)
            assert status == 0
            blob = bytes(encoded)
            path = tmp_path / str(cdfw.LEVEL) / str(row) / f'{col}.lerc'
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(blob)
            tiles.append({'row': row, 'col': col, 'sha256': sha256(blob).hexdigest(),
                          'hard_cells': int(np.count_nonzero((values == 1) & valid))})

        if mpa is None:
            mpa = box(-2000, -2000, -1000, -1000)
        # Synthetic snapshot passes the unmodified completeness and freshness screen.
        closure = {'type': 'Feature', 'geometry': mapping(transform(to_wgs, mpa))}
        mpas = {'sources': {'mpas': {'status': 'ok', 'data_retrieved_at': now.isoformat(),
                'data': {'geojson': {'type': 'FeatureCollection', 'features': [closure] * 100}}}}}
        audit = {'scope': 'cdfw-ds3091-40m-tile-audit', 'checked_at': now.isoformat(),
                 'metadata_url': 'https://example.test/synthetic', 'failures': [],
                 'requested_tiles': len(tiles), 'audited_tiles': len(tiles), 'tiles': tiles}
        coasts = {'regions': [{'id': 'synthetic', 'latitude': [-90, 90]}]}
        return cdfw.build(audit, mpas, coasts, tmp_path)['synthetic']['features']

    return compile, shape, box


@pytest.mark.parametrize('vertical', [False, True], ids=['east-west', 'north-south'])
def test_split_120_cells_match_within_tile_control(compile_tiles, vertical):
    """A per-tile threshold silently omits both 60-cell halves."""
    compile, shape, _ = compile_tiles
    if vertical:
        whole = compile([(0, 0, slice(0, 20), slice(0, 6), None)], origin=(0, -9840))
        split = compile([(0, 0, slice(246, 256), slice(0, 6), None),
                         (1, 0, slice(0, 10), slice(0, 6), None)])
    else:
        whole = compile([(0, 0, slice(0, 6), slice(0, 20), None)], origin=(9840, 0))
        split = compile([(0, 0, slice(0, 6), slice(246, 256), None),
                         (0, 1, slice(0, 6), slice(0, 10), None)])
    assert [f['properties']['approx_area_m2'] for f in whole] == [192_000]
    assert [f['properties']['approx_area_m2'] for f in split] == [192_000]
    assert shape(split[0]['geometry']).equals(shape(whole[0]['geometry']))
    properties = split[0]['properties']
    assert properties['source_class'] == 'Predicted hard (rugosity proxy)'
    for key in ('fishing_target', 'exportable', 'depth_qualified', 'fish_confirmed'):
        assert properties[key] is False


@pytest.mark.parametrize('barrier', ['soft', 'nodata', 'corner', 'mpa'])
def test_disconnected_subthreshold_fragments_stay_omitted(compile_tiles, barrier):
    """Tile adjacency, point contact, and screened gaps cannot supply patch area."""
    compile, _, box = compile_tiles
    top, left, masked, mpa = 0, 0, None, None
    if barrier == 'soft':
        left = 1
    elif barrier == 'nodata':
        masked = (slice(0, 6), 0)
    elif barrier == 'corner':
        top = 6
    else:
        mpa = box(10220, -500, 10260, 200)
    assert compile([(0, 0, slice(0, 6), slice(246, 256), None),
                    (0, 1, slice(top, top + 6), slice(left, 11 if masked else left + 10), masked)],
                   mpa=mpa) == []


def test_exact_minimum_can_require_two_seams(compile_tiles):
    """No adjacent pair is large enough; the complete component is exactly 100 cells."""
    compile, _, _ = compile_tiles
    features = compile([(1, 1, slice(0, 10), slice(0, 5), None),
                        (0, 1, slice(251, 256), slice(0, 5), None),
                        (0, 0, slice(251, 256), slice(251, 256), None)])
    assert [feature['properties']['approx_area_m2'] for feature in features] == [160_000]
