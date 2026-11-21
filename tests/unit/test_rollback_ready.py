"""Exercise the rollback readiness CLI with local Git history and a loopback site."""
import json
import os
import subprocess
import sys
from types import SimpleNamespace

import pytest

from scripts.relief import rollback_ready
from tests._support import ROOT
from tests.unit.test_relief_live_archive import SELECTED, Site, release as synthetic_release, row
from tests.unit.test_relief_live_check import commit, git, site, trace

REGION = 'fixture-bay'
POINTER = f'catalog/relief/{REGION}.json'
SCRIPT = ROOT / 'scripts/relief/rollback_ready.py'
REMOVAL = 'rollback: removes relief (no earlier release)'


@pytest.fixture
def release(synthetic_release):
    """Adapt the shared synthetic release to the live-check HTTP fixture."""
    return Site(synthetic_release)


@pytest.fixture
def checkout(tmp_path, release, request):
    repo = tmp_path / 'repo'
    repo.mkdir()
    git(repo, 'init', '--initial-branch=main')
    (repo / 'notes').write_text('Before any relief release')
    commit(repo, 'Initial')
    path = repo / POINTER
    path.parent.mkdir(parents=True)
    reviewed = dict(release.pointer, schema='sc-relief-pointer/1', status='reviewed', private=False,
                    generation='a' * 64, release_sha256='b' * 64, envelope_sha256='c' * 64,
                    previous=None, bounds=[-121, 35, -120, 36],
                    sources=[dict(id='synthetic', label='Synthetic', attribution='Fixture',
                                  vertical_datum='Fixture', survey_dates=['2000'],
                                  rights_class='public',
                                  rights=dict(public_display='allowed', license='Fixture'))],
                    detail_summary=dict(mask='transparent-nodata', depth_bands=[
                        dict(source_id='synthetic', min_depth_m=0, max_depth_m=10, resolution_m=5)]),
                    native_support_by_zoom={'8': dict(tiles=3, sources=[])})
    mode = getattr(request, 'param', 'two')
    target = dict(reviewed)
    if mode == 'invalid':
        del target['release_sha256']  # Invalid by schema alone, not used by check_archive.
    path.write_text(json.dumps(target))
    commit(repo, 'First release')
    if mode != 'first':
        # Neither the current archive nor its lineage hint points to the served object.
        path.write_text(json.dumps(dict(reviewed, sha256='d' * 64, generation='e' * 64,
                                        previous={k: reviewed[k] for k in (
                                            'generation', 'release_sha256', 'envelope_sha256', 'sha256'
                                        )} | {'sha256': 'f' * 64})))
        commit(repo, 'Second release')
        (repo / 'notes').write_text('Unrelated change after second release')
        commit(repo, 'Later HEAD')
    return SimpleNamespace(repo=repo, deployed=git(repo, 'rev-parse', 'HEAD'))


def argv(checkout, site):
    return ['--repo', str(checkout.repo), '--region', REGION, '--base', site.base + '/']


def run(*args, env=None):
    return subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True,
                          text=True, env=env, timeout=30, check=False)


def expected_text(rows, verdict):
    return ''.join(f"{r['status']} {r['check']} {r['key']}\n" for r in rows) + verdict + '\n'


def expected_keys(release):
    return [release.archive, release.root, *(release.prefix + p for p in SELECTED)]


@pytest.mark.parametrize('checkout', ['first'], indirect=True)
@pytest.mark.parametrize('as_json', [False, True])
def test_C1_first_release_never_contacts_site(checkout, site, as_json):
    """C1: Checking current HEAD instead of the rollback state makes a needless request."""
    result = run(*argv(checkout, site), *(['--json'] if as_json else []))
    expected = json.dumps(dict(checks=[], verdict='PASS', message=REMOVAL)) if as_json else REMOVAL
    assert (result.returncode, result.stdout, result.stderr, site.requests) == (0, expected + '\n', '', [])


def test_C2_reports_all_rows_for_the_served_git_target(checkout, site, release):
    """C2: Following HEAD, HEAD^ or pointer lineage would request a different archive."""
    result = run(*argv(checkout, site))
    expected = expected_text(release.expected_rows(), 'rollback-ready: PASS')
    assert (result.returncode, result.stdout, result.stderr) == (0, expected, '')
    assert site.requests == trace(*expected_keys(release))


