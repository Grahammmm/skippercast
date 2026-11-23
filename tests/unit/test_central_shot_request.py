"""Offline request → shots parser and camera plan; no stage execution."""
from hashlib import sha256
import json
from shutil import copyfile

import pytest

from scripts.relief import central_shot_request as request, region as cli
from skippercast.relief import envelope, package, receipts, render_config
from tests._support import ROOT

REGION = 'monterey-point-sur'
BOUNDS = [-122.35, 36.3, -121.65, 36.625]
SOURCE = 'synthetic-grid'
GEN = 'a' * 64


def _write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return sha256(data).hexdigest()


def _json(path, doc):
    return _write(path, json.dumps(doc, sort_keys=True).encode())


@pytest.fixture
def candidate(tmp_path, monkeypatch):
    config = tmp_path / 'repo-config'
    rights = {'public_display': 'allowed', 'license': 'public-domain'}
    _json(config / 'catalog/sources.json', {'sources': [dict(id=SOURCE, rights=rights, review_status='approved')]})
    schema = 'catalog/relief/pointer.schema.json'
    (config / schema).parent.mkdir()
    copyfile(ROOT / schema, config / schema)
    monkeypatch.setattr(package, 'repo_root', lambda: config)
    monkeypatch.setattr(envelope, 'repo_root', lambda: config)
    out = tmp_path / 'scratch OUT'
    basemap = tmp_path / 'base $map.pmtiles'
    _write(basemap, b'synthetic basemap')

    def make(region=REGION, bounds=BOUNDS):
        root = out / region

        def ref(path, doc):
            return {'path': path, 'sha256': _json(root / path, doc)}

        layers = [{'path': path, 'sha256': _write(root / path, b'layer'), 'bytes': 5}
                  for path in sorted((package.ARCHIVE, package.DIGEST_ROOT))]
        release = ref(f'release/{GEN}/release.json', {
            'schema': package.RELEASE_SCHEMA, 'region': region, 'generation': GEN,
            'code_sha': 'b' * 40, 'private': False, 'disclaimer': package.DISCLAIMER,
            'bounds': bounds, 'minzoom': 8, 'maxzoom': 8, 'layers': layers,
            'digest_root_sha256': sha256(b'layer').hexdigest(),
            'sources': [{'id': SOURCE, 'attribution': 'Synthetic survey', 'rights': rights,
                         'rights_class': 'public', 'label': 'estimated', 'vertical_datum': 'NAVD88',
                         'survey_dates': ['2020']}],
            'detail_summary': {'mask': 'transparent-nodata', 'depth_bands': [
                {'source_id': SOURCE, 'min_depth_m': 0, 'max_depth_m': 20, 'resolution_m': 2, 'support_class': 2}
            ]},
            'native_support_by_zoom': {'8': {'tiles': 1, 'limit_m': 91.44, 'sources': []}},
        })
        qa = ref(f'qa/{GEN}/qa.json', {'status': 'PASS', 'release_sha256': release['sha256']})
        review = ref(f'review/{GEN}/envelope.json', {'schema': envelope.ENVELOPE_SCHEMA, 'region': region,
                                                    'generation': GEN, 'release': release, 'qa': qa, 'layers': layers})
        return out, root / review['path'], basemap, release, review['sha256']

    return make


def _args(data, camera='monterey-harbor-z13'):
    out, review, basemap, *_ = data
    return ['--region', REGION, '--camera', camera, '--out', str(out), '--envelope', str(review),
            '--basemap', str(basemap)]


@pytest.mark.parametrize(('camera', 'center'), [
    ('monterey-harbor-z13', [-121.888, 36.605]),
    ('monterey-peninsula-z15', [-121.96, 36.6]),
])
def test_request_round_trips_to_actual_shots(camera, center, candidate, monkeypatch, capsys):
    """Catch first-camera fallback, coordinate drift/swaps, unsupported flags and wrong hash/paths."""
    data = candidate()
    out, review, basemap, release, review_sha = data
    seen = []

    def inspect(run):
        assert run.stage == 'shots' and run.region.id == REGION and run.region.out_root == out
        plan = run.plan({'package': {'generation': GEN, 'outputs': [release]}})
        assert plan.params['camera'] == center  # Real shots.plan invokes shots.camera.
        assert [item.path for item in plan.inputs] == [review.parents[2] / release['path'], basemap]
        seen.append(run.stage)
        return receipts.Result('ok', 'shots', None, GEN, 'parser only', out / 'unused.json')

    monkeypatch.setattr(receipts, 'run_stage', inspect)
    assert request.main(_args(data, camera)) == 0 and not seen
    msg = json.loads(capsys.readouterr().out)
    assert msg['camera_id'] == camera
    assert msg['expected_release_sha256'] == release['sha256']
    assert msg['expected_envelope_sha256'] == review_sha
    program, no_pyc, script, *shots_argv = msg['argv']
    assert (program, no_pyc, script) == ('python', '-B', 'scripts/relief/region.py')
    assert cli.main(shots_argv) == 0 and seen == ['shots']


def _refusal(args, capsys, reason):
    with pytest.raises(SystemExit) as exc:
        request.main(args)
    assert exc.value.code == 2
    out, err = capsys.readouterr()
    assert not out and reason in err


def test_refuses_valid_envelope_from_other_region(candidate, capsys):
    """Catch checking only hash validity, not the region the verified release describes."""
    data = candidate(region='big-sur-coast')
    assert envelope.verify_artifacts(data[1]).release['region'] == 'big-sur-coast'
    _refusal(_args(data), capsys, 'envelope belongs to another region')


def test_refuses_center_outside_release_bounds(candidate, capsys):
    """Catch emitting a region-valid center that the screenshot consumer would reject."""
    data = candidate(bounds=[-122.35, 36.3, -122, 36.625])
    _refusal(_args(data), capsys, 'center is outside release bounds')


def test_refuses_unknown_camera(candidate, capsys):
    """Catch silently choosing a default for a mistyped ID."""
    _refusal(_args(candidate(), 'not-configured'), capsys, 'unknown camera')


@pytest.mark.parametrize(('duplicate', 'reason'), [
    (False, 'center is outside region bounds'),
    (True, 'duplicate render config previews id'),
])
def test_refuses_invalid_configured_camera(duplicate, reason, candidate, tmp_path, monkeypatch, capsys):
    """Catch trusting recipe centers or silently picking one of two records with the same ID."""
    config = tmp_path / 'render-override'
    recipe = f'regions/{REGION}/render.json'
    doc = json.loads((ROOT / recipe).read_bytes())
    if duplicate:
        doc['previews'].append(doc['previews'][0].copy())
    else:
        doc['previews'][0]['center'] = [-121.888, 38.123456789]
    _json(config / recipe, doc)
    for name in (f'regions/{REGION}/region.json', 'schemas/sc-render-v1.schema.json', 'style/index.json'):
        dest = config / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        copyfile(ROOT / name, dest)
    monkeypatch.setattr(request, 'repo_root', lambda: config)
    monkeypatch.setattr(render_config, 'repo_root', lambda: config)
    # The remote center is inside this synthetic release, but not inside the
    # real region, so the region guard (not the release guard) must refuse it.
    data = candidate(bounds=[-122.35, 36.3, -121.65, 39])
    _refusal(_args(data), capsys, reason)


def test_refuses_envelope_under_different_out(candidate, tmp_path, capsys):
    """Catch showing expected hashes for one OUT while targeting another."""
    _, *inputs = candidate()
    other_out = tmp_path / 'other-out'
    other_out.mkdir()
    _refusal(_args((other_out, *inputs)), capsys, 'envelope must be under the explicit OUT')
