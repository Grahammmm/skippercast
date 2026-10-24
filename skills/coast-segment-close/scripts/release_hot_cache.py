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
import fcntl
import json
import os
from pathlib import Path
import stat

from close_common import (HEADER, Refused, Resolver, absolute, canonical, coast_ledger, directory_fd, find_root,
                          finish, header, load_json, observe, parser, relative_parts, require, sha256, verify_closed,
                          release_candidates, validate_schema, _consistency, write_once)

RECEIPT_SCHEMA = 'coast-segment-close-release-receipt-v1'


def lock(path):
    fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as error:
        os.close(fd)
        raise Refused('exclusive writer lock unavailable: ' + str(path)) from error
    return fd


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
    held = [lock(queue_root / 'close.lock'), lock(Path(str(ledger) + '.lock')), lock(Path(str(campaign_ledger) + '.lock'))]
    try:
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
        # Preflight complete; per-file recheck + unlink.
        released, failure = [], None
        for candidate in listing['candidates']:
            try:
                unlink_checked(queue_root, candidate)
                released.append(candidate['source_ref'])
            except (Refused, ValueError, OSError) as error:
                failure = dict(path=candidate['source_ref']['path'], error=str(error))
                break
        done = {canonical(r) for r in released}
        receipt = dict(schema=RECEIPT_SCHEMA, **head, campaign_segment_id=listing['campaign_segment_id'], close_id=listing['close_id'],
                       release_list_sha256=expected_sha256, status='partial' if failure else 'complete', released=released,
                       released_bytes=sum(r['bytes'] for r in released), failure=failure,
                       remaining=[c['source_ref'] for c in listing['candidates'] if canonical(c['source_ref']) not in done])
        target = Path(list_path).with_name('release-receipt.json')
        write_once(target, receipt)
        return receipt, target
    finally:
        for fd in held:
            os.close(fd)


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
