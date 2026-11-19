"""F26-07: unknown habitat is not other; proximity extends past the grid."""
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import patch
import tarfile
from zipfile import ZipFile

import pytest

np = pytest.importorskip('numpy')
pytest.importorskip('rasterio')
pytest.importorskip('pyproj')
pytest.importorskip('shapefile')
pytest.importorskip('shapely')
from rasterio.transform import from_origin

from research.scripts import audit_bss02_video_grid_overlap as audit


class SyntheticGrid:
    crs = 'EPSG:26910'
    transform = from_origin(0, 20, 2, 2)
    res = (2.0, 2.0)
    height = width = 10
    shape = (10, 10)
    bounds = SimpleNamespace(left=0, bottom=0, right=20, top=20)

    def __init__(self, habitat=False):
        self.habitat = habitat

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def index(self, x, y):
        return int((20 - y) // 2), int(x // 2)

    def read_masks(self, band):
        return np.full(self.shape, 255, dtype=np.uint8)

    def read(self, band, masked=False):
        if not self.habitat:
            return np.full(self.shape, -75.0)
        data = np.zeros(self.shape, dtype=int)
        data[5, 5] = -1  # rough positive control
        mask = np.zeros(self.shape, dtype=bool)
        mask[5, 7] = True
        return np.ma.array(data, mask=mask)


def point(x, y):
    return SimpleNamespace(
        shape=SimpleNamespace(points=[(x, y)]),
        record=SimpleNamespace(as_dict=lambda: {'MAJOR_GEO': 'rock'}),
    )


def test_unknown_and_outside_proximity_are_not_lost(tmp_path):
    # Regression: masked terrain used to count as non-rough, and the outside
    # point was dropped before the proximity test. The far point is negative.
    archive = tmp_path / 'grids.tar.gz'
    with tarfile.open(archive, 'w:gz') as bundle:
        for name in ('depth/grid', 'habitat/grid'):
            member = tarfile.TarInfo(name)
            member.size = 1
            bundle.addfile(member, BytesIO(b'x'))
    raw = BytesIO()
    with ZipFile(raw, 'w') as source:
        source.writestr('metadata.txt', 'Highly variable on the order of 10 meters.')
    camera = SimpleNamespace(iterShapeRecords=lambda: iter([
        point(11, 9), point(13, 9), point(15, 9), point(21, 9), point(200, 9),
    ]))
    transformer = SimpleNamespace(transform=lambda x, y: (x, y))
    spec = {'survey_id': 'BSS_Block02', 'bathymetry_grid': 'depth',
            'habitat_grid': 'habitat', 'archive_url': 'synthetic',
            'archive_sha256': 'synthetic', 'native_vertical_datum': 'synthetic'}
    manifest = {'archives': {audit.CRUISE: 'synthetic'}, 'base_url': 'synthetic/'}
    with (patch.object(audit, 'acquire', return_value=archive),
          patch.object(audit, 'load_archive', return_value=raw.getvalue()),
          patch.object(audit, 'open_original_zip', return_value=camera),
          patch.object(audit.rasterio, 'open', side_effect=[SyntheticGrid(), SyntheticGrid(True)]),
          patch.object(audit.Transformer, 'from_crs', return_value=transformer)):
        result = audit.inspect(spec, manifest, tmp_path, tmp_path)
    assert result['camera_records_inside_raster_bounds'] == 3
    assert result['camera_records_on_valid_depth_pixel'] == 3
    assert result['camera_records_within_100m_of_valid_depth_pixel'] == 4
    assert result['rock_boulder_cobble_windows_on_derived_rough_class'] == 1
    assert result['rock_boulder_cobble_windows_off_derived_rough_class'] == 1
    assert result['rock_boulder_cobble_windows_unknown_derived_class'] == 1
    assert result['rock_boulder_cobble_windows_in_band'] == 3
    assert result['rank_effect'] == 'none'
    assert result['exportable'] is False
