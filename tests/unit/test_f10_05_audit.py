"""A map point is not evidence of a qualified fishing target (F10-05)."""
from datetime import datetime, timezone
import hashlib

import pytest

from skippercast import validate
from skippercast.platform import build, contracts
from tests._support import FIXTURES

DATE = '2025-01-01'
REGION = 'synthetic-region'
ASSETS = {key: f'regions/{REGION}/{key}.json' for key in ('atlas', 'habitats', 'bottom_index')}
AFFIRMATIVE = {'depth_qualified': True, 'vertical_datum': 'MLLW',
               'fishing_target': True, 'fishing_export': True}


@pytest.mark.parametrize(('flags', 'depth', 'qualified'), [
    pytest.param({}, [30, 60], 0, id='missing-evidence'),
    pytest.param({**AFFIRMATIVE, 'research_only': True}, [30, 60], 0, id='research-only-veto'),
    pytest.param({**AFFIRMATIVE, 'fishing_target': False}, [30, 60], 0, id='not-a-fishing-target'),
    pytest.param({**AFFIRMATIVE, 'vertical_datum': 'unknown'}, [30, 60], 0, id='unverified-datum'),
    pytest.param(AFFIRMATIVE, [60, 30], 0, id='reversed-depths'),
    pytest.param(AFFIRMATIVE, [0, 60], 0, id='nonpositive-depth'),
    pytest.param(AFFIRMATIVE, [200, 240], 0, id='unreviewed-deeper-depth'),
    pytest.param(AFFIRMATIVE, [30, 60], 1, id='qualified-mllw'),
    pytest.param({**AFFIRMATIVE, 'depth_qualification': {'status': 'reviewed'}},
                 [200, 240], 1, id='reviewed-deeper-depth'),
])
def test_region_and_sector_readiness_count_only_affirmative_targets(tmp_path, monkeypatch, flags, depth, qualified):
    # Reuse the synthetic readiness input closure; exercise the real regional,
    # sector and readiness projections. Stub unrelated publication inputs only.
    inputs = contracts.read_json(FIXTURES / 'sp1701_readiness_spacing/root-inputs.json')
    bands = [dict(id=row['id'], name=row['name'], coast='synthetic', latitude=[i, i + 1])
             for i, row in enumerate(inputs.pop('dist/data/coastal-sectors.json')['sectors'])]
    bounds = [0, 0, 2, 1]
    region = dict(id=REGION, name='Synthetic region', status='preview', assets=ASSETS,
                  bounds=bounds, fishing_bounds=bounds, boat={'bottom_depth_limit_ft': 300},
                  species=[], coverage_note='Synthetic control')
    report = dict(schema_version=1, region_id=REGION, region_name=region['name'], needs=[],
                  capabilities={'surveyed-bottom-targets': {'ready': True, 'gaps': []}},
                  note='Synthetic control')
    inputs.update({
        f'regions/{REGION}/region.json': region,
        f'dist/{ASSETS["atlas"]}': dict(fishing_depth_limit_ft=300, targets=[
            dict(id='point', latitude=0.5, longitude=1, neighborhood_depth_ft=depth, **flags)]),
        f'dist/{ASSETS["bottom_index"]}': {'views': {}},
        'catalog/targets.json': {'targets': {}},
        'catalog/coasts.json': {'regions': [dict(id='synthetic', packages=[REGION], latitude=[0, len(bands)],
                                                bounds=[0, 0, 2, len(bands)], rules_url='https://example.invalid/rules')]},
        'catalog/coastal-sectors.json': dict(schema_version=1, reviewed_at=DATE, scope='synthetic',
                                            survey_feed_url='https://example.invalid/surveys',
                                            survey_product_feed_url='https://example.invalid/products',
                                            survey_discovery=[], sectors=bands),
    })
    for relative, packet in inputs.items():
        contracts.atomic_json(tmp_path / relative, packet)
    for output, field, source in (
        ('dist/data/nbs-hard-footprint-depth-audit.json',
         'inventory_sha256', 'dist/data/nbs-hard-footprint-tile-inventory.json'),
        ('dist/data/nbs-hard-footprint-original-class-overlap.json',
         'depth_audit_sha256', 'dist/data/nbs-hard-footprint-depth-audit.json'),
        ('dist/data/usgs-ds781-character-semantics.json',
         'source_native_audit_sha256', 'dist/data/usgs-ds781-native-character-review.json'),
        ('dist/data/usgs-ds781-character-semantics.json',
         'source_metadata_inventory_sha256', 'catalog/usgs-ds781-metadata-review.json'),
    ):
        path = tmp_path / output
        packet = contracts.read_json(path)
        packet[field] = hashlib.sha256((tmp_path / source).read_bytes()).hexdigest()
        contracts.atomic_json(path, packet)

    monkeypatch.setattr(build, 'load_region', lambda *_: dict(region))
    monkeypatch.setattr(build, 'load_catalogs', lambda *_: ({}, {}))
    monkeypatch.setattr(build, 'requirement_report', lambda *_: report)
    for name in ('validate_regional_rules', 'publish_shoreline', 'publish_depth_contours',
                 'publish_startup_forms', 'publish_land_water', 'compile_launch_points',
                 'compile_shore_habitat', 'compile_coasts'):
        monkeypatch.setattr(build, name, lambda *_: None)
    monkeypatch.setattr(build, 'atomic_json', lambda path, value, *, kind=None:
                        contracts.atomic_json(path, value, kind=kind if kind == 'coverage' else None))

    atlas_path = tmp_path / 'dist' / ASSETS['atlas']
    atlas_before = atlas_path.read_bytes()
    build.build(tmp_path, now=datetime(2025, 1, 1, tzinfo=timezone.utc))
    assert atlas_path.read_bytes() == atlas_before
    coverage = contracts.read_json(tmp_path / f'dist/regions/{REGION}/coverage.json')
    sector = contracts.read_json(tmp_path / 'dist/data/coastal-sectors.json')['sectors'][0]
    readiness = contracts.read_json(tmp_path / 'dist/data/california-atlas-readiness.json')['sectors'][0]
    assert (coverage['qualified_bottom_views'], readiness['status']) == (
        qualified, 'partial-local-targets' if qualified else 'source-review-only')
    assert (coverage['published_targets'], coverage['published_research_candidates'],
            coverage['qualified_fishing_targets']) == (1, 1 - qualified, qualified)
    assert (sector['published_candidate_points'], sector['published_research_candidates'],
            sector['qualified_fishing_targets']) == (1, 1 - qualified, qualified)
    assert (readiness['published_candidate_points_in_band'], readiness['published_research_candidates_in_band'],
            readiness['qualified_fishing_targets_in_band']) == (1, 1 - qualified, qualified)
    assert not validate.validator('coverage').is_valid(dict(coverage, unexpected=True))
