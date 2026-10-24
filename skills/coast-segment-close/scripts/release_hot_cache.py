"""OPERATOR ONLY: release verified hot-cache files listed in an independently posted release list.

Never run by headless agents against real data. Refuses without --execute.
Preflight (any failure keeps EVERY cache file): list SHA equals the posted SHA;
fresh archive-only graph closure reproduces the exact candidate list; current
hot ledgers are byte-identical to the archived snapshots (frozen tips); every
candidate is a regular, single-link file under <segment>/cache/ reached without
symlinks, with unchanged device/inode/size/mtime/hash; exclusive campaign close
and ledger locks. Then unlinks file by file (never a directory) after a
per-file recheck, and writes release-receipt.json next to the list. A later
unexpected failure stops and is reported as an honest partial release.
"""

import json
import os
from pathlib import Path
import stat
from contextlib import ExitStack

from close_common import (HEADER, Refused, Resolver, absolute, canonical, coast_ledger, directory_fd, find_root,
                          finish, header, load_json, observe, parser, relative_parts, require, sha256, verify_closed,
                          release_candidates, validate_schema, _consistency, write_once)
from close_common import archive_metrics, exclusive_lock, quiescent

RECEIPT_SCHEMA = 'coast-segment-close-release-receipt-v1'


def check_candidate(queue_root, candidate):
    ref = candidate['source_ref']
    parts = relative_parts(ref['path'])
    require(len(parts) >= 2 and parts[0] == 'cache', 'candidate outside <segment>/cache/: ' + ref['path'])
    ident, st = observe(queue_root, ref['path'])
    require(st.st_nlink == 1, 'hardlink alias refused: ' + ref['path'])
    require((st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns) == (candidate['device'], candidate['inode'], candidate['size'], candidate['mtime_ns']),
            'cache identity changed since archive preparation: ' + ref['path'])
    require((ident['sha256'], ident['bytes']) == (ref['sha256'], ref['bytes']), 'cache bytes changed: ' + ref['path'])


def unlink_checked(queue_root, candidate):
    """Recheck through the open parent FD, then directory-relative unlink."""
    ref = candidate['source_ref']
    parts = relative_parts(ref['path'])
    with directory_fd(queue_root) as top:
        fd = os.dup(top)
        try:
            for part in parts[:-1]:
                new = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                os.close(fd)
                fd = new
            leaf = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
            try:
                st = os.fstat(leaf)
                require(stat.S_ISREG(st.st_mode) and st.st_nlink == 1, 'candidate no longer a single-link regular file')
                require((st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns) == (candidate['device'], candidate['inode'], candidate['size'], candidate['mtime_ns']),
                        'candidate identity changed before unlink')
                import hashlib
                digest = hashlib.sha256()
                while chunk := os.read(leaf, 1024 * 1024):
                    digest.update(chunk)
                require(digest.hexdigest() == ref['sha256'], 'candidate bytes changed before unlink')
            finally:
                os.close(leaf)
            named = os.stat(parts[-1], dir_fd=fd, follow_symlinks=False)
            require((named.st_dev, named.st_ino) == (st.st_dev, st.st_ino), 'directory entry changed before unlink')
            with directory_fd(Path(queue_root).joinpath(*parts[:-1])) as current:
                expected, actual = os.fstat(fd), os.fstat(current)
                require((expected.st_dev, expected.st_ino) == (actual.st_dev, actual.st_ino),
                        'admitted cache parent changed before unlink')
            os.unlink(parts[-1], dir_fd=fd)
        finally:
            os.close(fd)


