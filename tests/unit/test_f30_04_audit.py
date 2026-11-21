"""F30-04: original legends, not words from adjacent classes, select hard bottom."""

from datetime import datetime, timezone
import hashlib
import zipfile

import pytest

from research.scripts.audit_usgs_map_metadata import parse_metadata

NOW = datetime(2026, 9, 23, tzinfo=timezone.utc)
XML_URL = 'https://example.invalid/SeafloorCharacter.xml'
ARCHIVE_URL = 'https://example.invalid/SeafloorCharacter.zip'
LEGACY = ('Coded values of the substrate classes. Class 1, Fine- to medium-grained smooth sediment; '
          'Class 2, Mixed smooth sediment and rock; Class 3, Rock and boulder, rugose; '
          'Class 4, Medium- to coarse- grained sediment')
MODERN = ('3', 'hard and rugose boulder, megaclast, and bedrock seafloor')


def original_legend(*, definitions=(), values=()):
    attrs = ''.join(f'<attr><attrlabl>{field}</attrlabl><attrdef>{text}</attrdef></attr>'
                    for field, text in definitions)
    domains = ''.join(f'<attrdomv><edom><edomv>{code}</edomv><edomvd>{label}</edomvd></edom></attrdomv>'
                      for code, label in values)
    raw = ('<metadata><bounding><westbc>-10</westbc><eastbc>0</eastbc>'
           '<southbc>0</southbc><northbc>10</northbc></bounding>'
           f'<eainfo><detailed>{attrs}<attr><attrlabl>Value</attrlabl>{domains}</attr>'
           '</detailed></eainfo></metadata>').encode()
    return parse_metadata(XML_URL, raw, now=NOW)


@pytest.fixture
def builders(monkeypatch):
    from shapely.geometry import Polygon

    from research.scripts import build_usgs_doi_context as doi
    from research.scripts import build_usgs_statewide_context as statewide

    for module in (doi, statewide):
        monkeypatch.setattr(module, 'mpa_union', lambda _: Polygon())

    def build(record, cache):
        product = {'metadata_url': XML_URL, 'filename': 'synthetic.tif'}
        row = {'kind': 'seafloor_character', 'status': 'ok', 'release_id': 'SYNTHETIC',
               'block_id': 'SYNTHETIC', 'metadata_url': XML_URL, 'archive_url': ARCHIVE_URL,
               'archive_sha256': record['archive_sha256'], 'metadata_sha256': record['xml_sha256']}
        mpas = {'sources': {'mpas': {'data_retrieved_at': NOW.isoformat()}}}
        metadata = {'scope': 'usgs-state-waters-doi-native-metadata', 'records': [{**record, **row}]}
        statewide_result = statewide.build(
            {'source_url': XML_URL, 'blocks': [{'id': 'SYNTHETIC', 'products': {row['kind']: [product]}}]},
            metadata, {'scope': 'usgs-state-waters-native-grid-audit', 'products': [row]}, mpas, cache,
        )
        doi_result = doi.build(
            {'scope': 'usgs-state-waters-doi-product-links', 'releases': [{'products': [product]}]},
            metadata, {'scope': 'usgs-state-waters-doi-native-grid-audit', 'products': [row]}, mpas, cache,
            {'schema_version': 1, 'scope': 'reviewed-usgs-natural-hard-context-holds'},
        )
        return (statewide_result['features'], statewide_result['failed_blocks']), (
            doi_result['features'], doi_result['failed_releases'])

    return build


@pytest.fixture
def raster_digest(tmp_path):
    import numpy as np
    import rasterio
    from rasterio.transform import from_origin

    # Two separable 6,400 m² patches: bare 3 and composite 13. Class 4 is neither.
    data = np.full((16, 48), 4, dtype='uint8')
    data[:, :16] = 3
    data[:, 32:] = 13
    tif = tmp_path / 'synthetic.tif'
    with rasterio.open(tif, 'w', driver='GTiff', count=1, dtype='uint8', width=48, height=16,
                       crs='EPSG:3857', transform=from_origin(-120, 80, 5, 5)) as raster:
        raster.write(data, 1)
    key = hashlib.sha256(ARCHIVE_URL.encode()).hexdigest()[:16]
    archive = tmp_path / f'SYNTHETIC-seafloor_character-{key}.zip'
    with zipfile.ZipFile(archive, 'w') as bundle:
        bundle.write(tif, tif.name)
    return hashlib.sha256(archive.read_bytes()).hexdigest()


@pytest.mark.gis
@pytest.mark.parametrize(('definitions', 'values', 'count'), [
    # Each negative previously accepted a wrong class-3 patch: same-field spillover,
    # cross-field spillover, numeric-prefix match, or accepting one of two conflicting claims.
    pytest.param((('SUBSTRATE', 'Class 3: sediment; Class 4: Rock and boulder, rugose'),), (), 0,
                 id='split-classes-same-field'),
    pytest.param((('SUBSTRATE', 'Class 3: sediment'), ('FULL_DESC', 'Class 4: Rock and boulder, rugose')),
                 (), 0, id='split-classes-across-fields'),
    pytest.param((('SUBSTRATE', 'Class 30: Rock and boulder, rugose'),), (), 0, id='class-30-is-not-3'),
    pytest.param((('SUBSTRATE', LEGACY), ('FULL_DESC', 'Class 3: smooth sediment')),
                 (), 0, id='contradictory-prose'),
    pytest.param((('SUBSTRATE', LEGACY),), (('3', 'soft sediment'),), 0, id='contradictory-encoding'),
    pytest.param((('SUBSTRATE', LEGACY),), (('13', 'soft sediment'),), 0, id='contradictory-composite-value'),
    pytest.param((), (MODERN, ('3', 'soft sediment')), 0, id='contradictory-enumeration'),
    pytest.param((('SUBSTRATE', LEGACY),), (), 2, id='reviewed-composite-retains-13'),
    pytest.param((), (MODERN,), 1, id='modern-legend-does-not-select-13'),
])
def test_both_context_builders_use_original_class_3_mapping(definitions, values, count, raster_digest, builders, tmp_path):
    record = original_legend(definitions=definitions, values=values)
    for features, failures in builders({**record, 'archive_sha256': raster_digest}, tmp_path):
        assert len(features) == count
        assert bool(failures) == (count == 0)
        assert all(not feature['properties']['fishing_target'] for feature in features)
        # The two patches straddle the synthetic prime meridian. Check identity,
        # not just the number of patches (selecting only 13 is also one patch).
        assert sorted(feature['geometry']['coordinates'][0][0][0] > 0 for feature in features) == (
            [False, True][:count])
