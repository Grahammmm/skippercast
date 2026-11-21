"""NOAA survey leads must belong to the current sector footprint (F33-09)."""
from datetime import datetime, timezone
import json
from urllib.parse import parse_qsl, urlencode, urlsplit

import pytest

from scripts.discover_noaa_surveys import scan


@pytest.mark.gis
@pytest.mark.parametrize(('bounds', 'request_changes', 'available'), [
    pytest.param([0, 0, 4, 4], {'geometry': '0.0,0.00,4.0,4.00'}, True, id='same-envelope'),
    pytest.param([10, 10, 14, 14], {}, False, id='moved-sector'),
    pytest.param([0, 0, 5, 4], {}, False, id='changed-overlapping-envelope'),
    pytest.param([0, 0, 4, 4], {'inSR': '3857'}, False, id='wrong-crs'),
    pytest.param([0, 0, 4, 4], {'inSR': ''}, False, id='missing-crs'),
    pytest.param([0, 0, 4, 4], {'geometryType': 'esriGeometryPoint'}, False, id='wrong-geometry-type'),
])
def test_only_current_sector_request_counts_leads(bounds, request_changes, available):
    from research.scripts.summarize_native_sector_leads import build

    # Keep a valid historical discovery and BAG hit while changing only what
    # binds it to the current sector. Joining on sector ID alone miscounts it.
    historical = {'id': 'synthetic', 'name': 'Synthetic', 'coast': 'synthetic', 'bounds': [0, 0, 4, 4]}
    response = {'features': [{'attributes': {'SURVEY_ID': 'H00001', 'BAGS_EXIST': 'Y',
                                           'DOWNLOAD_URL': 'https://www.ncei.noaa.gov/synthetic'}}]}
    discovery = scan([historical], now=datetime(2025, 1, 1, tzinfo=timezone.utc),
                     fetcher=lambda _: json.dumps(response).encode())
    item = discovery['sectors'][0]
    url = urlsplit(item['request_url'])
    query = dict(parse_qsl(url.query))
    query.update(request_changes)
    item['request_url'] = url._replace(query=urlencode(query)).geturl()
    bag = 'https://example.invalid/synthetic.bag'
    audit = {'scope': 'noaa-original-bag-native-overview-audit', 'collected_at': discovery['collected_at'],
             'max_bytes': 100, 'file_count': 1, 'inspected_count': 1, 'health': {'status': 'ok'},
             'files': [{'survey_id': 'H00001', 'url': bag, 'status': 'ok', 'raster_bounds_wgs84': [1, 1, 2, 2],
                        'metadata_status': 'mllw-product-uncertainty-reviewed-by-adapter',
                        'overview_resolution_m': [2, 2], 'variable_refinement_records': 0}]}
    overlap = {'scope': 'statewide-native-depth-substrate-overlap-leads', 'leads': [{'url': bag}]}
    sectors = {'schema_version': 1, 'sectors': [dict(historical, bounds=bounds)]}

    (row,) = build(audit, discovery, sectors, overlap)['sectors']

    if available:
        assert row['status'] == 'review-leads'
        assert row['eligible_for_native_substrate_review_bboxes'] == 1
        assert row['eligible_substrate_review_bag_urls'] == [bag]
    else:
        assert row['status'] == 'unavailable'
        assert 'eligible_for_native_substrate_review_bboxes' not in row
        assert 'eligible_substrate_review_bag_urls' not in row
