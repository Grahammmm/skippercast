"""Validate the static publication, its reviewed data copies, and local assets."""
from pathlib import Path
from html.parser import HTMLParser
import hashlib
import json
import re
from urllib.parse import urlsplit, unquote
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "dist"
ATLAS = ROOT / "atlas/avila-point-estero-2026-09-20"


class AssetParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.refs = []

    def handle_starttag(self, tag, attrs):
        self.refs.extend(value for key, value in attrs if key in {"src", "href"} and value)


def check_native_depth_review(name, scope):
    """Keep an incomplete native-source pass off the public coastal guide."""
    data = json.loads((WEB / 'data' / name).read_text())
    sectors = json.loads((WEB / 'data/coastal-sectors.json').read_text())['sectors']
    sector_ids = {row['id'] for row in sectors}
    assert data['scope'] == scope and data['status'] == 'ok' and not data['failed_survey_ids'], name
    assert data['survey_file_count'] == len(data['files']) and data['survey_file_count'] > 0, name
    assert {row['sector_id'] for row in data['sectors']} == sector_ids, name
    assert len(data['sectors']) == len(sector_ids), name
    assert len({row['bag_url'] for row in data['files']}) == len(data['files']), name
    expected = {sector_id: {'source_files_with_eligible_cells': 0,
                            'measured_native_cells': 0,
                            'depth_uncertainty_eligible_cells': 0}
                for sector_id in sector_ids}
    for source in data['files']:
        assert source['status'] == 'ok' and source['bag_sha256'], name
        assert set(source['sectors']) <= sector_ids, name
        counts = source['counts']
        assert 0 <= counts['depth_uncertainty_eligible_cells'] <= counts['measured_native_cells'], name
        for sector_id, values in source['sectors'].items():
            assert 0 <= values['depth_uncertainty_eligible_cells'] <= values['measured_native_cells'], name
            rollup = expected[sector_id]
            rollup['source_files_with_eligible_cells'] += values['depth_uncertainty_eligible_cells'] > 0
            for field in ('measured_native_cells', 'depth_uncertainty_eligible_cells'):
                rollup[field] += values[field]
    for row in data['sectors']:
        for key, value in expected[row['sector_id']].items():
            assert row[key] == value, (name, row['sector_id'], key)


def check_expanded_native_depth_inventory():
    name = 'noaa-vr-native-depth-expanded-review.json'
    data = json.loads((WEB / 'data' / name).read_text())
    manifest = json.loads((ROOT / 'catalog/noaa-vr-native-review-sources.json').read_text())
    assert manifest['scope'] == 'california-original-vr-depth-review-inputs'
    reviews = [json.loads((ROOT / path).read_text()) for path in manifest['review_files']]
    sectors = json.loads((WEB / 'data/coastal-sectors.json').read_text())['sectors']
    assert data['scope'] == 'california-expanded-original-vr-depth-inventory'
    assert data['source_review_count'] == len(reviews)
    assert data['survey_file_count'] == len(data['files']) == sum(r['survey_file_count'] for r in reviews)
    assert data['fishing_target'] is False and data['exportable'] is False
    assert {row['sector_id'] for row in data['sectors']} == {row['id'] for row in sectors}
    assert len({row['bag_url'] for row in data['files']}) == len(data['files'])
    assert {row['bag_url'] for row in data['files']} == {
        file['bag_url'] for review in reviews for file in review['files']}
    for row in data['sectors']:
        contributors = [source for source in data['files'] if source['sectors'].get(
            row['sector_id'], {}).get('depth_uncertainty_eligible_cells', 0) > 0]
        assert row['survey_ids_with_eligible_cells'] == sorted({s['survey_id'] for s in contributors})
        assert row['source_files_with_eligible_cells'] == len(contributors)
        for key in ('fine_native_grids', 'measured_native_cells',
                    'depth_uncertainty_eligible_cells'):
            assert row[key] == sum(source['sectors'].get(row['sector_id'], {}).get(key, 0)
                                   for source in data['files'])


