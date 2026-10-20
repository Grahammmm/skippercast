"""Require a main commit with successful push/main CI, never older than production.

The deploy workflow's source job selects the newest first-parent main commit whose
latest push/main Offline checks run succeeded. This check runs on that selected
commit (DEPLOY_SHA) after checkout and again immediately before production writes:
the commit must be current main or an ancestor of it, and the latest exact-SHA
push/main Offline checks run must have succeeded.

The workflow runs this file from its own revision (the "controller"), not from the
candidate checkout, so a newer controller can deploy an older candidate. With
DEPLOY_TREE set, the checkout there must be exactly DEPLOY_SHA.

With --production it also compares the selected commit with the commit production
serves and writes hold=true|false and reason=... to GITHUB_OUTPUT. The workflow
passes PRODUCTION_STATE: "unconfigured" (no Cloudflare credentials: the deploy
script writes nothing), "known" (PRODUCTION_SHA is the traced live commit) or
anything else, which means the live commit could not be traced (PRODUCTION_REASON
says why). A deploy is held, not failed, when production's commit is unknown, or
production already serves that commit or a newer one. A manual dispatch may
redeploy the commit production serves (to apply changed variables or secrets),
but never an older one, and never over an unknown production.

Reads public GitHub metadata, sending only the workflow's read-only token
(SOURCE_READ_TOKEN, `github.token` under `contents: read`) when it is set, so the
shared runners' anonymous rate limit cannot fail a deploy. Network/metadata failures stop
before dependency execution or production writes. This is a workflow source
check, not an access-control boundary against repository administrators.
"""
import json
import os
import re
import subprocess
import sys
from urllib.parse import urlencode
from urllib.error import HTTPError
from urllib.request import HTTPRedirectHandler, Request, build_opener


class RefuseRedirect(HTTPRedirectHandler):
    """No metadata redirect is followed: urllib would copy Authorization to any target, another host or plain HTTP included."""
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise HTTPError(newurl, code, 'deploy source metadata redirect refused', headers, fp)


_OPENER = build_opener(RefuseRedirect)
_SHA = re.compile(r'[0-9a-f]{40}')


def urlopen(request, timeout):
    return _OPENER.open(request, timeout=timeout)


class SourceError(ValueError):
    """The selected source has not established the deployment contract."""


def public_metadata(path):
    headers = {
        'Accept': 'application/vnd.github+json',
        'X-GitHub-Api-Version': '2026-03-10',
        'User-Agent': 'SkipperCast-deploy-source-check',
    }
    if os.environ.get('SOURCE_READ_TOKEN'):
        headers['Authorization'] = 'Bearer ' + os.environ['SOURCE_READ_TOKEN']
    request = Request('https://api.github.com' + path, headers=headers)
    with urlopen(request, timeout=15) as response:
        return json.load(response)


def is_sha(value):
    return isinstance(value, str) and _SHA.fullmatch(value) is not None


def compare(repository, base, head, read):
    """GitHub's status of head against base; 'ahead' means base is a strict ancestor of head."""
    doc = read('/repos/' + repository + '/compare/' + base + '...' + head + '?per_page=1')
    status = doc.get('status') if isinstance(doc, dict) else None
    behind = doc.get('behind_by') if isinstance(doc, dict) else None
    if (status not in ('identical', 'ahead', 'behind', 'diverged') or not isinstance(behind, int)
            or isinstance(behind, bool) or (status in ('identical', 'ahead')) != (behind == 0)):
        raise SourceError('commit comparison metadata is missing or invalid')
    return status


def verify_source(repository, ref, sha, read=public_metadata):
    if ref != 'refs/heads/main':
        raise SourceError('deployment requires refs/heads/main')
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9-]*/[A-Za-z0-9][A-Za-z0-9_.-]*', repository or ''):
        raise SourceError('invalid repository identity')
    if not is_sha(sha):
        raise SourceError('invalid deployment SHA')
    base = '/repos/' + repository
    main = read(base + '/git/ref/heads/main')
    if not isinstance(main, dict) or main.get('ref') != ref:
        raise SourceError('main ref metadata is missing or invalid')
    obj = main.get('object')
    if not isinstance(obj, dict) or obj.get('type') != 'commit' or not is_sha(obj.get('sha')):
        raise SourceError('main commit metadata is missing or invalid')
    # Current main or an ancestor of it: a commit that is not on main is never deployed.
    if obj['sha'] != sha and compare(repository, sha, obj['sha'], read) != 'ahead':
        raise SourceError('selected SHA is not current main or an ancestor of it')
    query = urlencode({'event': 'push', 'branch': 'main', 'head_sha': sha, 'per_page': 100})
    listing = read(base + '/actions/workflows/ci.yml/runs?' + query)
    if not isinstance(listing, dict):
        raise SourceError('CI run metadata is missing or invalid')
    runs, count = listing.get('workflow_runs'), listing.get('total_count')
    if (not isinstance(runs, list) or not isinstance(count, int) or isinstance(count, bool)
            or not 0 < count <= 100 or len(runs) != count):
        raise SourceError('exact-SHA CI listing is empty, incomplete or invalid')
    for run in runs:
        if (not isinstance(run, dict) or not isinstance(run.get('id'), int)
                or isinstance(run.get('id'), bool) or run['id'] <= 0):
            raise SourceError('invalid CI run identity')
    # A newer failed/pending rerun must not be hidden by an older green run.
    latest = max(runs, key=lambda run: run['id'])
    origin = latest.get('head_repository')
    if (latest.get('path') != '.github/workflows/ci.yml'
            or latest.get('name') != 'Offline checks'
            or latest.get('event') != 'push' or latest.get('head_branch') != 'main'
            or latest.get('head_sha') != sha or not isinstance(origin, dict)
            or origin.get('full_name') != repository
            or latest.get('status') != 'completed' or latest.get('conclusion') != 'success'):
        raise SourceError('latest exact-SHA push/main Offline checks has not succeeded')
    return latest['id']


