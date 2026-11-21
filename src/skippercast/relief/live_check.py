"""Prove the reviewed relief release is served, without modifying the input clone."""
from __future__ import annotations

import argparse
from http.client import HTTPException
import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import NamedTemporaryFile, TemporaryDirectory
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from skippercast.relief import live_archive, live_deploy, package, receipts
from skippercast.relief.stage_transport import ARCHIVE_LIMIT

_LIMIT = 20
_METADATA_LIMIT = 1 << 20
_GIT_TIMEOUT = 60


class LocalError(ValueError):
    """The local checkout or output cannot be used to run the proof."""


class FetchError(ValueError):
    def __init__(self, key, reason):
        self.key = key
        self.reason = reason
        super().__init__(reason)


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class Site:
    def __init__(self, base):
        self.base = base
        self.opener = build_opener(NoRedirect())
        # The single Git fetch counts as one operation against the same budget.
        self.requests = 1

    def fetch(self, key, *, max_bytes):
        if self.requests >= _LIMIT:
            raise FetchError(key, 'budget')
        self.requests += 1
        try:
            response = self.opener.open(Request(f'{self.base}/{key}', method='GET'), timeout=15)
        except HTTPError as exc:
            exc.close()
            if exc.code == 404:
                return None
            raise FetchError(key, 'redirect' if 300 <= exc.code < 400 else f'http-{exc.code}') from None
        except (OSError, HTTPException) as exc:
            raise FetchError(key, 'transport') from exc
        if response.status != 200:
            response.close()
            raise FetchError(key, f'http-{response.status}')

        def blocks():
            remaining = max_bytes + 1  # one sentinel byte distinguishes an oversized object
            with response:
                try:
                    while remaining:
                        block = response.read(min(65536, remaining))
                        if not block:
                            break
                        remaining -= len(block)
                        yield block
                except (OSError, HTTPException) as exc:
                    raise FetchError(key, 'transport') from exc

        return blocks()

    def metadata(self, key):
        body = self.fetch(key, max_bytes=_METADATA_LIMIT)
        if body is None:
            return None
        data = b''.join(body)
        if len(data) > _METADATA_LIMIT:
            raise FetchError(key, 'oversize')
        return data


def _git(repo, *args, check=True):
    return subprocess.run(['git', '--no-optional-locks', '-c', 'core.fsmonitor=false',
                           '-C', str(repo), *args], capture_output=True, check=check,
                          timeout=_GIT_TIMEOUT)


def _reviewed(repo, region, key):
    if Path(os.fsdecode(_git(repo, 'rev-parse', '--show-toplevel').stdout.rstrip(b'\n'))) != repo:
        raise LocalError('--repo must name the clone root')
    if _git(repo, 'status', '--porcelain', '--untracked-files=all').stdout:
        raise LocalError('--repo must be clean')
    head = _git(repo, 'rev-parse', 'HEAD').stdout.strip().decode('ascii')
    raw = _git(repo, 'show', f'{head}:{key}').stdout
    merge = _git(repo, 'log', '-1', '--first-parent', '--format=%H', head, '--', key).stdout.strip().decode('ascii')
    pointer = package.decode_document(raw)
    low, high, size = (pointer.get(k) for k in ('minzoom', 'maxzoom', 'bytes'))
    if (not merge or len(raw) > _METADATA_LIMIT or pointer.get('region') != region
            or pointer.get('schema') != 'sc-relief-pointer/1' or pointer.get('status') != 'reviewed'
            or pointer.get('private') is not False
            or not all(package.is_sha256(pointer.get(k)) for k in ('generation', 'sha256', 'digest_root_sha256'))
            or type(low) is not int or type(high) is not int or not 8 <= low <= high <= 17
            or type(size) is not int or not 1 <= size <= ARCHIVE_LIMIT):
        raise LocalError('invalid reviewed region pointer in HEAD')
    return raw, merge, pointer


