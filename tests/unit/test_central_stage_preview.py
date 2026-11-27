"""The manual Central Coast stage preview: one region per run on its own Worker and bucket.

Same controller scripts as the Morro preview (morro_stage_preview / morro_stage_controller /
morro_sources_overlay), now taking the region; Morro defaults are unchanged (its own tests).
Offline only: no Cloudflare, GitHub or R2 call is made.
"""
import hashlib
import json
import os
import re
import subprocess
import sys

import pytest
import yaml

from scripts.relief import morro_sources_overlay as overlay
from scripts.relief import morro_stage_controller as controller
from scripts.relief import morro_stage_preview as preview
from scripts.relief import central_preview_identities as identities
from scripts.relief.central_stage_handoff import CENTRAL_RELEASES
from scripts import build_sources_register as register
from skippercast.relief import package
from tests._support import ROOT

CENTRAL = preview.CENTRAL_REGIONS
WORKFLOW_PATH = ROOT / '.github/workflows/central-stage-preview.yml'
WORKFLOW_TEXT = WORKFLOW_PATH.read_text()
WORKFLOW = yaml.safe_load(WORKFLOW_TEXT)
MORRO_TEXT = (ROOT / '.github/workflows/stage-preview.yml').read_text()
MORRO = yaml.safe_load(MORRO_TEXT)
STEPS = WORKFLOW['jobs']['preview']['steps']
FETCH = WORKFLOW['jobs']['fetch']['steps']
WORKER, BUCKET = 'skippercast-central-stage', 'skippercast-feeds-central-stage'


def git(repo, *args):
    return subprocess.run(['git', '-C', str(repo), '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid',
                           '-c', 'commit.gpgsign=false', *args], check=True, capture_output=True, text=True).stdout.strip()


def commit(repo, files, message):
    for path, data in files.items():
        target = repo / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data if isinstance(data, bytes) else data.encode())
    git(repo, 'add', '-A')
    git(repo, 'commit', '-q', '-m', message)
    return git(repo, 'rev-parse', 'HEAD')


def pointer_bytes(region, generation='a' * 64, **extra):
    doc = {'schema': 'sc-relief-pointer/1', 'region': region, 'generation': generation, **extra}
    return (json.dumps(doc, sort_keys=True) + '\n').encode()


@pytest.fixture
def repo(tmp_path):
    repo = tmp_path / 'candidate'
    repo.mkdir()
    git(repo, 'init', '-q')
    return repo


REGION_JSON = 'dist/regions/big-sur-coast/region.json'
BOTH_CONTOURS = ['depth-contours-overview.geojson', 'depth-contours.geojson']


def region_json(chart_files, **extra):
    doc = {'id': 'big-sur-coast', 'name': 'Big Sur outer coast', **extra}
    if chart_files is not None:
        doc['chart_files'] = chart_files
    return json.dumps(doc) + '\n'


@pytest.fixture
def base(repo):
    # Reviewed main as it is before a region's first contours: region.json lists no Chart side files.
    page = f'<html>reviewed\n{register.BEGIN}\nold register\n{register.END}\n</html>\n'
    return commit(repo, {'server/index.ts': 'export {}\n', 'dist/sources.html': page, REGION_JSON: region_json([])},
                  'reviewed main')


def step(steps, name_prefix):
    matches = [i for i, s in enumerate(steps) if s.get('name', '').startswith(name_prefix)]
    assert len(matches) == 1, name_prefix
    return matches[0]


# --- region targets ------------------------------------------------------------------------------

def test_central_stage_regions_are_exactly_the_contour_bearing_central_regions():
    # The preview pins and serves a contour pair, so the two terrain-only regions are not stage regions.
    six = set(CENTRAL_RELEASES)
    assert len(six) == 6 and set(identities.TERRAIN_ONLY) < six
    assert set(CENTRAL) == six - identities.TERRAIN_ONLY and len(CENTRAL) == 4