def verify_checkout(tree, sha, run=subprocess.run):
    """The candidate checkout at tree must be exactly sha: a moved or substituted tree is never deployed."""
    try:
        head = run(['git', '-C', tree, 'rev-parse', '--verify', 'HEAD^{commit}'], capture_output=True, text=True,
                   timeout=30, check=False)
    except (OSError, subprocess.SubprocessError) as error:
        raise SourceError('the candidate checkout could not be read: ' + str(error)) from None
    if head.returncode != 0 or head.stdout.strip() != sha:
        raise SourceError('the candidate checkout is ' + (head.stdout.strip() or 'unreadable') + ', not ' + sha)


def production_hold(repository, sha, production, event, read=public_metadata, state='known', unknown=''):
    """Why a deploy of sha is held, given the commit production serves; None means deploy.

    state 'unconfigured' (no Cloudflare credentials) never holds: nothing is written then.
    Any state other than 'known', or a known state without a commit, holds on every event."""
    if state == 'unconfigured':
        return None
    if state != 'known' or not production:
        return ('the commit production serves could not be traced (' + (unknown or 'no live commit was read')
                + '), so it cannot be compared; roll production back to a version a deploy named or check it by hand')
    if not is_sha(production):
        raise SourceError('invalid production commit')
    if production == sha:
        # A manual deploy may repeat the live commit to apply changed variables or secrets.
        return None if event == 'workflow_dispatch' else 'production already serves ' + sha
    try:
        status = compare(repository, production, sha, read)
    except HTTPError as error:
        if error.code != 404:  # 404: GitHub does not know the commit production serves.
            raise
        status = 'unknown'
    if status == 'ahead':
        return None
    if status in ('identical', 'behind'):
        return 'production already serves ' + production + ', which is newer than ' + sha
    # Diverged or unknown: production serves a commit that is not on main. Replacing it
    # is a person's decision (a manual deploy), never an automatic one.
    if event == 'workflow_dispatch':
        return None
    return 'production serves ' + production + ', which is not on main; check it, then deploy by hand'


def main(argv=()):
    production = list(argv) == ['--production']
    if argv and not production:
        print('usage: check_deploy_source.py [--production]', file=sys.stderr)
        return 2
    repository = os.environ.get('GITHUB_REPOSITORY', '')
    sha = os.environ.get('DEPLOY_SHA') or os.environ.get('GITHUB_SHA', '')
    live = os.environ.get('PRODUCTION_SHA', '')
    state = os.environ.get('PRODUCTION_STATE', '')
    try:
        if os.environ.get('DEPLOY_TREE'):
            verify_checkout(os.environ['DEPLOY_TREE'], sha)
        run_id = verify_source(repository, os.environ.get('GITHUB_REF', ''), sha)
        reason = production_hold(repository, sha, live, os.environ.get('GITHUB_EVENT_NAME', ''), state=state,
                                 unknown=os.environ.get('PRODUCTION_REASON', '')) if production else None
    except (SourceError, OSError, ValueError, TypeError) as error:
        print(f'::error::Deployment source check failed: {error}', file=sys.stderr)
        return 1
    print(f'Deployment source verified: {sha}, push/main Offline checks run {run_id}')
    if not production:
        return 0
    if reason:
        print(f'::warning title=Deploy held::{reason}. Nothing was deployed.')
    elif state == 'unconfigured':
        print(f'Cloudflare is not configured; the deploy step writes nothing for {sha}.')
    else:
        print(f'Deploying {sha}; production serves {live}.')
    if os.environ.get('GITHUB_OUTPUT'):
        with open(os.environ['GITHUB_OUTPUT'], 'a') as output:
            output.write('hold=' + ('true' if reason else 'false') + '\n')
            output.write('reason=' + (reason or '') + '\n')
    return 0


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))
