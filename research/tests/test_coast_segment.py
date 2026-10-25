"""Real S-020 cached synthetic acceptance. No stage doubles in positive tests.

The existing coordinator run/admission are synthetic COPY envelopes. Their held
window states remain unchanged: this tests composition, never coordinator success.
All writes, including pytest basetemp, must be under this candidate's out/ root.
"""
import copy
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import socket
import subprocess
import sys
import tempfile

import pytest

from research.lib.paths import ROOT as REPO
from research.scripts.coast_mvp import coast_segment as driver


@pytest.fixture
def area():
    out = REPO.parent / 'out'
    out.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='s020-acceptance-', dir=out) as value:
        yield Path(value)


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(driver.canonical(value))
    return sha256(path.read_bytes()).hexdigest()


def seal(case):
    case['kwargs']['recipe_sha256'] = save(case['input'] / 'recipe.json', case['recipe'])
    case['plan']['recipe_sha256'] = case['kwargs']['recipe_sha256']
    case['kwargs']['plan_sha256'] = save(case['input'] / 'plan.json', case['plan'])
    case['kwargs']['run_sha256'] = save(case['input'] / 'run.json', case['run'])
    return case


@pytest.fixture
def case(area):
    import rasterio
    import numpy as np
    from rasterio.transform import from_origin
    from rasterio.warp import transform_bounds
    inputs = area / 'frozen'
    inputs.mkdir()
    slug = 'santa-cruz-monterey-bay'
    # A bounded synthetic COPY of a real recipe: exact synthetic metadata bounds,
    # not a reduced claim about the real region. Source catalog identity retained.
    recipe = json.loads((REPO / f'regions/{slug}/coast.json').read_text())
    recipe['bbox'] = [-121.001, 35.001, -120.999, 35.003]
    metadata = inputs / 'metadata'
    for relative in ('schemas/coast-recipe-v1.schema.json', 'catalog/sources.json', 'catalog/coastal-sectors.json',
                     f'regions/{slug}/region.json'):
        dest = metadata / relative
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes((REPO / relative).read_bytes())
    region = json.loads((metadata / f'regions/{slug}/region.json').read_text())
    region['bounds'] = recipe['bbox']
    save(metadata / f'regions/{slug}/region.json', region)
    projected = transform_bounds('EPSG:4326', 'EPSG:3310', *recipe['bbox'], densify_pts=101)
    west, north = projected[0] - 200, projected[3] + 200
    grid = -10 - np.arange(64, dtype='float32')[None, :] * 0.5 + np.zeros((64, 1), dtype='float32')
    cache = inputs / 'cache/source.tif'
    cache.parent.mkdir()
    with rasterio.open(cache, 'w', driver='GTiff', width=64, height=64, count=1, dtype='float32',
                       crs='EPSG:3310', transform=from_origin(west, north, 10, 10), nodata=-999999) as dst:
        dst.write(grid, 1)
    root_id = 'queue:synthetic'
    cache_ref = driver.ref(inputs, cache, root_id)
    run = json.loads((REPO / 'tests/fixtures/coast/queue/valid/run-summary.json').read_text())
    admission = json.loads((REPO / 'tests/fixtures/coast/queue/valid/admission.json').read_text())
    head = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=REPO, text=True, capture_output=True, check=True).stdout.strip()
    for doc in (run, admission):
        doc['code_commit'] = head
        doc['author_model'] = 'gpt-6.1-sol'
        doc['author_profile'] = 'sol-reviewer'
        doc['card_id'] = 't_2773af86'
    admission['sources'][0]['hot_cache'] = [cache_ref]
    admission_path = inputs / 'admission.json'
    save(admission_path, admission)
    run['admission'] = driver.ref(inputs, admission_path, root_id)
    rights = dict(license='Owned synthetic test fixture; no external data rights claim',
                  terms_url='https://example.invalid/synthetic-terms', attribution='Synthetic analytical grid', csumb_involved=False)
    plan = dict(schema='s020-synthetic-cached-plan-v1', synthetic_only=True, fetch=False, sources=[dict(
        source_id=admission['sources'][0]['source_id'], catalog_id='noaa-bag', cache=cache_ref,
        datum='unknown', resolution_m=10, source_url='https://example.invalid/synthetic-grid', rights=rights)])
    result = dict(input=inputs, recipe=recipe, plan=plan, run=run, admission=admission,
                  kwargs=dict(workspace=area / 'first', admitted_root=area, code_commit=head, reserve_gib=0))
    return seal(result)


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def refused(*args, **kwargs):
        raise AssertionError('network call reached from offline composition')
    class OfflineSocket(socket.socket):
        def __new__(cls, *args, **kwargs):
            return refused(*args, **kwargs)
    monkeypatch.setattr(socket, 'socket', OfflineSocket)
    monkeypatch.setattr(socket, 'create_connection', refused)