@pytest.mark.parametrize('region', sorted(identities.TERRAIN_ONLY))
def test_terrain_only_regions_are_refused_before_any_checkout_and_by_every_command(region, repo, base, tmp_path):
    inputs = WORKFLOW[True]['workflow_dispatch']['inputs']['region']['options']
    assert region not in inputs
    for steps in (FETCH, STEPS):
        assert region not in steps[0]['run']
    with pytest.raises(preview.PreviewError, match='may carry'):
        preview.check_region(region)
    with pytest.raises(preview.PreviewError):
        controller.data_paths(region)
    with pytest.raises(ValueError):
        overlay.inputs(region)
    data = pointer_bytes(region)
    sha = commit(repo, {preview.pointer_path(region): data}, f'{region} data')
    with pytest.raises(SystemExit):
        controller.main(['scope', '--tree', str(repo), '--base', base, '--sha', sha, '--region', region])
    with pytest.raises(SystemExit):
        preview.main(['plan', '--tree', str(repo), '--sha', sha, '--pointer-sha256', hashlib.sha256(data).hexdigest(),
                      '--wrangler', str(ROOT / 'wrangler.jsonc'), '--region', region,
                      '--worker', WORKER, '--bucket', BUCKET, '--out', str(tmp_path / 'plan')])
    assert not (tmp_path / 'plan').exists()


def test_every_central_region_has_the_one_central_target_and_morro_keeps_its_own():
    assert set(preview.REGIONS) == {'morro-bay', *CENTRAL}
    assert preview.STAGE_TARGETS['morro-bay'] == ('skippercast-morro-stage', 'skippercast-feeds-stage')
    for region in CENTRAL:
        assert preview.STAGE_TARGETS[region] == (WORKER, BUCKET)
    for worker, bucket in preview.STAGE_TARGETS.values():
        assert worker.endswith('-stage') and bucket.endswith('-stage')
        assert worker != preview.PRODUCTION_WORKER and bucket not in preview.PRODUCTION_BUCKETS


@pytest.mark.parametrize('region', ['southern-california', 'crescent-city', 'Big-Sur-Coast', '', None, '../morro-bay'])
def test_regions_outside_the_list_are_refused_everywhere(region, repo, base):
    with pytest.raises(preview.PreviewError, match='may carry'):
        preview.check_region(region)
    with pytest.raises(preview.PreviewError):
        controller.data_paths(region)
    with pytest.raises(controller.HoldError):
        controller.preview_tag({'region': region, 'envelope_sha256': 'e' * 64}, region)


@pytest.mark.parametrize('region', CENTRAL)
def test_plan_binds_the_region_pointer_to_the_central_target(repo, base, tmp_path, region):
    data = pointer_bytes(region)
    sha = commit(repo, {preview.pointer_path(region): data}, f'{region} data')
    out = tmp_path / 'plan'
    assert preview.main(['plan', '--tree', str(repo), '--sha', sha, '--pointer-sha256', hashlib.sha256(data).hexdigest(),
                         '--wrangler', str(ROOT / 'wrangler.jsonc'), '--region', region,
                         '--worker', WORKER, '--bucket', BUCKET, '--out', str(out)]) == 0
    receipt = json.loads((out / 'plan.json').read_text())
    assert (receipt['region'], receipt['worker'], receipt['bucket'], receipt['commit']) == (region, WORKER, BUCKET, sha)
    assert preview.read_plan((out / 'plan.json').read_bytes())['region'] == region
    loaded, _ = controller.load_plan(out)
    assert loaded['region'] == region
    origin = f'https://{WORKER}.fixture-account.workers.dev'
    assert controller.place_config(out, repo, origin).name == 'wrangler.stage.json'


def test_a_central_region_cannot_use_the_morro_preview_and_morro_cannot_use_the_central_one(repo, base):
    data = pointer_bytes('big-sur-coast')
    sha = commit(repo, {preview.pointer_path('big-sur-coast'): data}, 'big sur data')
    digest = hashlib.sha256(data).hexdigest()
    text = (ROOT / 'wrangler.jsonc').read_text()
    with pytest.raises(preview.PreviewError, match='its own stage Worker and bucket'):
        preview.plan(repo, sha, text, worker='skippercast-morro-stage', bucket='skippercast-feeds-stage',
                     pointer_sha256=digest, region='big-sur-coast')
    with pytest.raises(preview.PreviewError, match='its own stage Worker and bucket'):
        preview.plan(repo, sha, text, worker=WORKER, bucket='skippercast-feeds-stage', pointer_sha256=digest,
                     region='big-sur-coast')
    with pytest.raises(preview.PreviewError, match='its own stage Worker and bucket'):
        preview.plan(repo, sha, text, worker=WORKER, bucket=BUCKET, pointer_sha256=digest)  # Morro default region


