"""F31-07: synthetic evidence passed through the inventory and its report."""

import pytest

from research.scripts import inventory_coast_seafloor as inventory


def grid(family, area, source_id='synthetic'):
    return {
        'family': family, 'id': source_id, 'name': source_id, 'resolution_m': 2.0,
        'depth': 'confirmed' if area is None or area > 0 else 'none-shallow',
        'extent_km2': area,
    }


def sector(order, *evidence):
    sid = f'synthetic-{order}'
    measured = inventory.fig(0, 'MEASURED', 'synthetic fixture')
    return {
        'id': sid, 'name': f'Synthetic {order}', 'order': order, 'coast': 'north',
        'latitude': [0, 1],
        'shallow_0_300ft': inventory.shallow_block(sid, inventory.classify_shallow(evidence), evidence, [], None),
        'deeper_than_300ft': {
            'best_tier': 'none', 'best_resolution_m': None, 'best_source': 'none', 'sources': [],
        },
        'use_proxy': {'home_ports': measured, 'home_port_names': []},
        'review': {'status': 'partly-reviewed', 'native_files_read': measured, 'unread_or_open_items': []},
        'habitat': {
            'summary': 'none', 'cdfw_ds3091': {'predicted_hard_patches': measured},
            'usgs_csumb_classes': dict.fromkeys((
                'usgs_character_archives_catalogued', 'usgs_character_rasters_opened',
                'usgs_class_tables_verified', 'usgs_hard_context_outlines',
            ), measured),
        },
    }


def render(rows, gaps):
    summary = inventory.summarize(rows)
    summary['statewide_survey_catalog'] = dict.fromkeys(
        ('entries', 'native_inspected', 'catalog_or_metadata_only', 'usable_status'), {'value': 0},
    )
    return inventory.render_md({
        'generator': 'synthetic fixture', 'summary': summary, 'sectors': rows,
        'gap_list': gaps, 'definitions': {}, 'limits': [],
    })


def test_possibly_overlapping_records_are_neither_a_distinct_area_nor_a_rank_tiebreak():
    # The catalogs only carry figures; these two 1 km2 records could cover the same bottom.
    # Adding them would incorrectly rank the 1.5 km2 single-family sector ahead of this one.
    rows = [sector(2, grid('CSUMB', 1.5)), sector(1, grid('CSUMB', 1), grid('NOAA BAG', 1))]
    gaps = inventory.rank_gaps(rows)
    both_families = next(g for g in gaps if g['sector_id'] == 'synthetic-1')
    assert both_families['confirmed_2m_extent_km2'] is None
    assert [g['sector_id'] for g in gaps] == ['synthetic-1', 'synthetic-2']
    assert 'distinct 2 m shallow extent UNKNOWN' in gaps[0]['why']
    assert 'Synthetic 1: CSUMB (0-300 ft) 1 km2 (M), NOAA BAG (25-200 ft) 1 km2 (M)' in render(rows, gaps)


@pytest.mark.parametrize('records, expected', [
    ((), 'UNKNOWN'),
    ((grid('CSUMB', None),), 'UNKNOWN'),
    ((grid('CSUMB', 0),), '0 km2 (M)'),
    ((grid('CSUMB', 0.001),), '0.001 km2 (M)'),
])
def test_absent_family_figure_is_distinct_from_a_recorded_zero_or_small_positive(records, expected):
    # Empty sums and rounding must not invent a measured zero. The valid zero
    # belongs only to the measured family and cannot prove sector-wide absence.
    rows = [sector(1, *records)]
    gaps = inventory.rank_gaps(rows)
    if records and records[0]['extent_km2'] == 0:
        assert rows[0]['shallow_0_300ft']['best_tier'] == 'none'
    assert gaps[0]['confirmed_2m_extent_km2'] is None
    assert f'Synthetic 1: CSUMB (0-300 ft) {expected}, NOAA BAG (25-200 ft) UNKNOWN' in render(rows, gaps)
