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


@pytest.fixture
def base(repo):
    page = f'<html>reviewed\n{register.BEGIN}\nold register\n{register.END}\n</html>\n'
    return commit(repo, {'server/index.ts': 'export {}\n', 'dist/sources.html': page}, 'reviewed main')


def step(steps, name_prefix):
    matches = [i for i, s in enumerate(steps) if s.get('name', '').startswith(name_prefix)]
    assert len(matches) == 1, name_prefix
    return matches[0]


# --- region targets ------------------------------------------------------------------------------

def test_every_central_region_has_the_one_central_target_and_morro_keeps_its_own():
    assert set(preview.REGIONS) == {'morro-bay', *CENTRAL} and len(CENTRAL) == 6
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
             f'dist/regions/{region}/region.json': '{}\n',
             'dist/sources.html': f'<html>reviewed\n{register.BEGIN}\nnew register\n{register.END}\n</html>\n'}
    sha = commit(repo, files, 'big sur data')
    assert controller.scope(repo, base, sha, region) == sorted(files)
    assert controller.main(['scope', '--tree', str(repo), '--base', base, '--sha', sha, '--region', region]) == 0
    # The same candidate is outside Morro's data and outside another Central region's data.
    with pytest.raises(controller.HoldError, match='outside the Morro data'):
        controller.scope(repo, base, sha)
    with pytest.raises(controller.HoldError, match='outside the cambria-san-simeon data'):
        controller.scope(repo, base, sha, 'cambria-san-simeon')


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