def test_plan_holds_a_pointer_for_another_region(repo, base):
    data = pointer_bytes('cambria-san-simeon')
    sha = commit(repo, {preview.pointer_path('big-sur-coast'): data}, 'mislabelled pointer')
    with pytest.raises(preview.PreviewError, match='not for big-sur-coast'):
        preview.plan(repo, sha, (ROOT / 'wrangler.jsonc').read_text(), worker=WORKER, bucket=BUCKET,
                     pointer_sha256=hashlib.sha256(data).hexdigest(), region='big-sur-coast')


def test_a_tampered_plan_naming_the_morro_target_for_a_central_region_is_held(repo, base, tmp_path):
    data = pointer_bytes('big-sur-coast')
    sha = commit(repo, {preview.pointer_path('big-sur-coast'): data}, 'big sur data')
    out = tmp_path / 'plan'
    assert preview.main(['plan', '--tree', str(repo), '--sha', sha, '--pointer-sha256', hashlib.sha256(data).hexdigest(),
                         '--wrangler', str(ROOT / 'wrangler.jsonc'), '--region', 'big-sur-coast',
                         '--worker', WORKER, '--bucket', BUCKET, '--out', str(out)]) == 0
    receipt = json.loads((out / 'plan.json').read_text())
    receipt['region'] = 'morro-bay'
    (out / 'plan.json').write_text(json.dumps(receipt))
    with pytest.raises(controller.HoldError, match="region's own stage Worker"):
        controller.load_plan(out)
    with pytest.raises(preview.PreviewError, match="region's own stage Worker"):
        preview.read_plan((out / 'plan.json').read_bytes())


# --- scope ---------------------------------------------------------------------------------------

def test_scope_admits_only_the_named_region_data(repo, base):
    region = 'big-sur-coast'
    files = {preview.pointer_path(region): pointer_bytes(region),
             preview.contours_path(region): '{"type":"FeatureCollection","features":[]}\n',
             f'dist/regions/{region}/depth-contours.geojson': '{}\n',
             f'dist/regions/{region}/depth-contours-overview.geojson': '{}\n',
             # A region's first contours: the build rewrites its chart_files and the register its credits.
             REGION_JSON: region_json(BOTH_CONTOURS),
             'dist/sources.html': f'<html>reviewed\n{register.BEGIN}\nnew register\n{register.END}\n</html>\n'}
    sha = commit(repo, files, 'big sur data')
    assert controller.scope(repo, base, sha, region) == sorted(files)
    assert controller.main(['scope', '--tree', str(repo), '--base', base, '--sha', sha, '--region', region]) == 0
    # The same candidate is outside Morro's data and outside another Central region's data.
    with pytest.raises(controller.HoldError, match='outside the Morro data'):
        controller.scope(repo, base, sha)
    with pytest.raises(controller.HoldError, match='outside the cambria-san-simeon data'):
        controller.scope(repo, base, sha, 'cambria-san-simeon')


def contour_candidate(repo, region_doc):
    region = 'big-sur-coast'
    files = {preview.pointer_path(region): pointer_bytes(region),
             f'dist/regions/{region}/depth-contours.geojson': '{}\n',
             f'dist/regions/{region}/depth-contours-overview.geojson': '{}\n'}
    if region_doc is not None:
        files[REGION_JSON] = region_doc
    return commit(repo, files, 'contour candidate')


def test_scope_holds_a_stale_chart_index_that_was_not_changed(repo, base):
    # The reviewed regression: contours added, region.json left with its empty list, so the Chart asks for neither.
    sha = contour_candidate(repo, None)
    with pytest.raises(controller.HoldError, match='chart_files omits depth-contours.geojson, depth-contours-overview'):
        controller.scope(repo, base, sha, 'big-sur-coast')
    assert controller.main(['scope', '--tree', str(repo), '--base', base, '--sha', sha, '--region', 'big-sur-coast']) != 0