def check_central_sediment_context():
    manifest = json.loads((ROOT / 'catalog/usgs-central-sediment-source.json').read_text())
    data = json.loads((WEB / 'data/usgs-central-thin-sediment-context.geojson').read_text())
    assert data['type'] == 'FeatureCollection'
    assert data['scope'] == 'usgs-central-interpreted-sediment-context'
    assert data['source']['raster_sha256'] == manifest['raster_sha256']
    assert data['source']['metadata_sha256'] == manifest['metadata_sha256']
    assert data['screen']['negative_source_cells_excluded'] > 0
    assert len(data['features']) >= 20
    for feature in data['features']:
        props = feature['properties']
        assert feature['geometry']['type'] in {'Polygon', 'MultiPolygon'}
        assert props['source_id'] == manifest['id']
        assert props['kind'] == 'estimated-thin-sediment'
        assert props['estimated_sediment_thickness_m'] == [0, manifest['screening_threshold_m']]
        assert all(props[key] is False for key in
                   ('fishing_target', 'exportable', 'depth_qualified', 'fish_confirmed'))


def check_usgs_morro_report_datum():
    manifest = json.loads((ROOT / 'catalog/usgs-morro-report-datum-source.json').read_text())
    review = json.loads((WEB / 'data/usgs-morro-report-datum-review.json').read_text())
    assert review['scope'] == manifest['scope']
    assert review['report_sha256'] == manifest['report_sha256']
    assert review['report_url'] == manifest['report_url']
    assert review['report_depth_reference'] == 'MLLW'
    assert {row['release_id'] for row in review['sources']} == set(manifest['release_ids'])
    assert all(row['depth_qualified_for_fishing'] is False and
               row['has_per_cell_product_uncertainty'] is False and
               row['vertical_accuracy_lower_bound_m'] == .2 and
               row['vertical_accuracy_upper_bound_m'] is None for row in review['sources'])
    assert review['fishing_target'] is False and review['exportable'] is False


def check_usgs_bathy_accuracy_statewide():
    review = json.loads((WEB / 'data/usgs-bathymetry-accuracy-review.json').read_text())
    ledger = json.loads((WEB / 'data/usgs-depth-datum-ledger.json').read_text())
    assert review['scope'] == 'california-usgs-original-bathymetry-accuracy-review'
    assert review['status'] == 'ok' and not review['issues']
    assert review['source_grid_count'] == review['fully_verified_source_count'] == len(review['sources']) == ledger['source_grid_count']
    originals = {row['metadata_url']: row for row in ledger['sources']}
    assert {row['metadata_url'] for row in review['sources']} == set(originals)
    for row in review['sources']:
        assert row['status'] == 'ok' and row['metadata_sha256'] == originals[row['metadata_url']]['metadata_sha256']
        assert row['depth_qualified_for_fishing'] is False
        assert row['per_cell_uncertainty_available'] is False
    assert review['fishing_target'] is False and review['exportable'] is False


def check_h11876_sidescan_context():
    review = json.loads((WEB / 'data/h11876-original-sidescan-review.json').read_text())
    assert review['scope'] == 'h11876-original-sidescan-camera-context'
    assert review['source_sha256'] == 'fea036f596158b4f549ad86b83a8f66068637c24f848b867f3e772b8cf5f09e0'
    assert review['actual_raster_pixel_size_m'] == [1.5, 1.5]
    assert review['reviewed_rocky_windows_with_sidescan_coverage'] == review['reviewed_rocky_window_count'] == 11
    assert sum(row['patch_count'] for row in review['transects']) == 44
    assert review['fishing_target'] is False and review['exportable'] is False
    assert all('latitude' not in row and 'longitude' not in row and 'coordinates' not in row
               for row in review['transects'])


