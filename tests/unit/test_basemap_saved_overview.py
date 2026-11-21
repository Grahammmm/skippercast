"""Saved low-zoom extraction coverage, independent of valid detail geometry."""
import pytest

from tests.unit.test_basemap_detail import _run_dir


@pytest.mark.parametrize('overview', [
    {},  # Missing bbox.
    {'bbox': [-10, 0, -5, 5]},  # Valid bbox, disjoint from the detail boxes.
    {'bbox': [-125, 30, -114]},
    {'bbox': {'w': -125, 's': 30, 'e': -114, 'n': 43}},
    {'bbox': ['-125', 30, -114, 43]},
    {'bbox': [-125, False, -114, 43]},
    {'bbox': [-125, 30, -114, float('nan')]},
    {'bbox': [-125, 30, -114, float('inf')]},
    {'bbox': [-125, 30, -114, 10**400]},
    {'bbox': [-181, 30, -114, 43]},
    {'bbox': [-114, 30, -125, 43]},
])
def test_saved_plan_refuses_bad_overview_bbox(tmp_path, overview):
    # The previous checker accepted these plans because only the overview zoom mattered.
    result = _run_dir(tmp_path, lambda plan: {**plan, 'overview': {'maxzoom': 10, **overview}})
    assert result.returncode == 1 and result.stdout == ''
    assert result.stderr.startswith('FAIL: ') and 'overview.bbox' in result.stderr
    assert 'Traceback' not in result.stderr


@pytest.mark.parametrize('trim_edge', [None, 0, 1, 2, 3], ids=['exact', 'west', 'south', 'east', 'north'])
def test_saved_plan_requires_full_coverage_on_every_edge(tmp_path, trim_edge):
    # An exact fit needs no padding, but overlap alone must not qualify as coverage.
    def change_overview(plan):
        bbox = [bound(box['bbox'][i] for box in plan['regions'])
                for i, bound in enumerate((min, min, max, max))]
        if trim_edge is not None:
            bbox[trim_edge] += 0.01 if trim_edge < 2 else -0.01
        plan['overview']['bbox'] = bbox
        return plan

    result = _run_dir(tmp_path, change_overview)
    if trim_edge is None:
        assert result.returncode == 0, result.stderr
    else:
        assert result.returncode == 1 and result.stdout == ''
        assert result.stderr.startswith('FAIL: ') and 'overview.bbox' in result.stderr
