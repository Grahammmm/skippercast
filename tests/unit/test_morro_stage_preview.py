import json
import subprocess

import pytest

from scripts.relief import morro_stage_preview as preview
from tests._support import ROOT

POINTER = {'schema': 'sc-relief-pointer/1', 'region': 'morro-bay', 'generation': 'a' * 64}


def git(repo, *args):
    return subprocess.run(['git', '-C', str(repo), '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid',
                           '-c', 'commit.gpgsign=false', *args], check=True, capture_output=True, text=True).stdout.strip()


def commit_pointer(repo, doc, message):
    path = repo / preview.POINTER
    path.parent.mkdir(parents=True, exist_ok=True)
    data = (json.dumps(doc, sort_keys=True) + '\n').encode()
    path.write_bytes(data)
    git(repo, 'add', '--', preview.POINTER)
    git(repo, 'commit', '-q', '-m', message)
    return git(repo, 'rev-parse', 'HEAD'), data


@pytest.fixture
def repo(tmp_path):
    repo = tmp_path / 'candidate'
    repo.mkdir()
    git(repo, 'init', '-q')
    return repo


def base_text():
    return (ROOT / 'wrangler.jsonc').read_text(encoding='utf-8')


def test_stage_config_from_the_real_production_config_has_no_production_reach():
    config = preview.stage_config(preview.read_wrangler(base_text()), worker='skippercast-morro-stage',
                                  bucket='skippercast-feeds-stage')
    assert config['name'] == 'skippercast-morro-stage'
    assert config['workers_dev'] is True
    assert config['r2_buckets'] == [{'binding': 'FEEDS', 'bucket_name': 'skippercast-feeds-stage'}]
    for key in ('routes', 'triggers', 'queues', 'd1_databases'):
        assert key not in config
    assert config['vars']['IDENTITY_PROVIDER'] == 'none'
    assert 'BOAT_LOOKUP_ENABLED' not in config['vars']
    # The site itself is still built and served.
    assert config['main'] == 'dist/server/index.js' and config['assets']['directory'] == 'dist/client'


def test_production_extras_added_by_the_deploy_are_stripped():
    base = preview.read_wrangler(base_text())
    base['routes'] = [{'pattern': 'skippercast.com', 'custom_domain': True}]
    base['queues'] = {'producers': [{'binding': 'Q', 'queue': 'skippercast-trip-checks'}]}
    base['r2_buckets'].append({'binding': 'ADVISOR_MEDIA', 'bucket_name': 'skippercast-advisor-media'})
    config = preview.stage_config(base, worker='skippercast-morro-stage', bucket='skippercast-feeds-stage')
    assert 'routes' not in config and 'queues' not in config
    assert [b['bucket_name'] for b in config['r2_buckets']] == ['skippercast-feeds-stage']


@pytest.mark.parametrize('worker, bucket', [
    ('skippercast', 'skippercast-feeds-stage'),
    ('skippercast-morro', 'skippercast-feeds-stage'),
    ('skippercast-morro-stage', 'skippercast-feeds'),
    ('skippercast-morro-stage', 'skippercast-backups'),
])
def test_production_worker_or_bucket_names_are_refused(worker, bucket):
    with pytest.raises(preview.PreviewError):
        preview.stage_config(preview.read_wrangler(base_text()), worker=worker, bucket=bucket)


@pytest.mark.parametrize('mutate', [
    lambda c: c.update(name='skippercast'),
    lambda c: c.update(routes=[{'pattern': 'skippercast.com', 'custom_domain': True}]),
    lambda c: c.update(triggers={'crons': ['*/15 * * * *']}),
    lambda c: c.update(d1_databases=[{'binding': 'DB', 'database_name': 'skippercast'}]),
    lambda c: c.update(queues={'consumers': [{'queue': 'skippercast-trip-checks'}]}),
    lambda c: c.update(workers_dev=False),
    lambda c: c['r2_buckets'].append({'binding': 'X', 'bucket_name': 'skippercast-feeds'}),
    lambda c: c['r2_buckets'][0].update(preview_bucket_name='skippercast-feeds'),
    lambda c: c['vars'].update(IDENTITY_PROVIDER='skippercast'),
])
def test_refuse_production_catches_each_path_back_to_production(mutate):
    config = preview.stage_config(preview.read_wrangler(base_text()), worker='skippercast-morro-stage',
                                  bucket='skippercast-feeds-stage')
    preview.refuse_production(config)
    mutate(config)
    with pytest.raises(preview.PreviewError):
        preview.refuse_production(config)


def test_comment_inside_a_value_line_fails_closed():
    with pytest.raises(preview.PreviewError):
        preview.read_wrangler('{"name": "skippercast" // trailing\n}')