def run(case, **changes):
    return driver.run_segment(case['input'], **(case['kwargs'] | changes))


def test_real_end_to_end_validated_and_deterministic_across_output_roots(case, area):
    first = run(case)
    second = run(case, workspace=area / 'second')
    a, b = first['receipt'], second['receipt']
    assert a['determinism_digest'] == b['determinism_digest']
    assert driver.receipt_api.content_identity(a) == driver.receipt_api.content_identity(b)
    assert first['validation'] == dict(status='REVIEW REQUIRED', structurally_valid=True,
        closed_verified=False, semantic_approval=False, publication_allowed=False)
    assert a['tier1']['vision_result'] == 'unavailable' and a['closed'] is False
    assert a['code_commit'] == case['kwargs']['code_commit']
    assert a['campaign_segment_id'] == case['run']['campaign_segment_id']
    assert a['coordinator_segment_id'] == case['run']['coordinator_segment_id']
    assert a['qa']['coverage_denominator'] > 0
    assert a['qa']['hole_numerator'] == 0
    assert a['recipe_sha256'] == case['kwargs']['recipe_sha256']
    assert {o['tool']['name'] for o in a['outputs']} == set(driver.STAGE_HASHES)
    root = case['kwargs']['workspace']
    assert json.loads((root / 'c2/manifest.json').read_text())['contour_features'] > 0
    assert 'SYNTHETIC FIXTURE ONLY' in (root / 'rights.html').read_text()
    for path in sorted((root / 'c1').glob('*.tif')):
        measured = driver.verify_cog(path)
        assert measured['format'] == 'COG' and measured['block_count'] > 0
    assert (root / 'run.json').read_bytes() == (case['input'] / 'run.json').read_bytes()
    assert json.loads((root / 'run.json').read_text())['partition']['held'] == case['run']['partition']['held']
    assert (root / 'receipt.json').exists()


def test_dry_run_reports_source_bytes_and_missing_cache_without_writes(case):
    before = sorted(case['input'].parent.rglob('*'))
    result = run(case, dry_run=True)
    assert sorted(case['input'].parent.rglob('*')) == before
    row = case['plan']['sources'][0]
    assert result['sources'] == [dict(source_id=row['source_id'], bytes=row['cache']['bytes'], cached=True, cache_need_bytes=0)]
    assert result['bytes'] == row['cache']['bytes'] and result['cache_need_bytes'] == 0
    (case['input'] / row['cache']['path']).rename(case['input'] / 'removed.tif')
    result = run(case, dry_run=True)
    assert result['cache_need_bytes'] == row['cache']['bytes']
    assert result['sources'][0]['cached'] is False
    assert not case['kwargs']['workspace'].exists()
    with pytest.raises(ValueError, match='missing cached sources'):
        run(case)


@pytest.mark.parametrize('target', ['workspace', 'input'])
def test_outside_root_refused(case, area, target):
    kwargs = {'workspace': area.parent / 'outside-never-write'} if target == 'workspace' else {}
    if target == 'input':
        case['input'] = area.parent
    with pytest.raises(ValueError, match='outside admitted root'):
        run(case, **kwargs)
    assert not (area.parent / 'outside-never-write').exists()


@pytest.mark.parametrize('target', ['input', 'workspace', 'cache', 'ancestor', 'metadata'])
def test_symlinks_refused_before_output(case, area, target):
    if target == 'input':
        alias = area / 'alias'
        alias.symlink_to(case['input'], target_is_directory=True)
        case['input'] = alias
    elif target == 'workspace':
        alias = area / 'alias'
        alias.symlink_to(area / 'missing', target_is_directory=True)
        case['kwargs']['workspace'] = alias
    elif target == 'cache':
        cached = case['input'] / case['plan']['sources'][0]['cache']['path']
        cached.rename(case['input'] / 'native.tif')
        cached.symlink_to(case['input'] / 'native.tif')
    elif target == 'metadata':
        original = case['input'] / 'metadata/catalog/sources.json'
        original.rename(case['input'] / 'catalog.json')
        original.symlink_to(case['input'] / 'catalog.json')
    else:
        alias = area / 'alias'
        alias.symlink_to(case['input'], target_is_directory=True)
        case['input'] = alias / '.'
    with pytest.raises(ValueError, match='symlink'):
        run(case)


