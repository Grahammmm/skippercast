"""F32-09: Even a BAG with no hits must match the reviewed source bytes."""
from contextlib import contextmanager
from datetime import datetime, timezone
from hashlib import sha256
import json
from types import SimpleNamespace

import pytest

pytestmark = pytest.mark.gis


@pytest.mark.parametrize(('changed', 'intersects'), [
    pytest.param(True, False, id='changed-disjoint'),
    pytest.param(False, False, id='verified-disjoint'),
    pytest.param(False, True, id='verified-intersecting'),
])
def test_overlap_counts_require_reviewed_bag(tmp_path, monkeypatch, changed, intersects):
    import numpy as np
    from pyproj import CRS, Transformer
    from pyproj.crs import CompoundCRS
    from rasterio.coords import BoundingBox

    from research.scripts import review_noaa_seabed_native_overlap as audit

    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    lon, lat = -120, 36  # Invented observation, not a site record.
    x, y = Transformer.from_crs(4326, 3310, always_xy=True).transform(lon, lat)
    hit_bytes = json.dumps([x - 1, y - 1, x + 1, y + 1]).encode()
    miss_bytes = json.dumps([x + 9, y + 9, x + 11, y + 11]).encode()
    reviewed = hit_bytes if changed or intersects else miss_bytes
    url = 'https://example.invalid/synthetic.bag'
    path = tmp_path / f'synthetic-{sha256(url.encode()).hexdigest()[:16]}.bag'
    path.write_bytes(miss_bytes if changed else reviewed)
    crs = CompoundCRS('Synthetic compound', [CRS.from_epsg(3310), CRS.from_epsg(5866)])

    def read_cell(*args, **kwargs):
        assert intersects, 'Disjoint bounds must not cause a cell read'
        return np.array([[[-15.0]], [[0.1]]])

    @contextmanager
    def open_bag(candidate):
        assert candidate == path
        # Only replace the GDAL decoder: bounds come from the same local bytes
        # that the real digest check reads. Both versions have plausible headers.
        yield SimpleNamespace(driver='BAG', count=2, crs=crs, res=(2, 2),
                              bounds=BoundingBox(*json.loads(candidate.read_bytes())),
                              height=1, width=1, index=lambda x, y: (0, 0), read=read_cell)

    monkeypatch.setattr(audit.rasterio, 'open', open_bag)
    sample = {'type': 'Feature', 'geometry': {'type': 'Point', 'coordinates': [lon, lat]},
              'properties': {'OBJECTID': 1, 'DESCRP': 'rock'}}
    page = json.dumps({'type': 'FeatureCollection', 'features': [sample]}).encode()
    (tmp_path / 'page-01.geojson').write_bytes(page)
    samples = {'scope': 'california-historical-nos-seabed-sample-sector-audit',
               'page_sha256': [sha256(page).hexdigest()], 'bounded_original_sample_count': 1,
               'sectors': [{'uncurated_description_rock_word_count': 1}]}
    regular = {'scope': 'california-original-regular-native-depth-review', 'status': 'ok',
               'survey_file_count': 1, 'files': [{'status': 'ok', 'bag_url': url,
                                                'survey_id': 'synthetic', 'bag_sha256': sha256(reviewed).hexdigest()}]}
    sectors = [{'id': 'synthetic', 'bounds': [-121, 35, -119, 37]}]
    other_point = {'geometry': {'type': 'Point', 'coordinates': [lon, lat + 1]}}
    mpas = {'sources': {'mpas': {'status': 'ok', 'data_retrieved_at': now.isoformat(),
                               'data': {'geojson': {'features': [other_point] * 100}, 'feature_count': 100}}}}
    bodega = {'scope': 'sf-native-noaa-usgs-hard-bottom-context', 'features': []}
    args = (tmp_path, samples, regular, tmp_path, sectors, mpas, bodega)

    if changed:
        with pytest.raises(ValueError, match='Original NOAA BAG bytes changed'):
            audit.review(*args, now=now)
        return

    result = audit.review(*args, now=now)
    expected_hits = int(intersects)
    assert result['source_files_with_envelope_hits'] == expected_hits
    assert result['file_envelope_hits'] == expected_hits
    assert result['measured_file_cell_hits'] == expected_hits
    assert result['qualified_file_cell_hits'] == expected_hits
    assert result['sectors'][0]['uncurated_rock_word_samples'] == 1
    assert result['sectors'][0]['within_audited_regular_bag_envelope'] == expected_hits
