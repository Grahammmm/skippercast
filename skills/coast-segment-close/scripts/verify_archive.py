"""Archive-only verification and operator release-list proposal (rev4 4.3, 4.4, 7.8).

Reads ONLY the archive close directory and the raw mirror: the roots JSON may
bind only archive:/raw: namespaces, and --forbid names the hot campaign tree,
which no binding may overlap. Full shared-graph traversal (not a four-output
hash lookup) through the manifest table. Any failure exits 3 and writes NO list.
"""
import json
from pathlib import Path

from close_common import (HEADER, Refused, Resolver, absolute, finish, header, load_json, parser, release_candidates,
                          require, validate_schema, verify_closed, write_once, GraphValidator, _consistency)


def check_forbidden(bindings, forbid):
    for root_id, path in bindings.items():
        require(root_id.startswith(('archive:', 'raw:')), 'verify_archive binds archive/raw only, not ' + root_id)
        path = Path(path)
        require(not (path == forbid or path.is_relative_to(forbid) or forbid.is_relative_to(path)),
                'binding overlaps the forbidden hot tree: ' + root_id)


def verify(inner, *, original_queue_roots, original_raw_roots, head):
    """Return the release-list document (not yet written)."""
    archive_ids = [k for k in inner.bindings if k.startswith('archive:')]
    require(len(archive_ids) == 1, 'exactly one archive close binding required')
    closed = verify_closed(inner, archive_id=archive_ids[0], original_queue_roots=original_queue_roots,
                           original_raw_roots=original_raw_roots)
    manifest = closed['manifest']
    candidates = release_candidates(manifest)
    observations = [
        dict(code='archive_graph_closure', path='ARCHIVE-MANIFEST.json', expected=closed['manifest_ref']['sha256'],
             observed=closed['manifest_ref']['sha256']),
        dict(code='segment_ledger_tip', path='ledger/segment-ledger.jsonl', expected=closed['segment_tip'], observed=closed['segment_tip']),
        dict(code='campaign_ledger_tip', path='ledger/campaign-ledger.jsonl', expected=closed['campaign_tip'], observed=closed['campaign_tip']),
        dict(code='retained_objects_rehashed', path='ARCHIVE-MANIFEST.json', expected=str(len(manifest['files'])),
             observed=str(len(manifest['files']))),
    ]
    release = dict(schema='coast-release-list-v1', **head, campaign_segment_id=manifest['campaign_segment_id'],
                   close_id=manifest['close_id'], manifest=closed['manifest_ref'], segment_ledger_snapshot=closed['segment_ref'],
                   campaign_ledger_snapshot=closed['campaign_ref'], inventory=manifest['inventory'],
                   segment_tip_sha256=closed['segment_tip'], campaign_tip_sha256=closed['campaign_tip'],
                   candidates=candidates, validation_observations=observations, total_files=len(candidates),
                   total_bytes=sum(c['size'] for c in candidates))
    validate_schema(release)
    _consistency(release)
    GraphValidator(closed['resolver'], raw_provenance=closed['envelopes']).document(release, root_id=closed['queue_id'])
    return release


def main():
    cli = parser(__doc__)
    cli.add_argument('--archive', required=True, type=absolute)
    cli.add_argument('--forbid', required=True, type=absolute, help='Entire hot campaign tree C; never read')
    cli.add_argument('--original-queue-roots', required=True, type=absolute,
                     help='Independently admitted {queue:<segment>: ORIGINAL_ABS_ROOT}; spelling only, never opened')
    cli.add_argument('--header', required=True, type=absolute, help='Card-authenticated runtime header JSON: ' + ','.join(HEADER))
    cli.add_argument('--out', required=True, type=absolute)
    args = cli.parse_args()
    bindings = load_json(args.roots)
    check_forbidden(bindings, args.forbid)
    inner = Resolver(bindings, allowed_root_ids=args.allowed_root_id)
    archive_ids = [k for k in inner.bindings if k.startswith('archive:')]
    require(len(archive_ids) == 1 and inner.bindings[archive_ids[0]] == args.archive, '--archive differs from the archive binding')
    raw_roots = load_json(args.original_raw_roots) if args.original_raw_roots else None
    release = verify(inner, original_queue_roots=load_json(args.original_queue_roots), original_raw_roots=raw_roots,
                     head=header(args.header))
    raw = write_once(args.out, release)
    from close_common import sha256
    print(json.dumps(dict(release_list=str(args.out), sha256=sha256(raw), total_files=release['total_files'],
                          total_bytes=release['total_bytes'], authorization=False,
                          note='Post this SHA independently; booleans/observations never authorize release.'), sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(finish(main))
