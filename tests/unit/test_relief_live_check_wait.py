"""C1–C3: drive the bounded wait through the live-check loopback fixture."""
import json
import subprocess
import sys

import pytest

from skippercast.relief import live_check
from tests._support import ROOT
from tests.unit.test_relief_live_check import (
    CONTOURS, POINTER, argv, commit, encoded, git, report, row, trace, verified,
)

pytest_plugins = ('tests.unit.test_relief_live_check',)


def serve_commit(site, sha):
    site.responses['deploy.json'] = 200, {}, encoded({'commit': sha})


@pytest.mark.parametrize('polls, interval, seconds, commit_name, reason, total', [
    pytest.param(12, [], 300, 'deployed', 'ancestor', 20, id='C1: last poll at the budget limit; C3: default sleep'),
    pytest.param(2, ['--interval', '30'], 30, 'merge', 'equal', 10, id='C1: equal on last poll; C3: minimum interval'),
    pytest.param(2, ['--interval', '600'], 600, 'deployed', 'ancestor', 10, id='C1: descendant; C3: maximum interval'),
])
def test_C1_only_deploy_until_ready(checkout, release, site, polls, interval, seconds, commit_name, reason, total):
    """C1: Premature asset reads, polling past readiness or losing the contours slot breaks the trace."""
    deployed = getattr(checkout, commit_name)
    serve_commit(site, checkout.stale)
    sleeps = []

    def advance(delay):
        sleeps.append((delay, list(site.requests)))
        if len(sleeps) == polls - 1:
            serve_commit(site, deployed)

    assert live_check.main([*argv(checkout, site), '--wait', str(polls), *interval], sleeper=advance) == 0
    assert sleeps == [(seconds, trace(*['deploy.json'] * i)) for i in range(1, polls)]
    assert site.requests == trace(*['deploy.json'] * (polls + 1), POINTER, release.archive,
                                  release.root, *release.chunks, CONTOURS)
    assert json.loads(checkout.report.read_bytes()) == report(
        checkout, site, deployed, verified(release, reason) + [row('contours', 'none-merged', key=CONTOURS)],
        'PASS', total)


def test_C1_wait_refetches_history_for_descendant_that_appears_mid_wait(checkout, release, site):
    """C1: A snapshot taken before the wait would call a later descendant unknown-commit, not the reviewed merge."""
    serve_commit(site, checkout.stale)
    descendants = []

    def advance(delay):
        (checkout.origin / 'notes').write_text('landed during the wait')
        descendants.append(commit(checkout.origin, 'Descendant deployed during the wait'))
        serve_commit(site, descendants[0])

    assert live_check.main([*argv(checkout, site), '--wait', '2'], sleeper=advance) == 0
    assert len(descendants) == 1 and descendants[0] not in (checkout.deployed, checkout.merge)
    assert json.loads(checkout.report.read_bytes()) == report(
        checkout, site, descendants[0], verified(release, 'ancestor') + [row('contours', 'none-merged', key=CONTOURS)],
        'PASS', 10)


def test_C1_cli_dispatch_waits_once_when_already_deployed(checkout, release, site):
    """C1: The region command must accept the minimum poll count and proceed on the first hit."""
    result = subprocess.run([sys.executable, str(ROOT / 'scripts/relief/region.py'), 'live-check',
                             *argv(checkout, site), '--wait', '1'], check=False, capture_output=True,
                            text=True, timeout=15)
    assert (result.returncode, result.stdout, result.stderr) == (0, '', '')
    assert site.requests == trace('deploy.json', 'deploy.json', POINTER, release.archive,
                                  release.root, *release.chunks, CONTOURS)
    assert json.loads(checkout.report.read_bytes()) == report(
        checkout, site, checkout.deployed, verified(release) + [row('contours', 'none-merged', key=CONTOURS)],
        'PASS', 9)


def test_C1_budget_refusal_counts_every_zoom_and_contours(checkout, release, site, capsys):
    """C1: Twelve polls fit two zooms but not three; fail before contacting the site."""
    (checkout.repo / POINTER).write_bytes(encoded(dict(release.pointer, maxzoom=10)))
    commit(checkout.repo, 'Review wider zoom range')
    assert live_check.main([*argv(checkout, site), '--wait', '12'], sleeper=pytest.fail) == 2
    assert capsys.readouterr().err == 'region.py live-check: --wait 12 exceeds the 11-poll budget for this release\n'
    assert (site.requests, checkout.out.exists()) == ([], False)


