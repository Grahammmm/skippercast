"""F31-08: a variable-resolution range does not establish its lower endpoint."""

import json

import pytest

from research.scripts import inventory_coast_seafloor as inventory


@pytest.mark.parametrize('exact_m', [None, 2, 1], ids=['range-only', 'exact-2m', 'exact-1m'])
def test_inventory_reports_vr_range_separately_from_exact_grid(tmp_path, monkeypatch, exact_m):
    # Exercise both NOAA adapters and both output formats. Treating the VR lower
    # endpoint as observed would invent 1 m spacing or override the actual 2 m grid.
    sid = 'synthetic'
    sector = {'id': sid, 'name': 'Synthetic sector', 'coast': 'north', 'latitude': [0, 1]}
    readiness = {'sector_id': sid, 'bounds': [0, 0, 1, 1], 'original_bag_bbox_leads': 0,
                 'usgs_ds781_map_area_leads': [], 'published_candidate_points_in_band': 0}
    bag = {'survey_id': 'synthetic-vr', 'bag_url': 'synthetic-vr.bag', 'sectors': {
        sid: {'depth_uncertainty_eligible_cells': 10, 'measured_native_cells': 10},
    }}
    regular = [] if exact_m is None else [dict(bag, survey_id='synthetic-regular',
                                              bag_url='synthetic-regular.bag', status='ok',
                                              native_resolution_m=[exact_m, exact_m])]
    inputs = {
        'sectors': {'sectors': [sector]}, 'readiness': {'sectors': [readiness]},
        'ledger': {'reaches': []}, 'reaches': {'reaches': []}, 'surveys': {'surveys': []},
        'usgs_bathy': {'sources': [], 'sectors': []}, 'usgs_meta': {'records': []},
        'usgs_char': {'products': [], 'sectors': []}, 'ports': {'ports': []},
        'noaa_regular': {'files': regular}, 'noaa_vr': {'files': [bag], 'sectors': [
            {'sector_id': sid, 'source_files_with_eligible_cells': 1},
        ]},
        'bluetopo': {'tiles': [], 'sector_tile_ids': {}},
        'em300': {'sector_ids': []}, 'caldig': {'sector_ids': []},
        'gebco': {'name': 'synthetic fallback', 'spatial': {'resolution_m': 100}},
    }
    for key, relative_path in inventory.INPUTS.items():
        path = tmp_path / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(inputs[key]), encoding='utf-8')
    out_json, out_md = tmp_path / 'inventory.json', tmp_path / 'inventory.md'
    monkeypatch.setattr(inventory, 'ROOT', tmp_path)
    monkeypatch.setattr(inventory, 'OUT_JSON', out_json)
    monkeypatch.setattr(inventory, 'OUT_MD', out_md)
    assert inventory.main([]) == 0

    result = json.loads(out_json.read_text(encoding='utf-8'))
    shallow = result['sectors'][0]['shallow_0_300ft']
    exact = shallow['finest_grid_any_depth_m']
    expected_label = 'UNKNOWN' if exact_m is None else 'MEASURED'
    assert (exact['value'], exact['label']) == (exact_m, expected_label)
    assert shallow['grid_spacing_ranges_m'] == [[1, 4]]
    tier = '5 m' if exact_m is None else '2 m'
    assert shallow['best_tier'] == tier
    assert shallow['tier_uncertain'] is (exact_m is None)
    assert shallow['best_confirmed_resolution_m']['value'] == exact_m
    assert result['summary']['finest_grid_any_depth_counts'][tier]['value'] == 1

    markdown = out_md.read_text(encoding='utf-8')
    exact_text = 'UNKNOWN' if exact_m is None else f'{exact_m} m (M)'
    table_row = next(line for line in markdown.splitlines() if line.startswith('| 1 | Synthetic sector |'))
    assert table_row.split('|')[4].strip() == f'{exact_text}; reported range: 1-4 m'
    assert f'finest exact spacing at any depth {exact_text}; reported range: 1-4 m;' in markdown