@pytest.mark.parametrize('chart_files, match', [
    (['depth-contours.geojson'], 'omits depth-contours-overview.geojson'),
    (['depth-contours-overview.geojson', 'shoreline.geojson'], r'omits depth-contours\.geojson,'),
    (None, 'has no chart_files list'),
    ('depth-contours.geojson depth-contours-overview.geojson', 'has no chart_files list'),
])
def test_scope_holds_a_changed_chart_index_without_both_contour_files(repo, base, chart_files, match):
    sha = contour_candidate(repo, region_json(chart_files))
    with pytest.raises(controller.HoldError, match=match):
        controller.scope(repo, base, sha, 'big-sur-coast')


@pytest.mark.parametrize('doc', [region_json(BOTH_CONTOURS, status='live'),
                                 json.dumps({'id': 'big-sur-coast', 'chart_files': BOTH_CONTOURS}) + '\n'])
def test_scope_holds_a_region_json_change_beyond_chart_files(repo, base, doc):
    sha = contour_candidate(repo, doc)
    with pytest.raises(controller.HoldError, match='changes more than its chart_files list'):
        controller.scope(repo, base, sha, 'big-sur-coast')


@pytest.mark.parametrize('doc, match', [('not json\n', 'is not JSON'), ('[]\n', 'is not a JSON object')])
def test_scope_holds_a_malformed_region_json(repo, base, doc, match):
    sha = contour_candidate(repo, doc)
    with pytest.raises(controller.HoldError, match=match):
        controller.scope(repo, base, sha, 'big-sur-coast')


def test_scope_holds_a_deleted_region_json(repo, base):
    git(repo, 'rm', '-q', REGION_JSON)
    git(repo, 'commit', '-q', '-m', 'delete region.json')
    with pytest.raises(controller.HoldError, match='region.json is missing'):
        controller.scope(repo, base, git(repo, 'rev-parse', 'HEAD'), 'big-sur-coast')


def test_scope_accepts_an_unchanged_chart_index_that_already_lists_both_contour_files(repo):
    page = f'<html>reviewed\n{register.BEGIN}\nold\n{register.END}\n</html>\n'
    base = commit(repo, {'dist/sources.html': page, REGION_JSON: region_json(BOTH_CONTOURS)}, 'main with contours')
    sha = contour_candidate(repo, None)
    assert REGION_JSON not in controller.scope(repo, base, sha, 'big-sur-coast')


# A region whose shipped region.json already lists Chart side files (Cambria-San Simeon on main lists these five).
CAMBRIA = 'cambria-san-simeon'
CAMBRIA_JSON = f'dist/regions/{CAMBRIA}/region.json'
CAMBRIA_SHIPPED = json.loads((ROOT / CAMBRIA_JSON).read_text())


def cambria_candidate(repo, chart_files):
    page = f'<html>reviewed\n{register.BEGIN}\nold\n{register.END}\n</html>\n'
    base = commit(repo, {'dist/sources.html': page, CAMBRIA_JSON: json.dumps(CAMBRIA_SHIPPED) + '\n'}, 'main (Cambria)')
    files = {preview.pointer_path(CAMBRIA): pointer_bytes(CAMBRIA),
             f'dist/regions/{CAMBRIA}/depth-contours.geojson': '{}\n',
             f'dist/regions/{CAMBRIA}/depth-contours-overview.geojson': '{}\n',
             CAMBRIA_JSON: json.dumps({**CAMBRIA_SHIPPED, 'chart_files': chart_files}) + '\n'}
    return base, commit(repo, files, 'cambria contour candidate')


def test_the_cambria_fixture_is_the_shipped_list_of_five_existing_chart_files():
    assert sorted(CAMBRIA_SHIPPED['chart_files']) == ['land-water-lines.json', 'land-water.json', 'poster.svg',
                                                       'shoreline-overview.geojson', 'shoreline.geojson']