@pytest.mark.parametrize('field', ['recipe_sha256', 'plan_sha256', 'run_sha256'])
def test_frozen_hash_drift_refused(case, field):
    with pytest.raises(ValueError, match='frozen input hash mismatch'):
        run(case, **{field: 'f' * 64})
    assert not case['kwargs']['workspace'].exists()


@pytest.mark.parametrize('change', ['fetch', 'real', 'unknown_catalog', 'rights', 'permission', 'datum', 'resolution', 'traversal', 'url', 'source_hash', 'cap'])
def test_negative_controls_fail_closed(case, change):
    row = case['plan']['sources'][0]
    matches = {
        'fetch': 'fetch must be off', 'real': 'only frozen synthetic',
        'unknown_catalog': 'catalog binding', 'rights': 'rights.license',
        'permission': 'rights permission unresolved', 'datum': 'datum binding',
        'resolution': 'resolution required', 'traversal': 'schema coast-admission-v1',
        'url': 'schema coast-admission-v1', 'source_hash': 'cache/admission binding', 'cap': 'synthetic cell cap',
    }
    if change == 'fetch': case['plan']['fetch'] = True
    if change == 'real': case['plan']['synthetic_only'] = False
    if change == 'unknown_catalog': row['catalog_id'] = 'unapproved-other-source'
    if change == 'rights': row['rights']['license'] = ''
    if change == 'permission': row['rights']['csumb_involved'] = True
    if change == 'datum': row['datum'] = 'MLLW'
    if change == 'resolution': row['resolution_m'] = 0
    if change in ('traversal', 'url', 'source_hash'):
        if change == 'traversal': row['cache']['path'] = '../outside.tif'
        if change == 'url': row['cache']['path'] = 'https://example.invalid/native.tif'
        if change == 'source_hash': row['cache']['sha256'] = 'f' * 64
        if change != 'source_hash':
            case['admission']['sources'][0]['hot_cache'] = [row['cache']]
            save(case['input'] / 'admission.json', case['admission'])
            case['run']['admission'] = driver.ref(case['input'], case['input'] / 'admission.json', 'queue:synthetic')
    if change == 'cap':
        case['recipe']['bbox'] = [-121.95, 34.95, -120.55, 35.85]
        path = case['input'] / 'metadata/regions/santa-cruz-monterey-bay/region.json'
        region = json.loads(path.read_text()); region['bounds'] = case['recipe']['bbox']; save(path, region)
    seal(case)
    with pytest.raises(ValueError, match=matches[change]):
        run(case)
    assert not case['kwargs']['workspace'].exists()


def test_plain_tiff_refused_even_with_tif_name(case):
    with pytest.raises(ValueError, match='non-COG layout'):
        driver.verify_cog(case['input'] / 'cache/source.tif')


def test_producer_non_cog_cannot_reach_receipt_acceptance(case, monkeypatch):
    real = driver.qualify_stages
    def changed():
        stages = real()
        mosaic = stages['coast_mosaic'].mosaic
        def noncog_after_producer_check(*args, **kwargs):
            from rasterio.shutil import copy as raster_copy
            result = mosaic(*args, **kwargs)
            target = Path(args[2]) / 'elevation.tif'
            # Producer already returned success; only the independent consumer
            # verifier can reject this mutation before receipt acceptance.
            plain = Path(args[2]) / 'plain-control.tif'
            raster_copy(target, plain, driver='GTiff')
            plain.replace(target)
            return result
        stages['coast_mosaic'].mosaic = noncog_after_producer_check
        return stages
    monkeypatch.setattr(driver, 'qualify_stages', changed)
    with pytest.raises(ValueError, match='not a COG|non-COG'):
        run(case)
    assert not (case['kwargs']['workspace'] / 'receipt.json').exists()