@pytest.mark.parametrize('reason', ['missing', 'sha256', 'redirect'])
def test_C2_archive_refusals(checkout, site, release, reason):
    """C2: A missing object, a same-size substitution, or a redirect must not pass."""
    if reason == 'missing':
        del site.responses[release.archive]
    elif reason == 'sha256':
        body = release.objects[release.archive]
        site.responses[release.archive] = 200, {}, body[:-1] + bytes([body[-1] ^ 1])
    else:
        site.responses[release.archive] = 302, {'Location': site.base + '/redirected'}, b''
    result = run(*argv(checkout, site), '--json')
    failure = row('fetch' if reason == 'redirect' else 'archive', release.archive, reason)
    assert (result.returncode, json.loads(result.stdout), result.stderr) == (
        1, {'checks': [failure], 'verdict': 'FAIL'}, '')
    assert site.requests == trace(release.archive)


@pytest.mark.parametrize('checkout', ['invalid'], indirect=True)
def test_C2_validates_historical_pointer_before_http(checkout, site):
    """C2: A valid current pointer cannot substitute for validating the historical one."""
    result = run(*argv(checkout, site))
    assert (result.returncode, result.stdout, result.stderr, site.requests) == (
        1, 'FAIL pointer invalid\nrollback-ready: FAIL pointer invalid\n', '', [])


def test_C2_caps_archive_verifier_and_reports_partial_proof(checkout, site, release, monkeypatch, capsys):
    """C2: Ignoring the Site counter or a later failed row can falsely certify a partial proof."""
    site_class = rollback_ready.live_check.Site
    check_archive = rollback_ready.live_archive.check_archive

    def nearly_spent(base):
        assert base == 'https://skippercast.com'
        transport = site_class(site.base)
        transport.requests = 18
        return transport

    def check(pointer, fetch, *, budget):
        assert budget == 2
        return check_archive(pointer, fetch, budget=budget)

    monkeypatch.setattr(rollback_ready.live_check, 'Site', nearly_spent)
    monkeypatch.setattr(rollback_ready.live_archive, 'check_archive', check)
    assert rollback_ready.main(['--repo', str(checkout.repo), '--region', REGION]) == 1
    expected = expected_text(release.expected_rows()[:2],
                             f'FAIL chunk {release.prefix}{SELECTED[0]} budget\nrollback-ready: FAIL chunk budget')
    assert capsys.readouterr() == (expected, '')
    assert site.requests == trace(release.archive, release.root)


def test_C3_served_whole_leaves_repo_and_scratch_unchanged(checkout, site, release, tmp_path):
    """C3: Even a successful re-index must not write to Git or leave persistent output."""
    scratch = tmp_path / 'scratch'
    scratch.mkdir()
    repo = checkout.repo
    head = (repo / '.git/HEAD').read_bytes()
    index = (repo / '.git/index').read_bytes()
    refs = git(repo, 'show-ref', '--head')
    result = run(*argv(checkout, site), '--json', env={**os.environ, 'TMPDIR': str(scratch)})
    assert (result.returncode, json.loads(result.stdout), result.stderr) == (
        0, dict(checks=release.expected_rows(), verdict='PASS'), '')
    assert ((repo / '.git/HEAD').read_bytes(), (repo / '.git/index').read_bytes(),
            git(repo, 'show-ref', '--head'), git(repo, 'status', '--porcelain')) == (head, index, refs, '')
    assert list(scratch.iterdir()) == []
    assert site.requests == trace(*expected_keys(release))


def test_C3_refuses_scratch_inside_repo(checkout, site):
    """C3: Inherited TMPDIR must not cause even temporary checkout writes."""
    result = run(*argv(checkout, site), '--json', env={**os.environ, 'TMPDIR': str(checkout.repo)})
    assert (result.returncode, json.loads(result.stdout), result.stderr, site.requests) == (
        1, dict(checks=[dict(check='scratch', status='FAIL', reason='temporary directory must be outside --repo')],
                verdict='FAIL'), '', [])


def test_C3_refuses_missing_history(checkout, site):
    """C3: An unknown region is not evidence of a first release."""
    result = run(*argv(checkout, site), '--region', 'absent')
    assert (result.returncode, result.stdout, result.stderr, site.requests) == (
        1, 'FAIL history no catalog history for region absent\n'
        'rollback-ready: FAIL history no catalog history for region absent\n', '', [])


@pytest.mark.parametrize('args, message', [
    ([], 'the following arguments are required: --repo, --region'),
    (['--repo', '.', '--region', REGION, '--base', 'http://example.test/path'],
     'argument --base: --base must be an HTTP(S) origin without credentials'),
])
def test_C3_usage_is_distinct_from_a_failed_release_check(args, message):
    """C3: Malformed invocation is an argparse error, not a readiness verdict."""
    result = run(*args)
    assert (result.returncode, result.stdout, result.stderr.splitlines()[-1]) == (
        2, '', f'rollback_ready.py: error: {message}')