def release(bindings, *, list_path, expected_sha256, execute, ledger, campaign_ledger, original_raw_roots, head):
    if not execute:
        raise Refused('release_hot_cache refuses without --execute (OPERATOR ONLY); nothing deleted')
    raw = Path(list_path).read_bytes()
    require(sha256(raw) == expected_sha256, 'release list SHA differs from the independently posted SHA')
    listing = json.loads(raw)
    validate_schema(listing)
    _consistency(listing)
    require(listing['schema'] == 'coast-release-list-v1', 'not a release list')
    queue_id = find_root(bindings, 'queue:')
    archive_id = find_root(bindings, 'archive:')
    queue_root = Path(bindings[queue_id])
    require(queue_id == 'queue:' + listing['campaign_segment_id'], 'release list belongs to another segment')
    with ExitStack() as held:
        held.enter_context(quiescent(queue_root))
        held.enter_context(exclusive_lock(Path(str(ledger) + '.lock')))
        held.enter_context(exclusive_lock(Path(str(campaign_ledger) + '.lock')))
        # Fresh archive-only closure: hot queue/repo reads disabled.
        archive_only = {k: str(v) for k, v in bindings.items() if k.startswith(('archive:', 'raw:'))}
        inner = Resolver(archive_only, allowed_root_ids=set(archive_only))
        closed = verify_closed(inner, archive_id=archive_id, original_queue_roots={queue_id: str(queue_root)},
                               original_raw_roots=original_raw_roots)
        require(closed['manifest_ref'] == listing['manifest'], 'manifest changed since the release list')
        require(closed['segment_ref'] == listing['segment_ledger_snapshot'] and closed['campaign_ref'] == listing['campaign_ledger_snapshot'],
                'ledger snapshots changed since the release list')
        candidates = release_candidates(closed['manifest'])
        require(sorted(map(canonical, candidates)) == sorted(map(canonical, listing['candidates'])),
                'release candidates differ from the verified closed inventory')
        require(all(o['expected'] == o['observed'] for o in listing['validation_observations']), 'release list records a failed observation')
        for source, snapshot in ((ledger, listing['segment_ledger_snapshot']), (campaign_ledger, listing['campaign_ledger_snapshot'])):
            current = Path(source).read_bytes()
            coast_ledger.verify_bytes(current)
            require(sha256(current) == snapshot['sha256'], 'hot ledger changed after close (frozen tip mismatch): ' + str(source))
        for candidate in listing['candidates']:
            require(candidate['source_ref']['root_id'] == queue_id, 'candidate outside the segment queue root')
            check_candidate(queue_root, candidate)
        # Reserve BOTH accounting destinations before any destructive action.
        # Existing evidence is never replaced. The durable intent + per-file
        # markers remain authoritative if the final receipt cannot be written.
        target = Path(list_path).with_name('release-receipt.json')
        journal = target.with_name('release-accounting')
        with directory_fd(target.parent) as parent:
            require(not target.exists() and not target.is_symlink(), 'release receipt already exists')
            os.mkdir(journal.name, mode=0o700, dir_fd=parent)
            os.fsync(parent)
        write_once(journal / 'intent.json', dict(schema='coast-release-intent-v1', **head,
                   release_list_sha256=expected_sha256, candidates=listing['candidates'],
                   note='A before marker without an after marker means outcome UNKNOWN; no automatic retry.'))
        # O_EXCL reserves the exact final output, including permissions/capacity
        # checks. fsync the open reservation and its parent before the first unlink.
        with directory_fd(target.parent) as parent:
            receipt_fd = os.open(target.name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=parent)
            held.callback(os.close, receipt_fd)
            os.fsync(receipt_fd)
            os.fsync(parent)
        released, failure = [], None
        for index, candidate in enumerate(listing['candidates']):
            try:
                write_once(journal / f'{index:06d}-before.json', dict(source_ref=candidate['source_ref'], status='pending'))
                unlink_checked(queue_root, candidate)
                released.append(candidate['source_ref'])
                write_once(journal / f'{index:06d}-after.json', dict(source_ref=candidate['source_ref'], status='unlinked'))
            except (Refused, ValueError, OSError) as error:
                failure = dict(path=candidate['source_ref']['path'], error=str(error))
                break
        done = {canonical(r) for r in released}
        receipt = dict(schema=RECEIPT_SCHEMA, **head, campaign_segment_id=listing['campaign_segment_id'], close_id=listing['close_id'],
                       release_list_sha256=expected_sha256, status='partial' if failure else 'complete', released=released,
                       released_bytes=sum(r['bytes'] for r in released), failure=failure,
                       proposed_release_bytes=listing['total_bytes'], archive_metrics=archive_metrics(closed['manifest']),
                       remaining=[c['source_ref'] for c in listing['candidates'] if canonical(c['source_ref']) not in done])
        # Final receipt is written once to the already exclusively reserved FD.
        # Failure here raises (never success); the journal preserves every prefix.
        data = memoryview(canonical(receipt))
        while data:
            size = os.write(receipt_fd, data)
            require(size > 0, 'short release receipt write; consult release-accounting')
            data = data[size:]
        os.fsync(receipt_fd)
        return receipt, target


def main():
    cli = parser(__doc__)
    cli.add_argument('--list', required=True, type=absolute)
    cli.add_argument('--expected-list-sha256', required=True)
    cli.add_argument('--ledger', required=True, type=absolute)
    cli.add_argument('--campaign-ledger', required=True, type=absolute)
    cli.add_argument('--header', required=True, type=absolute, help='Operator runtime header JSON: ' + ','.join(HEADER))
    cli.add_argument('--execute', action='store_true', help='OPERATOR ONLY; without it nothing is deleted')
    args = cli.parse_args()
    bindings = Resolver(load_json(args.roots), allowed_root_ids=args.allowed_root_id).bindings
    raw_roots = load_json(args.original_raw_roots) if args.original_raw_roots else None
    receipt, target = release(bindings, list_path=args.list, expected_sha256=args.expected_list_sha256, execute=args.execute,
                              ledger=args.ledger, campaign_ledger=args.campaign_ledger, original_raw_roots=raw_roots,
                              head=header(args.header))
    print(json.dumps(dict(receipt=str(target), status=receipt['status'], released_files=len(receipt['released']),
                          released_bytes=receipt['released_bytes']), sort_keys=True))
    return 0 if receipt['status'] == 'complete' else 4


if __name__ == '__main__':
    raise SystemExit(finish(main))