def test_receipt_corruption_rejected_by_real_validator(case):
    value = run(case)['receipt']
    root = case['kwargs']['workspace']
    resolver = driver.receipt_api.Resolver({'queue:synthetic': str(root)}, allowed_root_ids={'queue:synthetic'})
    target = root / value['outputs'][0]['artifact']['path']
    raw = target.read_bytes()
    target.write_bytes(raw[:-1] + bytes([raw[-1] ^ 1]))
    with pytest.raises(ValueError, match='SHA256/bytes mismatch'):
        driver.receipt_api.validate_receipt(value, resolver, root_id='queue:synthetic')


def test_stage_closure_contains_no_cli_children_and_reuses_exact_bytes():
    modules = driver.qualify_stages()
    assert set(modules) == set(driver.STAGE_HASHES)
    for name, module in modules.items():
        assert sha256(Path(module.__file__).read_bytes()).hexdigest() == driver.STAGE_HASHES[name]


def test_disguised_csumb_rights_remain_held(case):
    case['plan']['sources'][0]['rights']['attribution'] = 'CSUMB synthetic permission-negative'
    seal(case)
    with pytest.raises(ValueError, match='rights permission unresolved'):
        run(case)
    assert not case['kwargs']['workspace'].exists()


def test_no_overwrite_and_source_hash_refusal(case):
    run(case)
    receipt = (case['kwargs']['workspace'] / 'receipt.json').read_bytes()
    with pytest.raises(ValueError, match='fresh exclusive workspace'):
        run(case)
    assert (case['kwargs']['workspace'] / 'receipt.json').read_bytes() == receipt
    path = case['input'] / 'cache/source.tif'
    raw = path.read_bytes()
    path.write_bytes(raw[:-1] + bytes([raw[-1] ^ 1]))
    with pytest.raises(ValueError, match='SHA256/bytes mismatch'):
        run(case, workspace=case['kwargs']['workspace'].parent / 'different')


def test_independent_cog_negative_is_sensitive_to_disabling_only_verifier(case, area, monkeypatch):
    real = driver.qualify_stages
    def changed():
        stages = real()
        mosaic = stages['coast_mosaic'].mosaic
        def mutated(*args, **kwargs):
            from rasterio.shutil import copy as raster_copy
            result = mosaic(*args, **kwargs)
            target = Path(args[2]) / 'elevation.tif'
            plain = Path(args[2]) / 'plain-control.tif'
            raster_copy(target, plain, driver='GTiff')
            plain.replace(target)
            result['outputs']['elevation'].update(sha256=sha256(target.read_bytes()).hexdigest(), bytes=target.stat().st_size)
            return result
        stages['coast_mosaic'].mosaic = mutated
        return stages
    monkeypatch.setattr(driver, 'qualify_stages', changed)
    with pytest.raises(ValueError, match='non-COG layout'):
        run(case)
    monkeypatch.setattr(driver, 'verify_cog', lambda path: dict(format='synthetic-disabled-gate-control'))
    # Explicitly unqualified diagnostic result: proves the preceding negative
    # depends on THIS gate, not some unrelated metadata/producer prerequisite.
    result = run(case, workspace=area / 'gate-disabled-control')
    assert result['receipt']['closed'] is False
    assert result['validation']['semantic_approval'] is False


def test_native_offline_context_restores_peer_runtime_state():
    import pyproj.network
    original = pyproj.network.is_network_enabled()
    with driver.native_offline():
        assert pyproj.network.is_network_enabled() is False
    assert pyproj.network.is_network_enabled() == original


def test_cli_dry_run_is_same_cached_summary(case):
    result = driver.main(['--input-root', str(case['input']), '--workspace', str(case['kwargs']['workspace']),
        '--admitted-root', str(case['kwargs']['admitted_root']), '--recipe-sha256', case['kwargs']['recipe_sha256'],
        '--plan-sha256', case['kwargs']['plan_sha256'], '--run-sha256', case['kwargs']['run_sha256'],
        '--code-commit', case['kwargs']['code_commit'], '--dry-run'])
    assert result == 0
    assert not case['kwargs']['workspace'].exists()


# ---- S-026 resume, stage receipts and manifests (all names contain "resume") ----

def resume(case, **changes):
    return driver.resume_segment(case['input'], **(case['kwargs'] | changes))


def status(case, **changes):
    kwargs = {k: v for k, v in (case['kwargs'] | changes).items() if k not in ('dry_run', 'viewer')}
    return {row['stage']: row['status'] for row in driver.segment_status(case['input'], **kwargs)['stages']}


