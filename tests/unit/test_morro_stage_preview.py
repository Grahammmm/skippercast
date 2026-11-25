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


def test_resource_bindings_outside_the_safe_set_are_dropped_not_carried():
    # Contract: only the reviewed safe keys survive. Bug caught: a denylist that misses a binding type
    # (here KV with a production namespace id) lets the stage Worker read or write a production store.
    base = preview.read_wrangler(base_text())
    base['kv_namespaces'] = [{'binding': 'KV', 'id': 'f' * 32}]
    base['vectorize'] = [{'binding': 'V', 'index_name': 'production'}]
    config = preview.stage_config(base, worker='skippercast-morro-stage', bucket='skippercast-feeds-stage')
    assert set(config) <= preview.SAFE_KEYS
    assert 'kv_namespaces' not in config and 'vectorize' not in config and 'ratelimits' not in config


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
    lambda c: c.update(kv_namespaces=[{'binding': 'KV', 'id': 'f' * 32}]),
    lambda c: c.update(hyperdrive=[{'binding': 'HD', 'id': 'f' * 32}]),
    lambda c: c.update(ratelimits=[{'name': 'PUBLIC_LIMITER', 'namespace_id': '1001'}]),
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
    # Contract: the build inputs are exactly the candidate. Bug caught: an untracked source file
    # (not ignored) passes the clean check and is built in while the receipt names only the commit.
    git(repo, 'checkout', '--', preview.POINTER)
    (repo / 'server').mkdir()
    (repo / 'server' / 'extra.ts').write_text('export const x = 1\n')
    with pytest.raises(preview.PreviewError, match='untracked'):
        preview.plan(repo, second, base_text(), pointer_sha256=digest, **kwargs)


def _planned(repo, sha, digest):
    return preview.plan(repo, sha, base_text(), pointer_sha256=digest,
                        worker='skippercast-morro-stage', bucket='skippercast-feeds-stage')


@pytest.mark.parametrize('hide', ['server/extra.ts', 'server/gen/extra.ts', 'dist/client-extra.js', 'web/node_modules.ts'])
def test_ignored_source_files_cannot_hide_from_the_clean_check(repo, hide):
    # Contract: build inputs are exactly the candidate. Bug caught: a file hidden by .git/info/exclude
    # (or a global ignore) is invisible to `git status`, so it was built in under the reviewed commit.
    sha, data = commit_pointer(repo, POINTER, 'reviewed')
    digest = preview._sha256(data)
    (repo / '.git' / 'info' / 'exclude').write_text('/' + hide + '\n')
    path = repo / hide
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('export const x = 1\n')
    assert git(repo, 'status', '--porcelain', '--untracked-files=all') == ''
    assert git(repo, 'check-ignore', '--', hide) == hide
    with pytest.raises(preview.PreviewError, match='ignored or hidden'):
        _planned(repo, sha, digest)


def test_dependency_and_build_output_do_not_block_a_clean_candidate(repo):
    # Control: only bounded generated paths (.gitignore'd dependencies and build output) are allowed.
    _, data = commit_pointer(repo, POINTER, 'reviewed')
    digest = preview._sha256(data)
    (repo / '.gitignore').write_text('node_modules/\ndist/client/\ndist/server/\n__pycache__/\n')
    git(repo, 'add', '--', '.gitignore')
    git(repo, 'commit', '-q', '-m', 'ignore build output')
    sha = git(repo, 'rev-parse', 'HEAD')
    for generated in ('node_modules/pkg/index.js', 'dist/client/app.js', 'dist/server/index.js',
                      'scripts/__pycache__/x.pyc'):
        path = repo / generated
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('generated\n')
    assert _planned(repo, sha, digest)[1]['commit'] == sha


def test_index_hidden_edits_to_tracked_files_are_refused(repo):
    # Bug caught: `update-index --skip-worktree` hides an edited tracked file from `git status`.
    sha, data = commit_pointer(repo, POINTER, 'reviewed')
    digest = preview._sha256(data)
    git(repo, 'update-index', '--skip-worktree', '--', preview.POINTER)
    (repo / preview.POINTER).write_text('{}')
    assert git(repo, 'status', '--porcelain') == ''
    with pytest.raises(preview.PreviewError, match='ignored or hidden'):
        _planned(repo, sha, digest)


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
