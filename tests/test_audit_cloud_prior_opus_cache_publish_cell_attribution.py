"""Audit repro: coverage-cell contributors never reach the published attribution.

seafloor.publish.build() computes `credits` (PMTiles attribution and the
manifest's source_attribution) only from habitat features' source_rights. The
`cells` layer of the same archive carries each cell's survey `source_id`
(e.g. a CSUMB noncommercial survey that requires a fixed credit), but those
sources are never passed through rights.source_rights / feature_rights, so a
ready bundle can publish CSUMB-derived coverage without the CSUMB credit and
without the for-profit refusal.
"""
import json
from datetime import datetime, timedelta, timezone

import pytest

from skippercast.seafloor import publish
from skippercast.seafloor.rights import CSUMB_CREDIT


def test_cell_layer_sources_are_credited(tmp_path, monkeypatch):
    now = datetime(2026, 10, 1, tzinfo=timezone.utc)
    (tmp_path / 'dist/data').mkdir(parents=True)
    (tmp_path / 'catalog').mkdir()
    (tmp_path / 'dist/data/seafloor-ledger.json').write_text(json.dumps(
        {'reaches': [], 'reference': {}}))
    (tmp_path / 'catalog/surveys.json').write_text(json.dumps({'surveys': [
        {'id': 'usgs-a', 'url': 'https://pubs.usgs.gov/a.tif'},
        {'id': 'csumb-b', 'url': 'https://data.ngdc.noaa.gov/platforms/ocean/ships/ventresca/b.tar.gz'}]}))
    usgs_rights = [{'source_id': 'usgs-a', 'attribution': 'USGS'}]
    habitat = {'type': 'Feature', 'geometry': {'type': 'Point', 'coordinates': [-121.9, 36.6]},
               'properties': {'status': 'habitat', 'exportable': True, 'source_ids': '["usgs-a"]',
                              'source_rights': json.dumps(usgs_rights)}}
    # Exactly what region_layers emits for a measured tier-1 cell from a CSUMB survey.
    cell = {'type': 'Feature', 'geometry': {'type': 'Point', 'coordinates': [-121.95, 36.55]},
            'properties': {'id': '3310:1:1', 'reach': 'r', 'tier': 1, 'source_id': 'csumb-b',
                           'reference_band': 'provisional', 'band_area_m2': 625,
                           'planning_notice': publish.NOTICE}}
    monkeypatch.setattr(publish, 'region_layers', lambda root, region, now=None: (
        {'cells': [cell], 'habitat': [habitat]}, {}, now + timedelta(days=30)))
    monkeypatch.setattr(publish, 'processing_scope', lambda root: 'all')
    seen = {}

    def fake_archive(tool, layers, output, *, title, attribution, description, precise):
        seen['attribution'] = attribution
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b'PMTiles\x03')
    import scripts.build_map_tiles as tiles
    monkeypatch.setattr(tiles, 'build_vector_archive', fake_archive)

    _, manifest = publish.build('central-coast', root=tmp_path, tool='tippecanoe', now=now)
    assert manifest['status'] == 'ready'
    # Correct behaviour: every survey contributing to a published layer is credited.
    assert CSUMB_CREDIT in manifest['source_attribution']
    assert CSUMB_CREDIT in seen['attribution']


import os as _audit_os  # noqa: E402

import pytest as _audit_pytest  # noqa: E402

pytestmark = _audit_pytest.mark.skipif(
    _audit_os.environ.get("SKIPPERCAST_AUDIT_CLOUD") != "1",
    reason="audit repro (fails on purpose): set SKIPPERCAST_AUDIT_CLOUD=1",
)