def tree(root, skip=()):
    return {p.relative_to(root).as_posix(): (sha256(p.read_bytes()).hexdigest(), p.stat().st_mtime_ns)
            for p in sorted(root.rglob('*')) if p.is_file() and p.relative_to(root).as_posix() not in skip}


def history(root):
    return (root / driver.HISTORY).read_bytes().splitlines(keepends=True)


def reseal_cache(case):
    inputs = case['input']
    cache_ref = driver.ref(inputs, inputs / 'cache/source.tif', 'queue:synthetic')
    case['admission']['sources'][0]['hot_cache'] = [cache_ref]
    save(inputs / 'admission.json', case['admission'])
    case['run']['admission'] = driver.ref(inputs, inputs / 'admission.json', 'queue:synthetic')
    case['plan']['sources'][0]['cache'] = cache_ref
    return seal(case)


ALL = list(driver.STAGES)


def test_resume_noop_rerun_preserves_digest_with_zero_stage_work(case):
    first = run(case)
    root = case['kwargs']['workspace']
    assert first['executed'] == ALL and first['reused'] == []
    before = tree(root, skip={driver.HISTORY})
    rows = history(root)
    second = resume(case)
    assert second['executed'] == [] and second['reused'] == ALL
    assert second['receipt']['determinism_digest'] == first['receipt']['determinism_digest']
    assert second['receipt'] == first['receipt']
    assert second['validation'] == first['validation']
    assert second['manifests']['archive_candidates'] == first['manifests']['archive_candidates']
    assert tree(root, skip={driver.HISTORY}) == before  # bytes AND mtimes: zero new stage work
    after = history(root)
    assert after[:len(rows)] == rows and len(after) == len(rows) + 1  # append-only
    row = json.loads(after[-1])
    assert row['executed'] == [] and row['reused'] == ALL and row['seq'] == 1
    assert row['previous_row_sha256'] == sha256(rows[-1]).hexdigest()
    assert set(status(case).values()) == {'complete'}


def test_resume_restart_after_interrupted_stage_matches_uninterrupted_digest(case, area, monkeypatch):
    crash = {'on': True}
    real = driver.qualify_stages
    def interrupted():
        stages = real()
        packet = stages['coast_qa'].packet
        def crashing(*args, **kwargs):
            result = packet(*args, **kwargs)  # outputs written, receipt never sealed
            if crash['on']:
                raise RuntimeError('simulated crash inside c4')
            return result
        stages['coast_qa'].packet = crashing
        return stages
    monkeypatch.setattr(driver, 'qualify_stages', interrupted)
    with pytest.raises(RuntimeError, match='simulated crash'):
        run(case)
    root = case['kwargs']['workspace']
    assert not (root / 'receipt.json').exists() and (root / 'c4/qa.json').exists()
    assert status(case) == dict(inputs='complete', c1='complete', c2='complete', c4='incomplete',
                                c5='blocked', receipt='blocked')
    kept = {stage: (root / f'stages/{stage}.json').read_bytes() for stage in ('inputs', 'c1', 'c2')}
    c1_before = tree(root / 'c1')
    residue = (root / 'c4/qa.json').read_bytes()
    crash['on'] = False
    resumed = resume(case)
    assert resumed['reused'] == ['inputs', 'c1', 'c2'] and resumed['executed'] == ['c4', 'c5', 'receipt']
    assert {stage: (root / f'stages/{stage}.json').read_bytes() for stage in kept} == kept
    assert tree(root / 'c1', skip={'qa-manifest.json'}) == {k: v for k, v in c1_before.items() if k != 'qa-manifest.json'}
    moved = [p for r in resumed['stages'] for p in r['quarantined']]
    assert any(p.endswith('/c4/c4') for p in moved)  # residue renamed aside, never deleted
    quarantined = next(root.glob('quarantine/*/c4/c4/qa.json'))
    assert quarantined.read_bytes() == residue
    fresh = run(case, workspace=area / 'fresh-uninterrupted')
    assert resumed['receipt']['determinism_digest'] == fresh['receipt']['determinism_digest']
    assert set(status(case).values()) == {'complete'}


