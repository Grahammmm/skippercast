"""Require the current main SHA and successful push/main CI for a manual deploy.

Reads public GitHub metadata, sending only the workflow's read-only token
(SOURCE_READ_TOKEN, `github.token` under `contents: read`) when it is set, so the
shared runners' anonymous rate limit cannot fail a deploy. Network/metadata failures stop
before dependency execution or production writes. This is a workflow source
check, not an access-control boundary against repository administrators.
"""
import json
import os
import re
import sys
from urllib.parse import urlencode
from urllib.request import Request, urlopen


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


def verify_source(repository, ref, sha, read=public_metadata):
    if ref != 'refs/heads/main':
        raise SourceError('manual deployment requires refs/heads/main')
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9-]*/[A-Za-z0-9][A-Za-z0-9_.-]*', repository or ''):
        raise SourceError('invalid repository identity')
    if not re.fullmatch(r'[0-9a-f]{40}', sha or ''):
        raise SourceError('invalid deployment SHA')
    base = '/repos/' + repository
    main = read(base + '/git/ref/heads/main')
    if not isinstance(main, dict) or main.get('ref') != ref:
        raise SourceError('main ref metadata is missing or invalid')
    obj = main.get('object')
    if not isinstance(obj, dict) or obj.get('type') != 'commit' or obj.get('sha') != sha:
        raise SourceError('selected SHA is not current main; dispatch main again')
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


def main():
    try:
        sha = os.environ.get('GITHUB_SHA', '')
        run_id = verify_source(os.environ.get('GITHUB_REPOSITORY', ''),
                               os.environ.get('GITHUB_REF', ''), sha)
    except (SourceError, OSError, ValueError, TypeError) as error:
        print(f'::error::Deployment source check failed: {error}', file=sys.stderr)
        return 1
    print(f'Deployment source verified: {sha}, push/main Offline checks run {run_id}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