@pytest.mark.parametrize('order', [lambda kept: kept + BOTH_CONTOURS, lambda kept: sorted(kept + BOTH_CONTOURS)])
def test_scope_accepts_a_chart_index_that_keeps_every_existing_file_and_adds_the_pair(repo, order):
    base, sha = cambria_candidate(repo, order(list(CAMBRIA_SHIPPED['chart_files'])))
    assert CAMBRIA_JSON in controller.scope(repo, base, sha, CAMBRIA)


@pytest.mark.parametrize('chart_files, match', [
    # The reviewed regression (RETURN at caff7219): both contour names kept, all five shipped files dropped.
    (BOTH_CONTOURS, 'drops land-water-lines.json, land-water.json, poster.svg, shoreline-overview.geojson, shoreline.geojson'),
    ([n for n in CAMBRIA_SHIPPED['chart_files'] if n != 'shoreline.geojson'] + BOTH_CONTOURS, r'drops shoreline\.geojson,'),
    (CAMBRIA_SHIPPED['chart_files'] + BOTH_CONTOURS + ['depth-contours.geojson'], 'lists depth-contours.geojson more than once'),
    (CAMBRIA_SHIPPED['chart_files'] + ['poster.svg'] + BOTH_CONTOURS, 'lists poster.svg more than once'),
    (CAMBRIA_SHIPPED['chart_files'] + BOTH_CONTOURS + ['coastline.geojson'], 'adds coastline.geojson beyond the contour pair'),
])
def test_scope_holds_a_chart_index_that_loses_repeats_or_invents_chart_files(repo, chart_files, match):
    base, sha = cambria_candidate(repo, chart_files)
    with pytest.raises(controller.HoldError, match=match):
        controller.scope(repo, base, sha, CAMBRIA)
    assert controller.main(['scope', '--tree', str(repo), '--base', base, '--sha', sha, '--region', CAMBRIA]) != 0


def test_scope_holds_when_the_base_region_json_has_no_chart_files_list(repo):
    page = f'<html>reviewed\n{register.BEGIN}\nold\n{register.END}\n</html>\n'
    base = commit(repo, {'dist/sources.html': page, REGION_JSON: region_json(None)}, 'main without a list')
    sha = contour_candidate(repo, region_json(BOTH_CONTOURS))
    with pytest.raises(controller.HoldError, match='base dist/regions/big-sur-coast/region.json has no chart_files list'):
        controller.scope(repo, base, sha, 'big-sur-coast')


def test_the_preview_must_serve_the_candidates_region_json():
    served = STEPS[step(STEPS, 'Require the preview to serve exactly')]['run']
    assert '"$STAGE_URL/regions/$REGION/region.json" -o "$served/region.json"' in served
    assert 'cmp -s "$served/region.json" "dist/regions/$REGION/region.json" || { ok=0;' in served
    cleared = [line for line in served.splitlines() if line.strip().startswith('rm -f "$served/deploy.json"')]
    assert len(cleared) == 1 and '"$served/region.json"' in cleared[0]  # no stale copy survives a retry


@pytest.mark.parametrize('page', [
    f'<html><script>bad()</script>\n{register.BEGIN}\nnew\n{register.END}\n</html>\n',
    f'<html>reviewed\n{register.BEGIN}\nnew\n{register.END}\n<script>bad()</script></html>\n',
    f'<html>reviewed\n{register.BEGIN}\nnew\n{register.END}\n{register.END}\n</html>\n',
    f'<html>reviewed\n{register.END}\nnew\n{register.BEGIN}\n</html>\n',
    f'<html>reviewed\n{register.BEGIN}\n{register.BEGIN}\n{register.END}\n</html>\n',
    '<html>no markers</html>\n',
])
def test_scope_holds_changes_outside_register_and_ambiguous_markers(repo, base, page):
    sha = commit(repo, {'dist/sources.html': page}, 'unreviewed page')
    with pytest.raises(controller.HoldError, match='sources.html'):
        controller.scope(repo, base, sha, 'big-sur-coast')


def test_scope_holds_deleted_sources_page(repo, base):
    git(repo, 'rm', 'dist/sources.html')
    git(repo, 'commit', '-q', '-m', 'delete page')
    with pytest.raises(controller.HoldError):
        controller.scope(repo, base, git(repo, 'rev-parse', 'HEAD'), 'big-sur-coast')