@pytest.mark.parametrize('change', ['recipe', 'input', 'tool'])
def test_resume_refuses_stale_reuse_without_writing(case, monkeypatch, change):
    run(case)
    root = case['kwargs']['workspace']
    before = tree(root)
    expected = 'inputs'
    if change == 'recipe':
        case['recipe']['cache_budget_bytes'] -= 1
        seal(case)
    elif change == 'input':
        import numpy as np
        import rasterio
        path = case['input'] / 'cache/source.tif'
        with rasterio.open(path) as src:
            profile, grid = src.profile, src.read(1)
        with rasterio.open(path, 'w', **profile) as dst:
            dst.write((grid + np.float32(1)).astype('float32'), 1)
        reseal_cache(case)
    else:
        real = driver.tool_identity
        monkeypatch.setattr(driver, 'tool_identity',
                            lambda stage: real(stage) | ({'gdal': 'changed-tool'} if stage == 'c2' else {}))
        expected = 'c2'
    report = status(case)
    assert report[expected] == 'stale'
    assert all(report[s] == 'complete' for s in ALL[:ALL.index(expected)])
    assert all(report[s] == 'blocked' for s in ALL[ALL.index(expected) + 1:])
    with pytest.raises(ValueError, match='stale stage binding refused: ' + expected):
        resume(case)
    assert tree(root) == before


@pytest.mark.parametrize('how', ['flipped', 'missing'])
def test_resume_refuses_tampered_output(case, area, how):
    run(case)
    root = case['kwargs']['workspace']
    if how == 'flipped':
        target, stage = sorted(p for p in (root / 'c2').rglob('*') if p.is_file())[0], 'c2'
        raw = target.read_bytes()
        target.write_bytes(raw[:-1] + bytes([raw[-1] ^ 1]))
    else:
        target, stage = root / 'c4/qa.json', 'c4'
        target.rename(area / 'moved-aside-qa.json')
    before = tree(root)
    report = status(case)
    assert report[stage] == 'tampered'
    assert all(report[s] == 'blocked' for s in ALL[ALL.index(stage) + 1:])
    with pytest.raises(ValueError, match='tampered stage output refused: ' + stage):
        resume(case)
    assert tree(root) == before