@pytest.mark.parametrize('option, value', [
    pytest.param('--wait', '0', id='C1: below minimum polls'),
    pytest.param('--wait', '13', id='C1: above maximum polls'),
    pytest.param('--wait', '1.5', id='C1: noninteger polls'),
    pytest.param('--interval', '29', id='C1: below minimum interval'),
    pytest.param('--interval', '601', id='C1: above maximum interval'),
    pytest.param('--interval', '1m', id='C1: noninteger interval'),
])
def test_C1_argument_refusal(checkout, site, option, value):
    """C1: Bad bounds or units are usage errors, not a receipt or a network attempt."""
    wait_args = ['--wait', '1'] if option == '--interval' else []
    with pytest.raises(SystemExit) as exc:
        live_check.main([*argv(checkout, site), *wait_args, option, value], sleeper=pytest.fail)
    assert (type(exc.value), exc.value.code, site.requests, checkout.out.exists()) == (SystemExit, 2, [], False)


def test_C2_exhausted_wait_reports_only_not_deployed(checkout, site):
    """C2: Three old builds must yield one not-deployed reason, not stale or an extra poll."""
    serve_commit(site, checkout.stale)
    sleeps = []
    assert live_check.main([*argv(checkout, site), '--wait', '3'], sleeper=sleeps.append) == 1
    assert (site.requests, sleeps) == (trace('deploy.json', 'deploy.json', 'deploy.json'), [300, 300])
    assert json.loads(checkout.report.read_bytes()) == report(
        checkout, site, checkout.stale, [row('deploy', 'not-deployed', fail=True)], 'FAIL', 4)


@pytest.mark.parametrize('reason', [
    pytest.param('diverged', id='C2: stop immediately on divergent history'),
    pytest.param('unknown-commit', id='C2: unknown ancestry is not a proven old deploy'),
    pytest.param('missing', id='C2: missing receipt is not a proven old deploy'),
    pytest.param('invalid', id='C2: malformed receipt is not a proven old deploy'),
    pytest.param('http-503', id='C2: transport failure is not a proven old deploy'),
])
def test_C2_does_not_label_other_failures_not_deployed(checkout, site, reason):
    """C2: Waiting on any FAIL would burn polls and hide the actual deployment failure."""
    deployed = None
    if reason == 'diverged':
        git(checkout.repo, 'switch', '-c', 'unrelated', checkout.stale)
        (checkout.repo / 'notes').write_text('fixture divergent deployment')
        deployed = commit(checkout.repo, 'Diverged')
        git(checkout.repo, 'switch', 'main')
    if reason == 'unknown-commit':
        deployed = 'f' * 40
    if deployed is not None:
        serve_commit(site, deployed)
    else:
        site.responses['deploy.json'] = {
            'missing': (404, {}, b''), 'invalid': (200, {}, b'{'), 'http-503': (503, {}, b''),
        }[reason]
    assert live_check.main([*argv(checkout, site), '--wait', '3'], sleeper=pytest.fail) == 1
    assert site.requests == trace('deploy.json')
    assert json.loads(checkout.report.read_bytes()) == report(
        checkout, site, deployed, [row('deploy', reason, fail=True)], 'FAIL', 2)


def test_C2_rollback_after_ready_poll_remains_stale(checkout, site, monkeypatch):
    """C2: Reusing the ready poll could certify a deployment that has since rolled back."""
    real_metadata = live_check.Site.metadata

    def roll_back(transport, key):
        body = real_metadata(transport, key)
        if site.requests == trace('deploy.json'):
            serve_commit(site, checkout.stale)
        return body

    monkeypatch.setattr(live_check.Site, 'metadata', roll_back)
    assert live_check.main([*argv(checkout, site), '--wait', '3'], sleeper=pytest.fail) == 1
    assert site.requests == trace('deploy.json', 'deploy.json')
    assert json.loads(checkout.report.read_bytes()) == report(
        checkout, site, checkout.stale, [row('deploy', 'stale', fail=True)], 'FAIL', 3)


def test_C3_no_wait_retains_the_single_stale_check(checkout, site):
    """C3: Applying the wait branch by default would relabel stale or send extra probes."""
    serve_commit(site, checkout.stale)
    assert live_check.main(argv(checkout, site), sleeper=pytest.fail) == 1
    assert site.requests == trace('deploy.json')
    assert json.loads(checkout.report.read_bytes()) == report(
        checkout, site, checkout.stale, [row('deploy', 'stale', fail=True)], 'FAIL', 2)
