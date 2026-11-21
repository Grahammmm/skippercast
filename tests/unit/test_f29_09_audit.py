"""F29-09: every valid overlapping sample counts toward depth-band support."""
from contextlib import nullcontext
from io import BytesIO
from itertools import permutations
import tarfile
import zipfile

import pytest

pytestmark = pytest.mark.gis


@pytest.mark.parametrize('order', list(permutations(('a', 'b', 'c'))))
@pytest.mark.parametrize('third_depth, spread, feet_range, in_band', [
    pytest.param(-70, 50, [65.6, 229.7], False, id='too-deep'),
    pytest.param(-5, 25, [16.4, 98.4], False, id='too-shallow'),
    pytest.param(-40, 20, [65.6, 131.2], True, id='all-in-band'),
])
def test_overlap_uses_both_depth_extrema(tmp_path, monkeypatch, order, third_depth, spread,
                                         feet_range, in_band):
    import numpy as np
    from rasterio.crs import CRS

    from research.scripts import audit_usgs_ds552_san_pedro as audit

    # The old first-grid rule can miss an out-of-band value and understate spread
    # when the first sample is between the other two. The second cell has only
    # one valid measurement; neither nodata nor NaN counts toward its extrema.
    depths = {'a': (-30, -9999), 'b': (-20, -30), 'c': (third_depth, float('nan'))}

    class Grid:
        driver = 'AIG'
        crs = CRS.from_epsg(32611)
        res = (4.0, 4.0)
        count = 1
        nodata = -9999

        def __init__(self, name):
            self.values = depths[name]

        def sample(self, points):
            return ([self.values[1 if x == 1 else 0]] for x, _ in points)

    sources = {}
    for name in order:
        tar = BytesIO()
        with tarfile.open(fileobj=tar, mode='w'):
            pass
        archive = tmp_path / f'{name}.tgz'
        with zipfile.ZipFile(archive, 'w') as bundle:
            bundle.writestr(f'{name}.tar', tar.getvalue())
        sources[name] = (audit.sha256(archive), 'synthetic')
    monkeypatch.setattr(audit, 'DEPTH_SOURCES', sources)
    monkeypatch.setattr(audit.rasterio, 'open', lambda path: nullcontext(Grid(path.parent.name)))
    row = {'component_id': 1, 'bbox_center_lon_lat': [0, 0], 'rock_class_area_m2': 32}
    summary = audit.audit_depth_support([row], tmp_path, (np.array([1, 1]), [(0, 0), (1, 0)]))
    review = row['original_full_rock_depth_review']
    assert summary['maximum_overlapping_grid_disagreement_m'] == spread
    assert summary['whole_footprint_depth_band_supported_components'] == int(in_band)
    assert review['maximum_overlapping_grid_disagreement_m'] == spread
    assert review['whole_footprint_depth_band_supported'] is in_band
    assert review['depth_covered_cells'] == 2
    assert review['depth_cells_in_25_to_200_ft_mllw'] == (2 if in_band else 1)
    assert review['overlapping_source_cells'] == 1
    assert review['sampled_rock_depth_ft_range'] == feet_range
