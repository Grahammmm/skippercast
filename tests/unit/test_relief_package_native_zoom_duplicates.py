"""Validate native support summaries without generating any release layers."""

import pytest

from skippercast.relief import package


@pytest.fixture
def metadata():
    rights = {'public_display': 'allowed', 'license': 'public-domain'}
    sources = [
        {'id': sid, 'label': 'measured', 'attribution': 'Synthetic survey',
         'vertical_datum': 'NAVD88', 'survey_dates': ['2020'], 'rights_class': 'public', 'rights': rights}
        for sid in ('survey-a', 'survey-b')
    ]
    keys = [('survey-a', 2), ('survey-a', 5), ('survey-b', 2)]
    doc = {
        'region': 'synthetic-bay', 'bounds': [-122, 34, -121, 35], 'minzoom': 14, 'maxzoom': 15,
        'sources': sources,
        'detail_summary': {'mask': 'transparent-nodata', 'depth_bands': [
            {'source_id': sid, 'min_depth_m': 0, 'max_depth_m': 20, 'resolution_m': grid}
            for sid, grid in keys
        ]},
        'native_support_by_zoom': {
            str(z): {'tiles': 3, 'limit_m': 91.44, 'sources': [
                {'id': sid, 'resolution_m': grid, 'tiles': 2} for sid, grid in keys
            ]}
            for z in (14, 15)
        },
    }
    catalog = {'sources': [
        {'id': row['id'], 'rights': rights, 'review_status': 'approved'} for row in sources
    ]}
    return doc, package.pointer_schema(), catalog


def test_accepts_overlapping_native_summaries_with_distinct_keys_per_zoom(metadata):
    # A release-wide or single-field key would reject valid repeats; summing
    # row counts would reject overlapping footprints (2 + 2 + 2 tiles vs 3).
    package.validate_metadata(*metadata)


@pytest.mark.parametrize('tiles', [2, 3], ids=['equal-count', 'unequal-count'])
def test_rejects_duplicate_native_source_resolution_in_one_zoom(metadata, tiles):
    # The extra row fits the zoom's tile count and references a valid band.
    # Checking rows independently (or comparing whole rows) misses the conflict.
    doc, schema, catalog = metadata
    rows = doc['native_support_by_zoom']['15']['sources']
    rows.append({**rows[0], 'tiles': tiles})
    with pytest.raises(package.ReleaseError, match=r'duplicate native source summary.*z15'):
        package.validate_metadata(doc, schema, catalog)
