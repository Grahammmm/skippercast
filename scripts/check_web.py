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


def main():
    assert (WEB / "index.html").is_file()
    readiness = json.loads((WEB / 'data/california-atlas-readiness.json').read_text())
    sectors = json.loads((WEB / 'data/coastal-sectors.json').read_text())['sectors']
    assert len(readiness['sectors']) == len(sectors) == 19
    assert {row['sector_id'] for row in readiness['sectors']} == {row['id'] for row in sectors}
    assert all(row['status'] in {'source-review-only', 'partial-local-targets'}
               and row['remaining_promotion_gates'] for row in readiness['sectors'])
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
    check_native_depth_review('noaa-regular-native-depth-review.json',
                              'california-original-regular-native-depth-review')
    check_central_sediment_context()
    print("Website entrypoints, asset references, vendor hashes, GPX, and canonical data copies passed.")


if __name__ == "__main__":
    main()