def main():
    assert (WEB / "index.html").is_file()
    induration = json.loads((WEB / 'data/h11967-noaa-induration-camera-review.json').read_text())
    chart = json.loads((WEB / 'data/h11967-enc-camera-research-screen.json').read_text())
    assert induration['scope'] == 'original-bag-camera-versus-noaa-2017-induration-research'
    assert induration['survey_id'] == 'H11967' and induration['camera_windows_checked'] == 18
    assert induration['source_context_sha256'] == chart['candidate_research_context_sha256']
    assert sum(induration['class_counts'].values()) == len(induration['rows']) == 18
    assert sum(induration['quality_counts'].values()) == 18
    assert induration['fishing_target'] is False and induration['exportable'] is False
    assert all('coordinates' not in row and 'longitude' not in row and 'latitude' not in row
               for row in induration['rows'])
    readiness = json.loads((WEB / 'data/california-atlas-readiness.json').read_text())
    usgs_leads = json.loads((WEB / 'data/usgs-ds781-source-leads.json').read_text())
    assert (WEB / 'data/usgs-ds781-source-leads.json').read_bytes() == (ROOT / 'catalog/usgs-ds781-source-leads.json').read_bytes()
    assert len(usgs_leads['map_areas']) == 39
    assert all(area['priority_product_status'] != 'linked' or area['products']
               for area in usgs_leads['map_areas'])
    sectors = json.loads((WEB / 'data/coastal-sectors.json').read_text())['sectors']
    assert len(readiness['sectors']) == len(sectors) == 19
    assert {row['sector_id'] for row in readiness['sectors']} == {row['id'] for row in sectors}
    assert all(row['status'] in {'source-review-only', 'partial-local-targets'}
               and row['remaining_promotion_gates'] for row in readiness['sectors'])
    assert all('usgs_ds781_map_area_leads' in row for row in readiness['sectors'])
    assert (WEB / "data/atlas.json").read_bytes() == (ATLAS / "data/atlas.json").read_bytes()
    for name in ["complete.gpx", "waypoints.gpx", "reef-outlines.gpx", "drift-lines.gpx", "spot-notes.html"]:
        assert (WEB / "downloads" / name).read_bytes() == (ATLAS / "exports" / name).read_bytes(), name
    assert (WEB / "downloads/LICENSE.txt").read_bytes() == (ROOT / "LICENSE").read_bytes()
    for name, digest in json.loads((ROOT / "scripts/web-vendor-sha256.json").read_text()).items():
        assert hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == digest, name
    for path in WEB.rglob("*.html"):
        if path.relative_to(WEB).parts[0] in {"client","server"}:continue
        parser = AssetParser()
        parser.feed(path.read_text())
        for ref in parser.refs:
            url = urlsplit(ref)
            if url.scheme or url.netloc or not url.path:
                continue
            target = (path.parent / unquote(url.path)).resolve()
            assert target.is_relative_to(WEB) and target.exists(), (path, ref)
    for path in WEB.rglob("*.css"):
        if path.relative_to(WEB).parts[0] in {"client","server"}:continue
        for ref in re.findall(r"url\(['\"]?([^)'\"]+)", path.read_text()):
            url = urlsplit(ref)
            if not url.scheme and url.path:
                assert (path.parent / unquote(url.path)).is_file(), (path, ref)
    ns = {"g": "http://www.topografix.com/GPX/1/1"}
    full = ET.parse(WEB / "downloads/complete.gpx").getroot()
    assert len(full.findall("g:wpt", ns)) == 132
    for path in (WEB / "downloads").glob("*.gpx"):
        assert ET.parse(path).getroot().tag == "{http://www.topografix.com/GPX/1/1}gpx"
    check_native_depth_review('noaa-vr-native-depth-review.json',
                              'california-original-vr-native-depth-review')
    check_expanded_native_depth_inventory()
    check_native_depth_review('noaa-regular-native-depth-review.json',
                              'california-original-regular-native-depth-review')
    check_central_sediment_context()
    check_usgs_morro_report_datum()
    check_usgs_bathy_accuracy_statewide()
    check_h11876_sidescan_context()
    print("Website entrypoints, asset references, vendor hashes, GPX, and canonical data copies passed.")


if __name__ == "__main__":
    main()
