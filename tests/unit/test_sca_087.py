"""Replay the named-ground compiler on fictional landing rows and a synthetic grid."""
import json
import sys
from collections import Counter

import pytest

from research.scripts.collect_charter_reports import parse_page


@pytest.mark.gis
def test_named_ground_build_counts_distinct_facts_not_day_links(tmp_path, monkeypatch):
    import numpy as np
    import rasterio
    from pyproj import Transformer
    from rasterio.transform import from_origin
    from shapely.geometry import Point, mapping

    from research.scripts import build_charter_grounds as builder

    day = '2001-01-01'
    source = 'https://example.invalid/day'

    def row(trip, catch, boat='Fixture Boat', ground='Fixture Ground'):
        return (f'<tr><td><b>{boat}</b> Avila Beach, CA</td>'
                f'<td>{trip} <i>{ground}</i></td><td>{catch}</td></tr>')

    morning = row('Morning', '2 Rockfish')
    rows = parse_page(day, 'January 1, 2001' + ''.join([
        morning, row('Morning', '2   Rockfish'),  # normalized repeat
        row('Afternoon', '2 Rockfish'),  # only trip differs
        row('Morning', '3 Rockfish'),  # only reported catch differs
        row('Afternoon', '1 Lingcod'),
        row('Morning', '1 Lingcod', 'Control Boat'),
        row('Morning', '1 Lingcod', 'Control Boat', 'Other Ground'),
    ]), source)

    research_data = tmp_path / 'data'
    research_data.mkdir()
    sink = tmp_path / 'dist/data'
    sink.mkdir(parents=True)
    grid = tmp_path / 'synthetic.tif'
    with rasterio.open(grid, 'w', driver='GTiff', width=70, height=70, count=1,
                       dtype='float32', crs='EPSG:32610',
                       transform=from_origin(500000, 4000700, 10, 10)) as ds:
        ds.write(np.full((70, 70), -20, dtype='float32'), 1)
    geo = Transformer.from_crs(32610, 4326, always_xy=True).transform
    anchor = geo(500350, 4000350)
    closed = {'features': [{'geometry': mapping(Point(*geo(510000, 4010000)))}]}
    (research_data / 'closed-area-screen.geojson').write_text(json.dumps(closed))
    (research_data / 'candidate-pool.json').write_text(json.dumps({'sources': [{
        'key': 'fixture', 'analysis_file': grid.name, 'bath': str(grid),
        'survey_year': 2000, 'source_url': 'https://example.invalid/survey',
    }]}))
    (sink / 'atlas.json').write_text('{"targets": []}')
    definition = {'label': 'Fixture Ground', 'source_id': 'fixture', 'anchor': anchor,
                  'radius_nm': 1, 'anchor_source': 'https://example.invalid/bounds'}
    monkeypatch.setattr(builder, 'DEFINITIONS', [definition, dict(definition, label='Other Ground')])
    monkeypatch.setattr(builder, 'ROOT', tmp_path)
    monkeypatch.setattr(sys, 'argv', ['build_charter_grounds.py', str(tmp_path), str(tmp_path)])

    def build(records):
        coverage = [{'date': day, 'status': 'ok', 'records': records}]
        (tmp_path / 'trip-facts.json').write_text(json.dumps({'coverage': coverage, 'records': records}))
        builder.main()
        return json.loads((sink / 'charter-grounds.json').read_text())

    forward = build(rows)
    ground = forward['grounds'][0]
    assert ground['report_count'] == 5
    assert Counter((r['boat'], tuple(r['species'])) for r in ground['reports']) == {
        ('Fixture Boat', ('rockfish',)): 3,
        ('Fixture Boat', ('lingcod',)): 1,
        ('Control Boat', ('lingcod',)): 1,
    }
    assert {r['source_url'] for r in ground['reports']} == {source}
    assert forward['coverage']['local_trips'] == 6
    assert forward['coverage']['ground_counts'] == {'Fixture Ground': 5, 'Other Ground': 1}
    assert forward['coverage']['mapped_single_ground_trips'] == 6
    assert forward['coverage']['pages'][0]['local_trip_count'] == 6
    assert ground['shared_source_groups'] == 1
    assert 'cannot establish' in ' '.join(forward['limitations'])
    assert build(list(reversed(rows))) == forward
