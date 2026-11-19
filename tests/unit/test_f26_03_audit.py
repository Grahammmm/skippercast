"""F26-03: the BlueTopo source screen must count only usable raster cells."""
from hashlib import sha256
import xml.etree.ElementTree as ET

import pytest

pytestmark = pytest.mark.gis  # The reserved test path requires the survey stack.
LOW_UNCERTAINTY = 'measured_since_min_year_below_navd88_uncertainty_le_1m_pixels'


@pytest.fixture
def audit_tile(tmp_path, monkeypatch):
    import numpy as np
    import rasterio
    from rasterio.transform import from_origin

    from research.scripts import audit_bluetopo_tile

    raster_path = tmp_path / 'SYN.tiff'
    rat_path = tmp_path / 'SYN.tiff.aux.xml'
    scheme = tmp_path / 'scheme'
    scheme.write_text('Synthetic scheme')
    root = ET.Element('PAMDataset')
    rat = ET.SubElement(ET.SubElement(root, 'PAMRasterBand', band='3'), 'GDALRasterAttributeTable')
    for name in ('value', 'coverage', 'bathy_coverage', 'source_survey_id', 'survey_date_end'):
        ET.SubElement(ET.SubElement(rat, 'FieldDefn'), 'Name').text = name
    row = ET.SubElement(rat, 'Row')
    for value in ('1', '1', '1', 'SYN', '2020-01-01'):
        ET.SubElement(row, 'F').text = value

    def run(pixels, *, mask=None, nodata=None):
        data = np.array(pixels, dtype='float32').T[:, None, :]
        with rasterio.open(raster_path, 'w', driver='GTiff', width=len(pixels), height=1,
                           count=3, dtype='float32', nodata=nodata, crs='EPSG:6349',
                           transform=from_origin(100, 200, 1, 1)) as dataset:
            dataset.write(data)
            dataset.descriptions = ('Elevation', 'Uncertainty', 'Contributor')
            if mask is not None:
                dataset.write_mask(np.array([mask], dtype='uint8'))
        ET.ElementTree(root).write(rat_path)
        monkeypatch.setattr(audit_bluetopo_tile, 'scheme_row', lambda *_: {
            'GeoTIFF_Link': 'https://example.invalid/synthetic.tiff',
            'RAT_Link': 'https://example.invalid/synthetic.tiff.aux.xml',
            'GeoTIFF_SHA256_Checksum': sha256(raster_path.read_bytes()).hexdigest(),
            'RAT_SHA256_Checksum': sha256(rat_path.read_bytes()).hexdigest(),
            'Delivered_Date': '2020-01-01',
        })
        return audit_bluetopo_tile.audit(scheme, 'SYN', tmp_path)

    return run


def test_four_pixel_control_excludes_masked_negative_and_high_uncertainty(audit_tile):
    # A raw read and an upper-bound-only filter counted three rather than one.
    result = audit_tile([(-12, .5, 1), (-12, -.1, 1), (-12, .5, 1), (-12, 2, 1)],
                        mask=[255, 255, 0, 255])
    assert result['counts'][LOW_UNCERTAINTY] == 1
    assert result['recent_measured_contributors'][0]['below_navd88_pixels'] == 2
    assert result['vertical_datum'] == 'NAVD88'
    assert result['fishing_target'] is result['exportable'] is False


def test_all_invalid_tile_counts_zero(audit_tile):
    # Nodata is present independently in each band; the other cells are nonfinite.
    missing = -9999
    result = audit_tile([(missing, .5, 1), (-12, missing, 1), (-12, .5, missing),
                         (float('-inf'), .5, 1), (-12, float('nan'), 1),
                         (-12, .5, float('inf'))], nodata=missing)
    assert result['counts'][LOW_UNCERTAINTY] == 0
    assert set(result['counts'].values()) == {0}
    assert result['recent_measured_contributors'] == []


def test_zero_and_one_metre_uncertainties_are_inclusive(audit_tile):
    assert audit_tile([(-12, 0, 1), (-12, 1, 1)])['counts'][LOW_UNCERTAINTY] == 2


@pytest.mark.parametrize('unrecognized', [2, 1.5])
def test_valid_cell_requires_exact_rat_code(audit_tile, unrecognized):
    # Missing codes still fail closed; 1.5 must not be truncated to the known code 1.
    with pytest.raises(ValueError, match='RAT does not identify all contributor codes'):
        audit_tile([(-12, .5, unrecognized)])
