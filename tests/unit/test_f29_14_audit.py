"""F29-14: reserve display overlap only for an emitted native context outline."""
import pytest

pytestmark = pytest.mark.gis


@pytest.fixture
def compile_outlines(monkeypatch):
    from shapely.geometry import box, mapping

    from research.scripts import build_native_hard_context as compiler

    # Synthetic planar metres, not real locations. Leave the actual clipping,
    # overlap subtraction, inward buffer and output assembly in the compiler.
    def identity(x, y):
        return x, y

    monkeypatch.setattr(compiler, 'TO_METERS', identity)
    monkeypatch.setattr(compiler, 'TO_WGS84', identity)
    monkeypatch.setattr(compiler, 'mpa_union', lambda _: box(-210, 0, -110, 60))
    monkeypatch.setattr(compiler, 'federal_union', lambda _: box(170, 0, 270, 60))

    def compile_features(outlines):
        reviews = {}
        rows = []
        for ident, bounds in outlines.items():
            receipts = dict(survey_id=ident, noaa_bag_sha256='a' * 64,
                            survey_report_sha256='b' * 64, usgs_sources=[])
            rows.append(dict(receipts, counts={'retained_components': 1}))
            reviews[ident] = dict(
                receipts, scope='native-noaa-usgs-hard-bottom-review', maximum_planning_depth_ft=200,
                native_resolution_m=2, survey_dates=['2000-01-01'],
                noaa_bag_url='https://example.invalid/bag', survey_report_url='https://example.invalid/report',
                features=[{'geometry': mapping(box(*bounds)), 'properties': {
                    'fishing_target': False, 'exportable': False, 'legal_clearance': False, 'fish_confirmed': False,
                    'component': 1, 'depth_ft_range': [50, 100], 'max_product_uncertainty_m': 1,
                }}],
            )
        return compiler.compile_context(
            reviews, {'scope': 'native-noaa-usgs-review-summary', 'surveys': rows},
            {'sources': {'mpas': {'data_retrieved_at': '2000-01-01T00:00:00Z'}}},
            {'retrieved_at': '2000-01-01T00:00:00Z'}, expected=set(reviews),
        )['features']

    return compile_features


def test_eroded_outline_does_not_reserve_later_survey_area(compile_outlines):
    from shapely.geometry import box, shape

    # The strip passes the 2,500 m² gate but cannot survive a 7.5 m inset.
    # Subtracting its 12 m band from the later rectangle would leave 2,280 m².
    first = (24, -100, 36, 150)
    later = (10, 0, 60, 60)
    features = compile_outlines({'A': first, 'B': later})
    assert [feature['properties']['survey_id'] for feature in features] == ['B']
    assert shape(features[0]['geometry']).equals(box(17.5, 7.5, 52.5, 52.5))


def test_emitted_outline_retains_overlap_dedup_and_context_labels(compile_outlines):
    from shapely.geometry import box, shape

    # A drawable survey claims the overlap; both synthetic closure buffers
    # still cut this wide input, and the feature remains context only.
    bounds = (-30, 0, 90, 60)
    features = compile_outlines({'A': bounds, 'B': bounds})
    assert [feature['properties']['survey_id'] for feature in features] == ['A']
    assert shape(features[0]['geometry']).equals(box(-2.5, 7.5, 62.5, 52.5))
    for label in ('fishing_target', 'exportable', 'legal_clearance', 'fish_confirmed', 'depth_qualified_for_target'):
        assert features[0]['properties'][label] is False