def test_morro_scope_is_unchanged():
    assert controller.DATA_PATHS == {'catalog/relief/morro-bay.json', 'catalog/depth-contours/morro-bay.geojson',
                                     'dist/regions/morro-bay/depth-contours.geojson',
                                     'dist/regions/morro-bay/depth-contours-overview.geojson'}
    assert controller.data_paths('morro-bay') == controller.DATA_PATHS


@pytest.mark.parametrize('other', ['dist/regions/big-sur-coast/manifest.json', 'catalog/relief/morro-bay.json',
                                   'catalog/sources.json', 'server/index.ts', 'dist/regions/index.json',
                                   'dist/regions/cambria-san-simeon/region.json'])
def test_scope_holds_any_other_file_for_a_central_region(repo, base, other):
    sha = commit(repo, {preview.pointer_path('big-sur-coast'): pointer_bytes('big-sur-coast'), other: '{}\n'}, 'more')
    with pytest.raises(controller.HoldError, match='outside the big-sur-coast data'):
        controller.scope(repo, base, sha, 'big-sur-coast')


# --- preview tag and pointer files ---------------------------------------------------------------

def test_preview_tag_names_the_region_and_never_the_production_tag():
    pointer = {'region': 'big-sur-coast', 'envelope_sha256': 'e' * 64}
    assert controller.preview_tag(pointer, 'big-sur-coast') == 'relief-preview-big-sur-coast-' + 'e' * 64
    with pytest.raises(controller.HoldError, match='Morro Bay pointer'):
        controller.preview_tag(pointer)
    with pytest.raises(controller.HoldError, match='cambria-san-simeon pointer'):
        controller.preview_tag(pointer, 'cambria-san-simeon')


def test_fetch_refuses_a_pointer_for_another_region_before_any_request(tmp_path):
    data = pointer_bytes('cambria-san-simeon')
    path = tmp_path / 'pointer.json'
    path.write_bytes(data)

    class Never:
        def assets(self, tag):
            raise AssertionError('no listing may be read for a mismatched region')

    # Held by the schema or the region check, either way before any listing is read.
    with pytest.raises((controller.HoldError, package.ReleaseError)):
        controller.fetch(path, hashlib.sha256(data).hexdigest(), tmp_path / 'out', release=Never(),
                         region='big-sur-coast')
    assert not (tmp_path / 'out').exists()


# --- /sources overlay ----------------------------------------------------------------------------

def test_overlay_inputs_follow_the_region_and_refuse_others():
    assert overlay.INPUTS == overlay.inputs('morro-bay')
    names = overlay.inputs('big-sur-coast')
    assert names['pointer'] == 'catalog/relief/big-sur-coast.json'
    assert names['detail'] == 'dist/regions/big-sur-coast/depth-contours.geojson'
    assert names['overview'] == 'dist/regions/big-sur-coast/depth-contours-overview.geojson'
    assert names['catalogue'] == 'catalog/sources.json'
    with pytest.raises(ValueError):
        overlay.inputs('southern-california')


def test_overlay_contour_rows_refuse_another_region_set():
    doc = {'type': 'FeatureCollection', 'features': [{}],
           'provenance': {'region_id': 'morro-bay', 'set': 'ft-v3', 'units': 'ft', 'contours': 's' * 64, 'features': 1,
                          'sources': []}}
    with pytest.raises(ValueError, match='big-sur-coast ft-v3'):
        list(overlay._contour_rows(doc, 'detail', 's' * 64, 'big-sur-coast'))
    assert list(overlay._contour_rows(doc, 'detail', 's' * 64)) == []


def overlay_tree(tmp_path):
    tree = tmp_path / 'tree'
    names = overlay.inputs('big-sur-coast')
    blobs = {name: f'{{"{name}": 1}}\n'.encode() for name in names}
    for name, path in names.items():
        (tree / path).parent.mkdir(parents=True, exist_ok=True)
        (tree / path).write_bytes(blobs[name])
    return tree, {name: hashlib.sha256(raw).hexdigest() for name, raw in blobs.items()}