@pytest.mark.parametrize('how', ['truncated', 'forged', 'empty'])
def test_resume_partial_stage_receipt_never_marks_complete(case, how):
    first = run(case)
    root = case['kwargs']['workspace']
    path = root / 'stages/c4.json'
    raw = path.read_bytes()
    if how == 'truncated':
        path.write_bytes(raw[:len(raw) // 2])
    elif how == 'empty':
        path.write_bytes(b'')
    else:
        value = json.loads(raw)
        value['outputs'] = value['outputs'][:-1]  # seal no longer matches
        path.write_bytes(driver.canonical(value))
    damaged = path.read_bytes()
    assert status(case) == dict(inputs='complete', c1='complete', c2='complete', c4='incomplete',
                                c5='blocked', receipt='blocked')
    resumed = resume(case)
    assert resumed['executed'] == ['c4'] and resumed['reused'] == ['inputs', 'c1', 'c2', 'c5', 'receipt']
    assert resumed['receipt']['determinism_digest'] == first['receipt']['determinism_digest']
    assert next(root.glob('quarantine/*/c4/stages/c4.json')).read_bytes() == damaged
    assert set(status(case).values()) == {'complete'}


def test_resume_a_b_a_binding_retains_truthful_status(case):
    a = run(case)
    root = case['kwargs']['workspace']
    pins_a = dict(case['kwargs'])
    url = case['plan']['sources'][0]['source_url']
    before = tree(root)
    case['plan']['sources'][0]['source_url'] = 'https://example.invalid/synthetic-grid-b'
    seal(case)
    assert case['kwargs']['plan_sha256'] != pins_a['plan_sha256']
    assert status(case)['inputs'] == 'stale'
    with pytest.raises(ValueError, match='stale stage binding refused: inputs'):
        resume(case)
    assert tree(root) == before
    case['plan']['sources'][0]['source_url'] = url
    seal(case)
    assert case['kwargs'] == pins_a
    assert set(status(case).values()) == {'complete'}
    again = resume(case)
    assert again['executed'] == [] and again['reused'] == ALL
    assert again['receipt']['determinism_digest'] == a['receipt']['determinism_digest']
    assert len(history(root)) == 2  # refused B appended nothing


def test_resume_mixed_completed_and_incomplete_stage_status_is_truthful(case, area):
    assert status(case) == dict(inputs='pending', c1='blocked', c2='blocked', c4='blocked', c5='blocked', receipt='blocked')
    assert not case['kwargs']['workspace'].exists()  # status is read-only
    run(case)
    root = case['kwargs']['workspace']
    (root / 'stages/c2.json').rename(area / 'c2-receipt-aside.json')
    report = status(case)
    assert report == dict(inputs='complete', c1='complete', c2='incomplete', c4='blocked', c5='blocked', receipt='blocked')


def test_resume_viewer_manifest_is_opt_in_and_archive_manifest_releases_nothing(case):
    first = run(case)
    root = case['kwargs']['workspace']
    assert first['manifests']['viewer'] is None and not list(root.glob('manifests/viewer-*'))
    archive = json.loads((root / first['manifests']['archive_candidates']['path']).read_text())
    assert archive['archived'] is False and archive['archive_verified'] is False and archive['closed'] is False
    assert 'skills/coast-segment-close' in archive['archive_owner']
    assert archive['cache_release'].startswith('not performed')
    assert [f['path'] for f in archive['cache_files']] == ['cache/source.tif']
    assert archive['determinism_digest'] == first['receipt']['determinism_digest']
    second = resume(case, viewer=True)
    assert second['executed'] == []
    viewer = json.loads((root / second['manifests']['viewer']['path']).read_text())
    assert viewer['opt_in'] is True and viewer['mask_qualified'] is False
    assert viewer['publication_allowed'] is False and viewer['local_only'] is True
    assert 'HELD' in viewer['terrain_mask_gate']
    assert {layer['path'].split('/')[0] for layer in viewer['layers']} == {'c1', 'c2', 'c4'}
    assert second['manifests']['archive_candidates'] == first['manifests']['archive_candidates']
    assert json.loads(history(root)[-1])['viewer'] == second['manifests']['viewer']
    # No cache release: the workspace copy and the frozen input cache both remain.
    for item in archive['cache_files']:
        assert sha256((root / item['path']).read_bytes()).hexdigest() == item['sha256']
    assert (case['input'] / 'cache/source.tif').exists()


def test_resume_refuses_unmarked_or_foreign_workspace(case):
    root = case['kwargs']['workspace']
    root.mkdir()
    with pytest.raises(ValueError, match='marked segment workspace'):
        resume(case)
    (root / driver.MARKER).write_bytes(driver.canonical(dict(schema='coast-segment-workspace-v1', root_id='queue:other',
                                                             segment_slug='x', campaign_segment_id='x')))
    with pytest.raises(ValueError, match='marker mismatch'):
        resume(case)
    assert sorted(p.name for p in root.iterdir()) == [driver.MARKER]


@pytest.mark.parametrize('how', ['edited', 'partial'])
def test_resume_refuses_damaged_manifest_history(case, how):
    run(case)
    root = case['kwargs']['workspace']
    path = root / driver.HISTORY
    raw = path.read_bytes()
    path.write_bytes(raw.replace(b'"seq":0', b'"seq":7') if how == 'edited' else raw + b'{"seq":1')
    before = tree(root)
    with pytest.raises(ValueError, match='manifest history damaged'):
        resume(case)
    assert tree(root) == before


def test_resume_cli_status_and_resume_modes(case, capsys):
    args = ['--input-root', str(case['input']), '--workspace', str(case['kwargs']['workspace']),
            '--admitted-root', str(case['kwargs']['admitted_root']), '--recipe-sha256', case['kwargs']['recipe_sha256'],
            '--plan-sha256', case['kwargs']['plan_sha256'], '--run-sha256', case['kwargs']['run_sha256'],
            '--code-commit', case['kwargs']['code_commit']]
    # The CLI keeps C1's production reserve default; a 250 GiB reserve is not
    # changed here, so only status (read-only) and refusals are exercised.
    assert driver.main(args + ['--status']) == 0
    assert json.loads(capsys.readouterr().out)['stages'][0] == dict(stage='inputs', status='pending')
    assert not case['kwargs']['workspace'].exists()
    run(case)
    assert driver.main(args + ['--status']) == 0
    assert json.loads(capsys.readouterr().out)['complete'] is True
    assert driver.main(args) == 3  # plain run never adopts an existing workspace
    assert 'fresh exclusive workspace' in capsys.readouterr().err
