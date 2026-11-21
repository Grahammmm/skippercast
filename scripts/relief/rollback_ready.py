#!/usr/bin/env python3
"""Check that the previous relief release can still be restored from the live site."""
import argparse
import json
import os
from pathlib import Path
import sys
import tempfile
from urllib.parse import urlsplit

# This command can run from the very checkout it is checking.
if __name__ == '__main__':
    sys.dont_write_bytecode = True

from skippercast.relief import live_archive, live_check, package, rollback

_NO_EARLIER = 'rollback: removes relief (no earlier release)'


def _origin(value):
    base = value.rstrip('/')
    try:
        url = urlsplit(base)
        _ = url.port
        if (url.scheme in ('http', 'https') and url.hostname and url.username is None
                and not url.path and not any(c in base for c in '?#')
                and not any(c.isspace() for c in value)):
            return base
    except ValueError:
        pass
    raise argparse.ArgumentTypeError('--base must be an HTTP(S) origin without credentials')


def _failure(check, reason, **fields):
    return dict(check=check, status='FAIL', reason=reason, **fields)


def _report(rows, as_json, *, message=None):
    failure = next((row for row in rows if row['status'] == 'FAIL'), None)
    verdict = 'PASS' if failure is None else 'FAIL'
    if as_json:
        report = dict(checks=rows, verdict=verdict)
        if message is not None:
            report['message'] = message
        print(json.dumps(report))
    elif message is not None:
        print(message)
    else:
        for row in rows:
            print(' '.join(filter(None, (row['status'], row['check'], row.get('key'), row['reason']))))
        suffix = '' if failure is None else f" {failure['check']} {failure['reason']}"
        print(f'rollback-ready: {verdict}{suffix}')
    return int(failure is not None)


def _check(repo, pointer, base):
    try:
        # tempfile can probe a configured directory with a write before selecting it.
        candidates = (os.environ.get(name) for name in ('TMPDIR', 'TEMP', 'TMP'))
        if any(path and Path(path).resolve().is_relative_to(repo) for path in candidates):
            return [_failure('scratch', 'temporary directory must be outside --repo')]
        if Path(tempfile.gettempdir()).resolve().is_relative_to(repo):
            return [_failure('scratch', 'temporary directory must be outside --repo')]
        site = live_check.Site(base)
        # Site reserves one operation for live-check's Git fetch; keep its counter.
        return live_archive.check_archive(pointer, site.fetch, budget=20 - site.requests)
    except live_check.FetchError as exc:
        return [_failure('fetch', exc.reason, key=exc.key)]
    except OSError:
        return [_failure('archive', 'local-io')]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', required=True, type=Path, help='root of the release clone')
    parser.add_argument('--region', required=True)
    parser.add_argument('--base', default='https://skippercast.com', type=_origin)
    parser.add_argument('--json', action='store_true', help='print a JSON report to stdout')
    args = parser.parse_args(argv)

    try:
        repo = args.repo.resolve()
        git = rollback.GitCli(repo)
        if git.run(['git', 'rev-parse', '--show-prefix']) != b'\n':
            raise rollback.RollbackError('--repo must point to the root of the clone')
        state = rollback.previous_state(git, args.region)
    except (OSError, rollback.RollbackError) as exc:
        return _report([_failure('history', str(exc))], args.json)
    raw = state[f'catalog/relief/{args.region}.json']
    if raw is None:
        return _report([], args.json, message=_NO_EARLIER)

    try:
        pointer = package.decode_document(raw)
        package.validate_schema(pointer, package.pointer_schema())
        if (pointer['region'] != args.region or type(pointer['bytes']) is not int
                or type(pointer['minzoom']) is not int or type(pointer['maxzoom']) is not int
                or pointer['minzoom'] > pointer['maxzoom']):
            raise package.ReleaseError('pointer does not describe a valid archive for this region')
    except (ValueError, OSError, ImportError):
        return _report([_failure('pointer', 'invalid')], args.json)

    return _report(_check(repo, pointer, args.base), args.json)


if __name__ == '__main__':
    raise SystemExit(main())