@pytest.mark.parametrize('missing', ['detail', 'overview'])
def test_overlay_requires_both_contour_pins_for_a_central_candidate(tmp_path, missing, capsys):
    tree, pins = overlay_tree(tmp_path)
    args = ['--tree', str(tree), '--out', str(tmp_path / 'out'), '--region', 'big-sur-coast']
    for name, pin in pins.items():
        if name != missing:
            args += [f'--{name}-sha256', pin]
    with pytest.raises(SystemExit) as stop:
        overlay.main(args)
    assert stop.value.code == 2 and f'--{missing}-sha256' in capsys.readouterr().err
    assert not (tmp_path / 'out').exists()


@pytest.mark.parametrize('wrong', ['detail', 'overview'])
def test_overlay_holds_a_mismatched_contour_pin_for_a_central_candidate(tmp_path, wrong, capsys):
    tree, pins = overlay_tree(tmp_path)
    pins[wrong] = 'f' * 64
    args = ['--tree', str(tree), '--out', str(tmp_path / 'out'), '--region', 'big-sur-coast']
    for name, pin in pins.items():
        args += [f'--{name}-sha256', pin]
    assert overlay.main(args) == 2
    assert f'{wrong}: SHA-256 differs from the reviewed pin' in capsys.readouterr().err
    assert not (tmp_path / 'out').exists()


# --- workflow ------------------------------------------------------------------------------------

def test_workflow_is_manual_from_protected_main_with_a_fixed_region_list():
    triggers = WORKFLOW[True]
    assert list(triggers) == ['workflow_dispatch']
    inputs = triggers['workflow_dispatch']['inputs']
    assert set(inputs) == {'region', *MORRO[True]['workflow_dispatch']['inputs']}
    assert inputs['region']['type'] == 'choice' and inputs['region']['options'] == list(CENTRAL)
    assert WORKFLOW['permissions'] == {'contents': 'read'}
    assert list(WORKFLOW['jobs']) == ['fetch', 'preview']
    for job in WORKFLOW['jobs'].values():
        for clause in ("github.event_name == 'workflow_dispatch'", "github.repository == 'Grahammmm/skippercast'",
                       "github.ref == 'refs/heads/main'", 'github.ref_protected'):
            assert clause in job['if']
        assert job['env']['REGION'] == '${{ inputs.region }}'
    assert WORKFLOW['jobs']['preview']['environment'] == 'central-stage-preview'
    assert (WORKFLOW['env']['STAGE_WORKER'], WORKFLOW['env']['STAGE_BUCKET']) == (WORKER, BUCKET)
    assert WORKFLOW['concurrency']['group'] != MORRO['concurrency']['group']


def test_both_jobs_reject_an_unlisted_region_before_any_checkout():
    for steps in (FETCH, STEPS):
        first = steps[0]
        assert first['name'].startswith('Reject a non-main dispatch')
        case = re.search(r'case "\$REGION" in\s+([^)]+)\)', first['run'])
        assert case and case.group(1).split('|') == list(CENTRAL)
        assert 'exit 1' in first['run']
        checkouts = [i for i, s in enumerate(steps) if str(s.get('uses', '')).startswith('actions/checkout@')]
        assert checkouts and min(checkouts) > 0


def test_workflow_shell_reads_the_region_only_from_the_env():
    # `${{ inputs.region }}` is expanded by Actions before the shell runs, so it may appear only in
    # `with:` values and the env, never inside a run body (script injection).
    for job in WORKFLOW['jobs'].values():
        for s in job['steps']:
            assert '${{ inputs.' not in s.get('run', ''), s.get('name')


