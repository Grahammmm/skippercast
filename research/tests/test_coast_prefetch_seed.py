"""The committed-evidence seed must never pose as a complete campaign inventory."""
from pathlib import Path

from research.scripts.build_coast_prefetch_plan import BOUNDS, GAPS, build
from skippercast.coastal.prefetch import SEGMENTS, load_plan
from skippercast.http import Session
import json

ROOT = Path(__file__).resolve().parents[2]


def test_seed_has_campaign_order_and_explicit_gaps(tmp_path):
    seed = build(ROOT)
    assert tuple(BOUNDS) == SEGMENTS
    assert len(BOUNDS) == 22
    assert set(GAPS) <= {g['id'] for g in seed['unresolved']}
    assert seed['review_required'] is True
    assert len(seed['files']) == len({r['url'] for r in seed['files']})
    assert all(r['segments'] for r in seed['files'])
    assert [SEGMENTS.index(r['segments'][0]) for r in seed['files']] == sorted(SEGMENTS.index(r['segments'][0]) for r in seed['files'])
    path = tmp_path / 'plan.json'
    path.write_text(json.dumps(seed))
    assert len(load_plan(path, Session())['files']) == len(seed['files'])


def test_seed_carries_both_csmp_resolutions_sfml_and_vr():
    seed = build(ROOT)
    urls = {r['url'] for r in seed['files']}
    assert any('Bathymetry_2m_OffshoreMonterey.zip' in u for u in urls)
    assert any('Bathymetry_5m_OffshoreMonterey.zip' in u for u in urls)
    assert any('Cal_DIG_I_v2_Bathymetry.zip' in u for u in urls)
    assert any('H13089_MB_VR_MLLW.bag' in u for u in urls)
    assert any('_8m_MLLW_' in u for u in urls)
    for row in seed['files']:
        if row['source'] in ('csmp', 'csumb-sfml'):
            assert 'for-profit' in row['licence']
    for series, count in [('BSS_Block', 13), ('SCC_Block', 28)]:
        assert len({u for u in urls if series in u and 'additional_products' in u}) == count


def test_seed_generation_is_deterministic():
    assert build(ROOT) == build(ROOT)
