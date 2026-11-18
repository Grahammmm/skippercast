"""F07-15: local discovery reports a raster without a CRS as unevaluated, never as examined.

Contract: ``complete_within_supplied_catalog`` is true only when every supplied candidate had its
intersection tested; unknown-CRS candidates are counted and named, and a no-lead result caused by
them carries a distinct hold. Believable bug: the unknown-CRS ``continue`` skips the candidate
silently and the receipt still says complete, so "no overlap" and "could not tell" look identical.
Everything is a tiny synthetic local raster; no network, no real catalog.
"""
import json

import pytest

from skippercast.coastal import stage_cli
from skippercast.coastal.handoff.common import digest, ref, write
from tests._support import NOW

np = pytest.importorskip("numpy")
rasterio = pytest.importorskip("rasterio")
pytest.importorskip("pyproj")
pytest.importorskip("shapely")
from rasterio.transform import from_origin  # noqa: E402

SEGMENT_BBOX = [-120.0, 35.0, -119.9, 35.1]
UNKNOWN_HOLD = 'no_local_leads_unknown_crs_candidates_unevaluated'
EXAMINED_HOLD = 'no_local_leads_external_catalogs_unexamined'


def raster(root, name, *, west, crs):
    path = root / 'sources' / name
    path.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(path, 'w', driver='GTiff', width=4, height=4, count=1, dtype='float32',
                       crs=crs, transform=from_origin(west, 35.08, 0.01, 0.01)) as ds:
        ds.write(np.full((1, 4, 4), -20.0, dtype='float32'))
    return dict(source=ref(root, path, 'native-raster-v1'), window=[0, 0, 4, 4])


def discover(root, candidates):
    plan = dict(schema='coastal-local-discovery-plan-v1', synthetic=True, segment_id='seg-1',
                candidates=candidates)
    write(root / 'plan.json', plan)
    reference = ref(root, root / 'plan.json', plan['schema'])
    job = dict(root=str(root), stage='discover', job_id='synthetic-job',
               segment=dict(segment_id='seg-1', synthetic=True, bbox_crs84=SEGMENT_BBOX),
               lease_token='synthetic-token', code_sha='a' * 64, deps_sha='b' * 64, params={},
               params_sha=digest({}), input_manifest=reference, input_manifest_sha=reference['sha256'],
               budget=dict(wall_s=60, bytes=1000000, requests=0), deadline_utc=32503680000.0)
    result = stage_cli.execute(job, 'out', now=NOW)
    return result, json.loads((root / 'out' / 'discovery.json').read_text())


def test_missing_crs_only_catalog_is_unevaluated_and_held(tmp_path):
    result, receipt = discover(tmp_path, [raster(tmp_path, 'nocrs.tif', west=-119.98, crs=None)])
    assert (receipt['candidates_attempted'], receipt['candidates_evaluated'],
            receipt['candidates_unknown_crs']) == (1, 0, 1)
    assert receipt['complete_within_supplied_catalog'] is False
    assert receipt['unexamined_external_catalogs'] is True and receipt['leads'] == []
    assert len(receipt['unknown_crs_sources']) == 1
    assert result['state'] == 'held' and result['holds'] == [UNKNOWN_HOLD]
    assert 'next_job' not in result


def test_fully_examined_disjoint_catalog_states_no_local_overlap(tmp_path):
    result, receipt = discover(tmp_path, [raster(tmp_path, 'far.tif', west=-110.0, crs='EPSG:4326')])
    assert (receipt['candidates_attempted'], receipt['candidates_evaluated'],
            receipt['candidates_unknown_crs']) == (1, 1, 0)
    assert receipt['complete_within_supplied_catalog'] is True and receipt['unknown_crs_sources'] == []
    assert result['state'] == 'held' and result['holds'] == [EXAMINED_HOLD]


def test_lead_is_kept_but_unknown_crs_candidate_still_marks_catalog_incomplete(tmp_path):
    near = raster(tmp_path, 'near.tif', west=-119.98, crs='EPSG:4326')
    result, receipt = discover(tmp_path, [raster(tmp_path, 'nocrs.tif', west=-119.98, crs=None), near])
    assert (receipt['candidates_attempted'], receipt['candidates_evaluated'],
            receipt['candidates_unknown_crs']) == (2, 1, 1)
    assert receipt['leads'] == [near] and receipt['complete_within_supplied_catalog'] is False
    assert result['state'] == 'done' and result['next_job']['stage'] == 'acquire'