def test_every_controller_call_carries_the_region():
    runs = {s['name']: s['run'] for s in STEPS if 'run' in s}
    assert '--region "$REGION"' in runs["Require the candidate to change only the region's data against the controller"]
    assert '--region "$REGION"' in runs['Plan the isolated stage config before any dependency or build runs']
    assert '--region "$REGION"' in runs['Re-plan after the build (only dependencies and build output may have appeared)']
    assert '--region "$REGION"' in runs["Render the candidate's /sources credits from its pinned files"]
    fetch = FETCH[step(FETCH, 'Fetch the candidate pointer')]['run']
    assert '--region "$REGION" --pointer "catalog/relief/$REGION.json"' in fetch
    sparse = [s for s in FETCH if str(s.get('uses', '')).startswith('actions/checkout@')][1]['with']['sparse-checkout']
    assert sparse == 'catalog/relief/${{ inputs.region }}.json'
    served = STEPS[step(STEPS, 'Require the preview to serve exactly')]['run']
    for path in ('/catalog/relief/$REGION.json', '/regions/$REGION/depth-contours.geojson',
                 '/regions/$REGION/depth-contours-overview.geojson'):
        assert path in served
    assert 'morro-bay' not in WORKFLOW_TEXT


def test_workflow_matches_the_reviewed_morro_preview_apart_from_the_region():
    # Same steps in the same order with the same actions and secrets: the Central preview is the reviewed
    # Morro preview with the region made an input, nothing added or dropped.
    for job in ('fetch', 'preview'):
        ours, theirs = WORKFLOW['jobs'][job]['steps'], MORRO['jobs'][job]['steps']
        assert [s.get('uses') for s in ours] == [s.get('uses') for s in theirs]
        assert len(ours) == len(theirs)
        for a, b in zip(ours, theirs):
            assert set(a.get('env', {})) == set(b.get('env', {}))
            assert (a.get('if'), a.get('working-directory'), a.get('continue-on-error')) == \
                   (b.get('if'), b.get('working-directory'), b.get('continue-on-error'))
        assert WORKFLOW['jobs'][job].get('permissions') == MORRO['jobs'][job].get('permissions')
        assert WORKFLOW['jobs'][job]['timeout-minutes'] == MORRO['jobs'][job]['timeout-minutes']
    secrets = set(re.findall(r'secrets\.([A-Z0-9_]+)', WORKFLOW_TEXT))
    assert secrets == set(re.findall(r'secrets\.([A-Z0-9_]+)', MORRO_TEXT))
    body = '\n'.join(line for line in WORKFLOW_TEXT.splitlines() if not line.lstrip().startswith('#'))
    for production in ("'skippercast-feeds'", 'skippercast-feeds ', 'skippercast-backups', 'skippercast-advisor-media',
                       'cloudflare_deploy.sh', 'd1 ', 'CUSTOM_DOMAINS', 'pull_request_target', 'vars.',
                       'skippercast-morro-stage', 'skippercast-feeds-stage\n'):
        assert production not in body


CONTROLLER_CALL = re.compile(r'python3 -I "\$CONTROLLER/(scripts/relief/[a-z_]+\.py)" ([a-z-]+)')


@pytest.mark.parametrize('workflow', [WORKFLOW, MORRO], ids=['central', 'morro'])
@pytest.mark.parametrize('job', ['fetch', 'preview'])
def test_every_controller_command_starts_from_the_workflow_sparse_checkout(workflow, job, tmp_path):
    # The job runs the controller from its own sparse checkout of main, not from a full tree: lay out exactly
    # the tracked files that checkout names and start every command the job calls (an import missing from the
    # checkout fails here, as it would on the runner before any asset is fetched).
    steps = workflow['jobs'][job]['steps']
    checkout = next(s for s in steps if s.get('with', {}).get('path') == '.preview-controller')
    patterns = checkout['with']['sparse-checkout'].split()
    tracked = subprocess.run(['git', '-C', str(ROOT), 'ls-files', '-z'], check=True, capture_output=True).stdout
    for path in tracked.decode().split('\0'):
        if any(path == p or (p.endswith('/') and path.startswith(p)) for p in patterns):
            (tmp_path / path).parent.mkdir(parents=True, exist_ok=True)
            (tmp_path / path).write_bytes((ROOT / path).read_bytes())
    calls = sorted({m.groups() for s in steps for m in CONTROLLER_CALL.finditer(s.get('run', ''))})
    assert calls, job
    for script, command in calls:
        run = subprocess.run([sys.executable, '-I', str(tmp_path / script), command, '--help'], cwd=tmp_path,
                             env={'PATH': os.environ.get('PATH', '')}, capture_output=True, text=True, timeout=60)
        assert run.returncode == 0, (script, command, run.stderr[-2000:])