def _fetch_history(repo, history):
    origin = os.fsdecode(_git(repo, 'remote', 'get-url', 'origin').stdout.rstrip(b'\n'))
    # A relative local origin is relative to the supplied clone, not to scratch.
    if not urlsplit(origin).scheme and ':' not in origin:
        origin = str((repo / origin).resolve())
    objects = _git(repo, 'rev-parse', '--path-format=absolute', '--git-path', 'objects').stdout.rstrip(b'\n')
    _git(history, 'init', '--bare', '--quiet')
    # Borrow local objects read-only, so merge-base can also classify a divergent commit.
    (history / 'objects/info/alternates').write_bytes(objects + b'\n')
    _git(history, 'remote', 'add', 'origin', '--', origin)
    _git(history, '-c', 'http.followRedirects=false', 'fetch', 'origin', 'main')


def _is_ancestor(history, first, second):
    status = _git(history, 'merge-base', '--is-ancestor', first, second, check=False).returncode
    return {0: True, 1: False}.get(status)


def _failure(check, reason):
    return {'check': check, 'status': 'FAIL', 'reason': reason}


def _check(site, history, merge, key, raw, pointer):
    try:
        data = site.metadata('deploy.json')
        if data is None:
            return None, [_failure('deploy', 'missing')]
        deployed = live_deploy.parse_deploy(json.loads(data))
    except FetchError as exc:
        return None, [_failure('deploy', exc.reason)]
    except ValueError:
        return None, [_failure('deploy', 'invalid')]
    checks = [live_deploy.deploy_verdict(merge, deployed, lambda a, b: _is_ancestor(history, a, b))]
    if checks[-1]['status'] == 'PASS':
        try:
            checks.append(live_deploy.pointer_verdict(raw, site.metadata(key)))
        except FetchError as exc:
            checks.append(_failure('pointer', exc.reason))
    if checks[-1]['status'] == 'PASS':
        try:
            checks.extend(live_archive.check_archive(pointer, site.fetch, budget=_LIMIT - site.requests))
        except FetchError as exc:
            checks.append({**_failure('fetch', exc.reason), 'key': exc.key})
    return deployed, checks


def _write(path, report):
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent, delete=False) as stream:
        tmp = Path(stream.name)
        try:
            with stream:
                json.dump(report, stream, indent=2)
                stream.write('\n')
                stream.flush()
                os.fsync(stream.fileno())
            tmp.replace(path)
        finally:
            tmp.unlink(missing_ok=True)


def _run(args):
    if not receipts.REGION_ID.fullmatch(args.region):
        raise LocalError('invalid region id')
    base = args.base.rstrip('/')
    url = urlsplit(base)
    if (url.scheme not in ('http', 'https') or not url.hostname or url.username is not None
            or url.path or '?' in base or '#' in base or any(char.isspace() for char in base)):
        raise LocalError('--base must be an HTTP(S) origin without credentials')
    # Accessing port also checks for invalid port syntax before any requests.
    _ = url.port
    repo, out = args.repo.resolve(), args.out.resolve()
    key = f'catalog/relief/{args.region}.json'
    raw, merge, pointer = _reviewed(repo, args.region, key)
    parent = (out / args.region / 'live' / pointer['generation']).resolve()
    if out.is_relative_to(repo) or parent.is_relative_to(repo) or not parent.is_relative_to(out):
        raise LocalError('receipt must stay under OUT and outside --repo')
    out.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix='relief-history-', dir=out) as scratch:
        history = Path(scratch)
        _fetch_history(repo, history)
        site = Site(base)
        deployed, checks = _check(site, history, merge, key, raw, pointer)
    passed = all(row['status'] == 'PASS' for row in checks)
    _write(parent / 'live.json', dict(region=args.region, base=base, merge=merge, deployed=deployed,
                                    checks=checks, verdict='PASS' if passed else 'FAIL', requests=site.requests))
    return 0 if passed else 1


def main(argv=None):
    parser = argparse.ArgumentParser(prog='region.py live-check', description=__doc__)
    parser.add_argument('--region', required=True)
    parser.add_argument('--out', required=True, type=Path)
    parser.add_argument('--repo', required=True, type=Path)
    parser.add_argument('--base', default='https://skippercast.com')
    args = parser.parse_args(argv)
    try:
        return _run(args)
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        print(f'{parser.prog}: {exc}', file=sys.stderr)
        return 2
