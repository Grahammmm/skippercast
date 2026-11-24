"""Saved low-zoom extraction coverage, independent of valid detail geometry."""
from datetime import datetime, timezone
import json
import shutil
import subprocess
import sys

import pytest

from scripts.basemap import regions
from tests._support import ROOT
from tests.unit.test_basemap_detail import _manifest_summary, _run_dir
from tests.unit.test_basemap_regions import LISTING


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


@pytest.mark.parametrize(('case', 'error'), [
    pytest.param('padded', None, id='padded'),
    pytest.param('touch', None, id='touch'),
    pytest.param('clipped', 'overview.bbox does not contain indexed region central-fixture', id='clipped'),
    pytest.param('outside-domain', 'overview.bbox must have finite, ordered coordinates within bounds',
                 id='outside-domain'),
])
def test_saved_pointer_requires_overview_coverage(tmp_path, case, error):
    # Run the real CLI against a tiny offline index where trimming just one
    # overview edge clips Central without losing any detail coverage.
    scripts = tmp_path / 'scripts' / 'basemap'
    scripts.mkdir(parents=True)
    for name in ('check_detail.py', 'regions.py'):
        shutil.copyfile(ROOT / 'scripts' / 'basemap' / name, scripts / name)
    minute = 1 / 60
    for region_id, status, (west, south) in (
        ('central-fixture', 'preview', (-122, 36)),
        ('north-fixture', 'active', (-123, 39)),
    ):
        path = tmp_path / 'regions' / region_id / 'region.json'
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({'id': region_id, 'status': status,
                                    'bounds': [west, south, west + minute, south + minute]}))

    plan = regions.plan('20261008', LISTING, root=tmp_path)
    archive = tmp_path / plan['key'].rsplit('/', 1)[-1]
    archive.write_bytes(b'0' * 1024)  # The footprint check does not read tile bytes.
    document = regions.manifest(plan, archive, 1, now=datetime(2026, 10, 8, tzinfo=timezone.utc))
    bbox = document['overview']['bbox']
    central_east = -122 + minute
    if case == 'touch':
        bbox[2] = central_east
    elif case == 'clipped':
        bbox[2] = central_east - minute / 2
    elif case == 'outside-domain':
        bbox[0] = -181
    pointer = tmp_path / 'pointer.json'
    pointer.write_text(json.dumps(document))

    result = subprocess.run([sys.executable, '-B', str(scripts / 'check_detail.py'),
                             '--manifest', str(pointer)], capture_output=True, text=True)
    if error is None:
        expected = ('PASS central-fixture: inside manifest detail box central-fixture\n'
                    'PASS north-fixture: inside manifest detail box north-fixture\n'
                    + _manifest_summary(2))
        assert (result.returncode, result.stdout, result.stderr) == (0, expected, '')
    else:
        assert (result.returncode, result.stdout, result.stderr) == (1, '', f'FAIL: pointer.json: {error}\n')