def test_plan_binds_the_exact_commit_and_reviewed_pointer(repo, tmp_path):
    sha, data = commit_pointer(repo, POINTER, 'candidate')
    digest = preview._sha256(data)
    out = tmp_path / 'out'
    rc = preview.main(['plan', '--tree', str(repo), '--sha', sha, '--pointer-sha256', digest,
                       '--wrangler', str(ROOT / 'wrangler.jsonc'), '--out', str(out)])
    assert rc == 0
    receipt = json.loads((out / 'plan.json').read_text())
    config_bytes = (out / 'wrangler.stage.json').read_bytes()
    assert receipt['commit'] == sha and receipt['pointer_sha256'] == digest
    assert receipt['contours_sha256'] is None
    assert receipt['config_sha256'] == preview._sha256(config_bytes)
    preview.refuse_production(json.loads(config_bytes))


def test_plan_refuses_wrong_commit_dirty_tree_and_unreviewed_pointer(repo):
    first, data = commit_pointer(repo, POINTER, 'reviewed')
    digest = preview._sha256(data)
    second, _ = commit_pointer(repo, dict(POINTER, generation='b' * 64), 'later')
    kwargs = dict(worker='skippercast-morro-stage', bucket='skippercast-feeds-stage')
    with pytest.raises(preview.PreviewError, match='not the candidate commit'):
        preview.plan(repo, first, base_text(), pointer_sha256=digest, **kwargs)
    with pytest.raises(preview.PreviewError, match='not the reviewed pointer'):
        preview.plan(repo, second, base_text(), pointer_sha256=digest, **kwargs)
    (repo / preview.POINTER).write_text('{}')
    with pytest.raises(preview.PreviewError, match='uncommitted'):
        preview.plan(repo, second, base_text(), pointer_sha256=digest, **kwargs)


def test_plan_refuses_a_candidate_without_a_morro_pointer(repo):
    sha, data = commit_pointer(repo, dict(POINTER, region='fixture-bay'), 'wrong region')
    with pytest.raises(preview.PreviewError, match='not for Morro Bay'):
        preview.plan(repo, sha, base_text(), pointer_sha256=preview._sha256(data),
                     worker='skippercast-morro-stage', bucket='skippercast-feeds-stage')
    (repo / preview.POINTER).unlink()
    git(repo, 'commit', '-qam', 'remove pointer')
    head = git(repo, 'rev-parse', 'HEAD')
    with pytest.raises(preview.PreviewError, match='has no'):
        preview.plan(repo, head, base_text(), pointer_sha256='0' * 64,
                     worker='skippercast-morro-stage', bucket='skippercast-feeds-stage')


def test_verify_requires_the_exact_commit_and_pointer_not_an_ancestor(repo, tmp_path):
    older, _ = commit_pointer(repo, dict(POINTER, generation='b' * 64), 'older')
    sha, data = commit_pointer(repo, POINTER, 'candidate')
    _, receipt = preview.plan(repo, sha, base_text(), pointer_sha256=preview._sha256(data),
                              worker='skippercast-morro-stage', bucket='skippercast-feeds-stage')
    reasons = lambda checks: [(c['check'], c['status'], c['reason']) for c in checks]
    assert reasons(preview.verify(receipt, {'commit': sha}, data)) == [
        ('deploy', 'PASS', 'exact'), ('pointer', 'PASS', 'exact')]
    assert reasons(preview.verify(receipt, {'commit': older}, data))[0] == ('deploy', 'FAIL', 'other-commit')
    assert reasons(preview.verify(receipt, {'commit': sha}, data + b' '))[1] == ('pointer', 'FAIL', 'differs')
    assert reasons(preview.verify(receipt, {'commit': sha}, None))[1] == ('pointer', 'FAIL', 'missing')
    assert reasons(preview.verify(receipt, {'commit': sha.upper()}, data))[0] == ('deploy', 'FAIL', 'unreadable')
    assert reasons(preview.verify(receipt, ['not', 'an', 'object'], data))[0] == ('deploy', 'FAIL', 'unreadable')
    plan_path = tmp_path / 'plan.json'
    plan_path.write_text(json.dumps(receipt))
    deploy = tmp_path / 'deploy.json'
    deploy.write_text(json.dumps({'commit': older}))
    served = tmp_path / 'pointer.json'
    served.write_bytes(data)
    argv = ['verify', '--plan', str(plan_path), '--deploy-json', str(deploy), '--pointer', str(served)]
    assert preview.main(argv) == 1
    deploy.write_text(json.dumps({'commit': sha}))
    assert preview.main(argv) == 0
