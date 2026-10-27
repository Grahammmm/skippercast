"""Raw campaign mirror only: no extraction, qualification, mapping or publication.

Transfers use the shared HTTPS/DNS/redirect policy. A single process fetches one
bounded range at a time (including redirects), below the two-per-host ceiling.
HTTP failures park the HOST durably; an operator service may retry later.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import time
from urllib.parse import urlsplit

from skippercast.http import ContractError, Session, USER_AGENT, default_allowlist, parse_retry_after
from skippercast.paths import repo_root

MOUNT = Path('/mnt/agentorange-backup')
RAW = MOUNT / 'skippercast-campaign/raw'
MIRROR = Path.home() / 'skippercast-data/campaign-raw-manifest'
RETRY_STATE = MIRROR / 'retry-state.json'
STATUS = Path.home() / 'agent-work/reports/coast-pilot/prefetch-status.json'
RESERVE = 200_000_000_000  # decimal GB, not GiB; not operator-adjustable
RANGE_BYTES = 64 * 1024 * 1024
SEGMENTS = ('C1', 'C2', 'C3', 'C4', 'C5', 'C6', 'C7a', 'C7b',
            'S1', 'S2', 'S3', 'S4', 'S5', 'S6',
            'N1', 'N2', 'N3', 'N4', 'N5', 'N6', 'N6b', 'N7')
SLUG = re.compile(r'[a-z0-9][a-z0-9-]{0,79}\Z')
SHA = re.compile(r'[a-f0-9]{64}\Z')


class Hold(ValueError):
    """A permanent contract/inventory hold; never silently retry it."""


class CapacityError(ContractError):
    """Stop the whole pass, not just this file."""


class Parked(OSError):
    """A host is unavailable until its persisted retry time."""


class TransferSession(Session):
    """Reuse all shared transport policy, but never buffer an error body.

    A raw-file byte ceiling can be gigabytes; Session normally uses that ceiling
    for error bodies too. Prefetch only needs status/headers to park the host.
    This narrow read hook is exercised through Session.request in offline tests.
    """
    def _read(self, response, limit, sink, digest, truncate=False):
        if not 200 <= response.status < 300:
            return b'', 0
        return super()._read(response, limit, sink, digest, truncate)

    def _decode(self, body, headers, limit):
        # A discarded error may advertise gzip. Do not try to decompress it.
        if not body:
            return body, None
        return super()._decode(body, headers, limit)


def stamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def digest(path: Path) -> str:
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def safe_path(path: Path) -> Path:
    """No symlinks, including parents and not-yet-created final components."""
    path = path.absolute()
    if '..' in path.parts:
        raise Hold(f'Parent traversal refused: {path}')
    for component in (path, *path.parents):
        if component.is_symlink():
            raise Hold(f'Symlink refused: {component}')
    return path


def atomic_text(path: Path, text: str) -> None:
    safe_path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = safe_path(path.with_name(path.name + '.tmp'))
    with temp.open('w', encoding='utf-8') as stream:
        stream.write(text)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temp, path)  # same directory / same filesystem; works on exFAT


def atomic_json(path: Path, data: dict) -> None:
    atomic_text(path, json.dumps(data, indent=2, sort_keys=True) + '\n')


def read_json(path: Path, default: dict | None = None) -> dict:
    safe_path(path)
    return json.loads(path.read_text()) if path.exists() else (default or {})


def filename(row: dict) -> str:
    # URL identity prevents basename collisions; ASCII/casefold-safe on exFAT.
    leaf = re.sub(r'[^A-Za-z0-9._-]', '_', urlsplit(row['url']).path.rsplit('/', 1)[-1])
    leaf = leaf.strip(' .')[:120] or 'response.bin'
    return hashlib.sha256(row['url'].encode()).hexdigest()[:20] + '-' + leaf


def load_plan(path: Path, session: Session) -> dict:
    plan = read_json(path)
    if plan.get('schema_version') != 1 or not isinstance(plan.get('files'), list):
        raise Hold('Expected schema_version=1 and files array')
    if not plan['files']:
        raise Hold('Empty inventory is not a completed campaign')
    if not isinstance(plan.get('unresolved', []), list):
        raise Hold('unresolved must be an array')
    files = {}
    destinations = set()
    for original in plan['files']:
        if not isinstance(original, dict):
            raise Hold('Every file entry must be an object')
        row = dict(original)
        if not SLUG.fullmatch(row.get('source', '')):
            raise Hold('source must be a safe lower-case slug')
        url = row.get('url', '')
        session.check_url(url)  # no DNS/network; every redirect is checked later too
        if urlsplit(url).fragment:
            raise Hold('URL fragments are not download identities')
        if not isinstance(row.get('licence'), str) or not row['licence'].strip():
            raise Hold(f'Missing licence: {url}')
        segments = row.get('segments')
        if not isinstance(segments, list) or not segments or any(s not in SEGMENTS for s in segments):
            raise Hold(f'Missing/unknown campaign segments: {url}')
        row['segments'] = sorted(set(segments), key=SEGMENTS.index)
        size, sha = row.get('bytes'), row.get('sha256')
        if size is not None and (type(size) is not int or size <= 0):
            raise Hold(f'bytes must be a positive integer or null: {url}')
        if sha is not None and (not isinstance(sha, str) or not SHA.fullmatch(sha)):
            raise Hold(f'Invalid SHA-256: {url}')
        if url in files:
            previous = files[url]
            if any(previous.get(k) != row.get(k) for k in ('source', 'bytes', 'sha256', 'licence')):
                raise Hold(f'Conflicting duplicate URL: {url}')
            previous['segments'] = sorted(set(previous['segments'] + segments), key=SEGMENTS.index)
            continue
        dest = (row['source'] + '/' + filename(row)).casefold()
        if dest in destinations:
            raise Hold(f'Case-insensitive destination collision: {url}')
        destinations.add(dest)
        files[url] = row
    plan['files'] = sorted(files.values(), key=lambda r: (SEGMENTS.index(r['segments'][0]), r['source'], r['url']))
    return plan


def dry_run(plan: dict) -> dict:
    """No writes, mount requirement, network, or hashing of large cached files."""
    totals = {s: {'files': 0, 'known_bytes': 0, 'unknown_size_files': 0} for s in SEGMENTS}
    for row in plan['files']:
        # One physical source counted once, at its first requested segment.
        total = totals[row['segments'][0]]
        total['files'] += 1
        total['known_bytes'] += row.get('bytes') or 0
        total['unknown_size_files'] += row.get('bytes') is None
    for total in totals.values():
        total['total_bytes'] = None if total['unknown_size_files'] else total['known_bytes']
    return {'schema_version': 1, 'review_required': True,
            'inventory_complete': not plan.get('unresolved'),
            'unresolved': plan.get('unresolved', []), 'segments': totals,
            'files': [{**row, 'relative_path': row['source'] + '/' + filename(row)} for row in plan['files']],
            'note': 'Totals count shared URLs only at their earliest segment; null means unknown, not zero.'}


class GuardedSink:
    """Session sink with continuous mount/free-space checks before every write."""
    def __init__(self, stream, guard, progress):
        self.stream, self.guard, self.progress = stream, guard, progress

    def seekable(self):
        return True

    def seek(self, *args):
        return self.stream.seek(*args)

    def truncate(self, *args):
        return self.stream.truncate(*args)

    def write(self, chunk):
        self.guard(len(chunk))
        result = self.stream.write(chunk)
        self.progress(result)
        return result


def mirror_urls(path):
    """URLs receipted in a mirror manifest; unparseable lines are stale and carry none."""
    urls = []
    for line in path.read_text().splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict) and isinstance(row.get('url'), str):
            urls.append(row['url'])
    return urls


class Prefetch:
    def __init__(self, plan: dict, session: Session, *, root=RAW, mirror=MIRROR,
                 status=STATUS, mount=MOUNT, clock=time.time, disk_usage=shutil.disk_usage,
                 ismount=os.path.ismount, lock_dir=None, retry_state=None):
        self.plan, self.session = plan, session
        self.root, self.mirror, self.status = map(Path, (root, mirror, status))
        self.mount = Path(mount)
        self.clock, self.disk_usage, self.ismount = clock, disk_usage, ismount
        self.lock_dir = Path(lock_dir) if lock_dir else Path.home() / '.cache/skippercast/coast-prefetch'
        self.retry_state = Path(retry_state) if retry_state is not None else RETRY_STATE
        self.state = {}
        self.records = {}
        self.results = {}
        self.progress_bytes = 0
        self.last_status = 0.0
        self.active = None

    def guard(self, incoming=0):
        safe_path(self.mount)
        safe_path(self.root)
        if not self.root.absolute().is_relative_to(self.mount.absolute()) or not self.ismount(self.mount):
            raise CapacityError('SanDisk mount absent or destination outside the mounted disk')
        if self.disk_usage(self.mount).free < RESERVE + incoming:
            raise CapacityError('Hard stop: SanDisk would fall below 200 GB free')

    @contextmanager
    def lock(self):
        # Local Linux filesystem lock, not an exFAT permission/symlink assumption.
        key = hashlib.sha256(str(self.root.absolute()).encode()).hexdigest()
        path = safe_path(self.lock_dir / (key + '.lock'))
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('a') as stream:
            try:
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as error:
                raise Hold('Another prefetch process owns this raw mirror') from error
            yield

    @staticmethod
    def merge_state(target, incoming):
        # Never shorten an existing hold, even when importing an older snapshot.
        for host, entry in incoming.items():
            old = target.get(host, {})
            winner = entry if entry.get('retry_at', 0) > old.get('retry_at', 0) else old
            target[host] = {**winner, 'failures': max(old.get('failures', 0), entry.get('failures', 0))}

    @contextmanager
    def retry_lock(self):
        # One stable local lock for ALL modes/snapshots, independent of raw root.
        # Hold it through the request and error persistence: another process must
        # not pass the cooldown check just before this one parks the host.
        path = safe_path(self.retry_state.with_name(self.retry_state.name + '.lock'))
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('a') as stream:
            fcntl.flock(stream, fcntl.LOCK_EX)
            self.state = read_json(self.retry_state)
            before = dict(self.state)
            legacy = self.mirror / 'retry-state.json'
            if legacy.absolute() != self.retry_state.absolute():
                self.merge_state(self.state, read_json(legacy))
            if self.state != before:
                atomic_json(self.retry_state, self.state)
            yield

    def import_retry_state(self, paths):
        """Network-free, additive migration of old per-snapshot registries."""
        with self.retry_lock():
            for path in paths:
                if not safe_path(path).is_file():
                    raise Hold(f'Missing retry-state import: {path}')
                self.merge_state(self.state, read_json(path))
            atomic_json(self.retry_state, self.state)

    def park(self, host: str, reason: str, status=None, headers=None):
        with self.retry_lock():
            self._park(host, reason, status, headers)

    def _park(self, host: str, reason: str, status=None, headers=None):
        # Caller owns retry_lock; no stale read/modify/write or nested flock.
        old = self.state.get(host, {})
        failures = min(old.get('failures', 0) + 1, 16)
        wait = min(86400, 900 * 2 ** (failures - 1))
        noaa = host.endswith('.noaa.gov') or (host.startswith('noaa-') and host.endswith('.amazonaws.com'))
        if noaa and status in (500, 503):
            wait = max(wait, 86400)  # NOAA outage: next day, not immediate retry
        retry_after = parse_retry_after((headers or {}).get('Retry-After'), now=self.clock())
        wait = max(wait, retry_after or 0)
        self.merge_state(self.state, {host: {'failures': failures, 'retry_at': self.clock() + wait,
                                             'reason': reason, 'http_status': status}})
        atomic_json(self.retry_state, self.state)
        raise Parked(f'{host}: {reason}; retry after {wait:.0f}s')

    def request(self, method, url, *, follow_redirects=True, **kwargs):
        with self.retry_lock():
            return self._request(method, url, follow_redirects=follow_redirects, **kwargs)

    def _request(self, method, url, *, follow_redirects, **kwargs):
        # Follow redirects explicitly so a parked TARGET host is never contacted.
        from urllib.parse import urljoin
        current = url
        for _ in range(self.session.max_redirects + 1):
            host, _port = self.session.check_url(current)
            retry_at = self.state.get(host, {}).get('retry_at', 0)
            if self.clock() < retry_at:
                raise Parked(f'{host}: parked until {retry_at}')
            try:
                response = self.session.request(method, current, attempts=1, use_cache=False,
                                                follow_redirects='return', raise_for_status=False,
                                                **kwargs)
            except CapacityError:
                raise
            except OSError as error:
                self._park(host, str(error))
            if response.status in (301, 302, 303, 307, 308):
                if not follow_redirects:
                    raise Hold(f'Metadata redirect refused: {current}')
                location = response.headers.get('Location')
                if not location:
                    raise Hold(f'Redirect without Location: {current}')
                current = urljoin(current, location)
                continue
            if response.status == 429 or 500 <= response.status <= 599:
                self._park(host, f'HTTP {response.status}', response.status, response.headers)
            if response.status not in (200, 206):
                raise Hold(f'HTTP {response.status}: {current}')
            if method == 'HEAD' and response.status != 200:
                raise Hold('Expected complete HEAD metadata, not a partial response')
            return response
        raise Hold('Too many redirects')

    def write_status(self, *, state='running', error=None, force=True):
        if not force and self.clock() - self.last_status < 10:
            return
        sources = {}
        for row in self.plan['files']:
            source = sources.setdefault(row['source'], {'files_done': 0, 'files_total': 0,
                                                        'bytes': 0, 'errors': []})
            source['files_total'] += 1
            result = self.results.get(row['url'], {})
            if result.get('state') == 'verified':
                source['files_done'] += 1
                source['bytes'] += result['bytes']
            elif result.get('error'):
                source['errors'].append({'url': row['url'], **result})
        atomic_json(self.status, {'schema_version': 1, 'updated_at': stamp(), 'state': state,
                                 'review_required': True, 'sources': sources,
                                 'unresolved': self.plan.get('unresolved', []),
                                 'active_url': self.active, 'transfer_bytes_this_pass': self.progress_bytes,
                                 'parked_hosts': self.state, 'error': error})
        self.last_status = self.clock()

    def progress(self, size):
        self.progress_bytes += size
        self.write_status(force=False)

    def manifest(self, source):
        self.guard()
        directory = safe_path(self.root / source)
        directory.mkdir(parents=True, exist_ok=True)
        path = safe_path(directory / 'manifest.jsonl')
        records = {}
        if path.exists():
            for line in path.read_text().splitlines():
                row = json.loads(line)
                records[row['url']] = row
        mirror = self.mirror / (source + '.jsonl')
        if mirror.exists() and set(mirror_urls(mirror)) - set(records):
            # A lost or truncated primary must never erase the only other copy of receipts.
            raise Hold(f'Mirror manifest has receipts the primary lacks; preserve both: {mirror}')
        self.records[source] = records
        self.flush_manifest(source)  # repair a stale/missing second copy after a crash

    def flush_manifest(self, source):
        text = ''.join(json.dumps(r, sort_keys=True) + '\n'
                       for _, r in sorted(self.records[source].items()))
        self.guard(len(text.encode()))
        atomic_text(self.root / source / 'manifest.jsonl', text)
        atomic_text(self.mirror / (source + '.jsonl'), text)

    def checkpoint(self, path, data):
        # Atomic metadata replacement also needs space above the exFAT reserve.
        text = json.dumps(data, indent=2, sort_keys=True) + '\n'
        self.guard(len(text.encode()))
        atomic_text(path, text)

    @staticmethod
    def validator(headers):
        # Only a strong ETag may stitch ranges: a weak ETag is not byte identity and
        # Last-Modified has 1 s resolution. Without one, fetch one full entity.
        etag = headers.get('ETag')
        if etag and not etag.startswith('W/'):
            return etag
        return None

    @staticmethod
    def entity_changed(head, response):
        """Any ETag change (weak or strong) or Last-Modified change means another entity."""
        if response.get('ETag') != head.get('ETag'):
            return True
        modified = head.get('Last-Modified')
        return bool(modified and response.get('Last-Modified') not in (None, modified))

    def fetch(self, row):
        self.guard()
        directory = self.root / row['source']
        final = safe_path(directory / filename(row))
        partial = safe_path(final.with_name(final.name + '.part'))
        meta_path = safe_path(final.with_name(final.name + '.part.json'))
        chunk_path = safe_path(final.with_name(final.name + '.chunk'))
        record = self.records[row['source']].get(row['url'])
        if final.exists():
            sha, size = digest(final), final.stat().st_size
            if (record and record.get('sha256') == sha and record.get('bytes') == size
                    and record.get('path') == str(final.absolute())
                    and (row.get('bytes') is None or row['bytes'] == size)
                    and (row.get('sha256') is None or row['sha256'] == sha)):
                # Preserve raw bytes; refresh licence/segment metadata from the reviewed plan.
                record.update(licence=row['licence'], segments=row['segments'])
                self.flush_manifest(row['source'])
                return size
            raise Hold(f'Existing final file lacks matching verified receipt; preserve and investigate: {final}')

        headers = {'Accept-Encoding': 'identity'}
        head = self.request('HEAD', row['url'], headers=headers, max_bytes=0)
        declared = head.headers.get('Content-Length')
        total = int(declared) if declared and declared.isdigit() else row.get('bytes')
        if not total or (row.get('bytes') is not None and total != row['bytes']):
            raise Hold('Missing or mismatched remote size; review inventory before transfer')
        validator = self.validator(head.headers)
        meta = read_json(meta_path)
        offset = 0
        if partial.exists() and (meta_path.exists() or partial.stat().st_size):
            # Never concatenate different remote entities or an unchecked partial.
            if (meta.get('url') != row['url'] or meta.get('total') != total
                    or meta.get('final_url') != head.final_url
                    or (meta.get('bytes') and not validator) or meta.get('validator') != validator):
                raise Hold('Partial identity changed or has no strong ETag; preserve for operator')
            offset = meta.get('bytes', -1)
            if (type(offset) is not int or not 0 <= offset <= total
                    or partial.stat().st_size < offset):
                raise Hold('Partial size/hash mismatch; preserve for operator')
            prefix = hashlib.sha256()
            with partial.open('rb') as stream:
                remaining = offset
                while remaining:
                    block = stream.read(min(remaining, 1024 * 1024))
                    prefix.update(block)
                    remaining -= len(block)
            if prefix.hexdigest() != meta.get('sha256'):
                raise Hold('Partial size/hash mismatch; preserve for operator')
            # A crash during append may leave an uncommitted suffix. The verified
            # checkpoint prefix is authoritative; re-fetch only that suffix.
            with partial.open('r+b') as stream:
                stream.truncate(offset)
        elif meta_path.exists():
            raise Hold('Partial receipt exists without partial bytes')
        else:
            # A crash before the first checkpoint may leave an empty .part and
            # no receipt. No bytes exist to authenticate; safely initialize it.
            # Nonempty unreceipted bytes and any existing receipt still fail closed.
            partial.touch()
            self.checkpoint(meta_path, {'url': row['url'], 'total': total, 'validator': validator,
                                    'final_url': head.final_url,
                                    'bytes': 0, 'sha256': hashlib.sha256(b'').hexdigest()})

        rolling = hashlib.sha256()
        if offset:
            with partial.open('rb') as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b''):
                    rolling.update(block)
        while offset < total:
            end = min(offset + RANGE_BYTES, total) - 1 if validator else total - 1
            request_headers = {**headers, 'Range': f'bytes={offset}-{end}'}
            if validator:
                request_headers['If-Range'] = validator
            self.guard()
            with chunk_path.open('w+b') as stream:
                # Permit a server ignoring Range to return one FULL file, never append it.
                response = self.request('GET', row['url'], headers=request_headers, max_bytes=total,
                                        sink=GuardedSink(stream, self.guard, self.progress))
                stream.flush()
                os.fsync(stream.fileno())
            size = chunk_path.stat().st_size
            if response.final_url != head.final_url:
                raise Hold('Remote redirect target changed during transfer')
            if response.headers.get('Content-Encoding', 'identity').lower() != 'identity':
                raise Hold('Encoded response refused: raw byte identity required')
            if self.entity_changed(head.headers, response.headers):
                raise Hold('Remote validator changed during transfer')
            if response.status == 206:
                expected = f'bytes {offset}-{end}/{total}'
                if response.headers.get('Content-Range') != expected or size != end - offset + 1:
                    raise Hold('Content-Range/length does not match requested bytes')
                if offset and not validator:
                    raise Hold('Cannot concatenate ranges without a remote validator')
                self.guard(size)
                with partial.open('ab') as target, chunk_path.open('rb') as source:
                    for block in iter(lambda: source.read(1024 * 1024), b''):
                        self.guard(len(block))
                        target.write(block)
                        rolling.update(block)
                    target.flush()
                    os.fsync(target.fileno())
                offset += size
                chunk_path.unlink()
            else:
                if size != total:
                    raise Hold('Server ignored Range but did not return the complete entity')
                os.replace(chunk_path, partial)
                offset = total
                with partial.open('rb') as stream:
                    rolling = hashlib.file_digest(stream, 'sha256')
            self.checkpoint(meta_path, {'url': row['url'], 'total': total, 'validator': validator,
                                    'final_url': head.final_url,
                                    'bytes': offset, 'sha256': rolling.hexdigest()})
            self.write_status()
        sha = digest(partial)
        if partial.stat().st_size != total or (row.get('sha256') and row['sha256'] != sha):
            raise Hold('Final size/SHA-256 does not match reviewed inventory')
        self.guard()
        # Receipt BEFORE rename: a crash between these is recoverable from the complete partial.
        self.records[row['source']][row['url']] = {
            'url': row['url'], 'final_url': head.final_url, 'bytes': total, 'sha256': sha,
            'etag': head.headers.get('ETag'), 'last_modified': head.headers.get('Last-Modified'),
            'fetched_at': stamp(), 'licence': row['licence'], 'segments': row['segments'],
            'path': str(final.absolute()), 'review_required': True,
            'verification': 'publisher-sha256' if row.get('sha256') else 'http-size-and-local-sha256',
        }
        self.flush_manifest(row['source'])
        os.replace(partial, final)
        meta_path.unlink()
        return total

    def probe_sizes(self, output: Path):
        """Explicit metadata-only preflight. Dry-run itself never makes requests."""
        with self.lock():
            with self.retry_lock():
                pass
            result = {**self.plan, 'files': [dict(r) for r in self.plan['files']],
                      'unresolved': list(self.plan.get('unresolved', []))}
            for row in result['files']:
                self.active = row['url']
                try:
                    head = self.request('HEAD', row['url'], max_bytes=0,
                                        headers={'Accept-Encoding': 'identity'})
                    declared = head.headers.get('Content-Length', '')
                    if not declared.isdigit() or int(declared) <= 0:
                        raise Hold('HEAD does not supply a positive size')
                    if row.get('bytes') is not None and row['bytes'] != int(declared):
                        raise Hold('HEAD size differs from existing inventory pin')
                    row.update(bytes=int(declared), size_checked_at=stamp(),
                               size_etag=head.headers.get('ETag'),
                               size_last_modified=head.headers.get('Last-Modified'))
                except (ValueError, OSError) as error:
                    self.results[row['url']] = {'state': 'parked' if isinstance(error, Parked) else 'held',
                                                'error': str(error)}
                    result['unresolved'].append({'source': row['source'], 'url': row['url'], 'reason': str(error)})
                self.write_status(state='probing')
            self.active = None
            atomic_json(output, result)
            self.write_status(state='inventory-review-required')
            return 2 if result['unresolved'] else 0

    def run(self, *, allow_incomplete=False):
        with self.lock():
            with self.retry_lock():
                pass
            if self.plan.get('unresolved') and not allow_incomplete:
                message = 'Inventory unresolved; --dry-run shows holds. Only --allow-incomplete permits a partial pass.'
                self.write_status(state='stopped', error=message)
                raise Hold(message)
            self.write_status()
            try:
                self.guard()
                for row in self.plan['files']:
                    self.active = row['url']
                    self.write_status()
                    if row['source'] not in self.records:
                        self.manifest(row['source'])
                    try:
                        size = self.fetch(row)
                        self.results[row['url']] = {'state': 'verified', 'bytes': size}
                    except Parked as error:
                        self.results[row['url']] = {'state': 'parked', 'error': str(error)}
                    except (ValueError, OSError) as error:
                        if isinstance(error, CapacityError):
                            raise
                        self.results[row['url']] = {'state': 'held', 'error': str(error)}
                    self.write_status()
            except (ValueError, OSError) as error:
                self.write_status(state='stopped', error=str(error))
                raise
            finally:
                self.active = None
            states = {r['state'] for r in self.results.values()}
            code = 2 if 'held' in states or self.plan.get('unresolved') else 75 if 'parked' in states else 0
            self.write_status(state='complete' if code == 0 else 'incomplete')
            return code


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan', type=Path)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument('--dry-run', action='store_true')
    action.add_argument('--run', action='store_true')
    action.add_argument('--probe-sizes', action='store_true', help='Explicit HEAD-only preflight; writes a new review-required plan')
    action.add_argument('--import-retry-state', type=Path, action='append',
                        help='Network-free additive migration of legacy retry state (repeatable)')
    parser.add_argument('--output', type=Path, help='Required with --probe-sizes; must not overwrite its input')
    parser.add_argument('--allow-incomplete', action='store_true', help='Fetch known files but retain unresolved holds; never reports complete')
    args = parser.parse_args(argv)
    if args.import_retry_state:
        try:
            run = Prefetch({'files': []}, TransferSession(), mirror=RETRY_STATE.parent)
            run.import_retry_state(args.import_retry_state)
            print(json.dumps({'retry_state': str(run.retry_state), 'parked_hosts': run.state}))
            return 0
        except (ValueError, OSError) as error:
            print(json.dumps({'state': 'stopped', 'error': str(error)}))
            return 2
    if args.plan is None:
        parser.error('--plan is required except for --import-retry-state')
    if args.probe_sizes and (args.output is None or args.output.absolute() == args.plan.absolute()):
        parser.error('--probe-sizes requires a distinct --output path')
    # Existing reviewed policy, including catalog URLs and its explicit built-in
    # source hosts (e.g. cmgds). No CLI expansion or promotion of bare host strings.
    allowlist = default_allowlist(root=repo_root())
    session = TransferSession(allowed_hosts=allowlist, attempts=1, cache=None,
                      user_agent=USER_AGENT + ' coast-campaign-raw-prefetch (operator-managed)',
                      min_interval={h: 1.0 for h in allowlist.exact}, timeout=120)
    try:
        plan = load_plan(args.plan, session)
        if args.dry_run:
            print(json.dumps(dry_run(plan), indent=2))
            return 0
        if args.probe_sizes:
            return Prefetch(plan, session).probe_sizes(args.output)
        return Prefetch(plan, session).run(allow_incomplete=args.allow_incomplete)
    except (ValueError, OSError) as error:
        print(json.dumps({'state': 'stopped', 'error': str(error)}))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
