"""Archive one quiescent, fully accepted campaign segment (rev4 4.3, 7.8).

Order (acyclic): freeze -> closure traversal -> copy + re-hash every retained
object -> ARCHIVE-MANIFEST.json -> `archived` ledger row (segment + campaign
index, via coast_ledger.append_index; this script is the ONLY archived writer)
-> ledger snapshots into the archive. Never deletes, never writes raw, never
overwrites: the close-id directory must be new and empty.
"""
import json
import os
from pathlib import Path
import shutil

from close_common import (CAMPAIGN_SNAPSHOT, HEADER, MANIFEST, SEGMENT_SNAPSHOT, RecordingResolver, Refused,
                          Resolver, absolute, canonical, check_inventory, coast_ledger, collect_envelopes, excluded,
                          find_root, finish, header, load_json, loads, locate, observe, parser, require,
                          retained_path, sha256, traverse, write_once, write_retained, GraphValidator)
from close_common import archive_metrics, quiescent

DEFAULT_RESERVE = 200 * 10**9


def tip(raw):
    lines = raw.splitlines(keepends=True)
    return sha256(lines[-1]) if lines else coast_ledger.GENESIS


def archive(resolver, *, campaign_path, ledger, campaign_ledger, head, reserve_bytes=DEFAULT_RESERVE,
            close_id, extra_documents=()):
    """Return the result dict; raises Refused before any ledger write on failure.

    ``resolver`` is the operator-bound hot Resolver (queue, raw, archive and any
    repo roots). ``extra_documents`` lets offline tests add explicitly enumerated
    producer receipts as roots; the CLI never discovers any.
    """
    bindings = resolver.bindings
    queue_id = find_root(bindings, 'queue:')
    archive_id = find_root(bindings, 'archive:')
    raw_id = 'raw:campaign' if 'raw:campaign' in bindings else None
    segment_id = queue_id.split(':', 1)[1]
    require(archive_id == 'archive:' + segment_id + ':' + close_id, 'archive root id must be archive:<segment>:<close-id>')
    dest = Path(bindings[archive_id])
    require(locate(bindings, ledger)[0] == queue_id, 'segment ledger must live in the campaign segment root')
    with quiescent(bindings[queue_id]):
        if (dest / MANIFEST).exists():
            return reconcile(resolver, campaign_path=campaign_path, ledger=ledger, campaign_ledger=campaign_ledger,
                             head=head, close_id=close_id)
        require(not any(dest.iterdir()), 'close-id archive directory must be new and empty (never overwritten)')
        segment_raw = Path(ledger).read_bytes()
        campaign_raw = Path(campaign_ledger).read_bytes() if Path(campaign_ledger).exists() else b''
        rows = coast_ledger.verify_bytes(segment_raw)
        campaign_rows = coast_ledger.verify_bytes(campaign_raw)
        require(not any(r['kind'] == 'archived' and r['close_id'] == close_id for r in rows), 'close-id already used')
        campaign_root, campaign_rel = locate(bindings, campaign_path)
        require(campaign_root == queue_id, 'campaign inventory must live in the segment root')
        ident, _ = observe(bindings[queue_id], campaign_rel)
        campaign_ref = dict(root_id=queue_id, **ident)
        campaign = loads(resolver.read(campaign_ref))
        require(campaign.get('schema') == 'coast-campaign-v1' and campaign['campaign_segment_id'] == segment_id,
                'inventory is not this campaign segment')
        selected = check_inventory(resolver, campaign, rows)
        envelopes = collect_envelopes(resolver, rows)
        recorder = RecordingResolver(resolver)
        for name in ('original_raw_roots', 'original_queue_roots'):
            if hasattr(resolver, name):
                setattr(recorder, name, getattr(resolver, name))
        def lookup(root_id, path):
            found, _ = observe(bindings[root_id], path)
            return dict(root_id=root_id, **found)
        recorder.read(campaign_ref)  # the frozen inventory itself is retained
        # Every ledger row (selected AND superseded verdicts) is a closure root.
        traverse(recorder, [campaign] + rows + campaign_rows + list(extra_documents), root_id=queue_id,
                 envelopes=envelopes, head=head, lookup=lookup)
        reads = [recorder.reads[k] for k in sorted(recorder.reads)]
        raw_by_identity = {(r['sha256'], r['bytes']): r for r in reads if r['root_id'] == raw_id}
        files, copies, candidates = [], {}, []
        for ref in reads:
            if ref['root_id'].startswith(('archive:', 'raw:')):
                continue  # already in a retained namespace
            require(not excluded(ref), 'required reference points to excluded scratch/lease/SQLite: ' + ref['path'])
            require(ref['root_id'] in (queue_id,) or ref['root_id'].startswith('repo:'), 'unsupported source namespace ' + ref['root_id'])
            raw_match = raw_by_identity.get((ref['sha256'], ref['bytes'])) if ref['path'].split('/')[0] == 'cache' else None
            if raw_match is not None:
                retained = raw_match
            else:
                relative = retained_path(ref)
                retained = dict(root_id=archive_id, path=relative, sha256=ref['sha256'], bytes=ref['bytes'])
                copies.setdefault(relative, ref)
            files.append(dict(source_ref=ref, retained_ref=retained))
            if ref['root_id'] == queue_id and ref['path'].split('/')[0] == 'cache':
                ident, st = observe(bindings[queue_id], ref['path'])
                require(ident['sha256'] == ref['sha256'] and ident['bytes'] == ref['bytes'], 'cache file changed during close')
                candidates.append(dict(source_ref=ref, device=st.st_dev, inode=st.st_ino, size=st.st_size, mtime_ns=st.st_mtime_ns))
        need = sum(r['bytes'] for r in copies.values())
        require(shutil.disk_usage(dest).free - need >= reserve_bytes, 'insufficient archive capacity after reserve')
        for relative, ref in sorted(copies.items()):
            write_retained(dest, relative, resolver.read(ref))
        for item in files:  # re-hash every retained object after copying
            resolver.read(item['retained_ref'], retain=False)
        manifest = dict(schema='coast-archive-manifest-v1', **head, campaign_segment_id=segment_id, close_id=close_id,
                        inventory=campaign_ref, selected_verdicts=[r['verdict_file'] for r in selected],
                        original_segment_tip_sha256=tip(segment_raw), original_campaign_tip_sha256=tip(campaign_raw),
                        files=files, lineage_snapshot=campaign_ref, cache_candidates=candidates)
        GraphValidator(resolver, raw_provenance=envelopes).document(manifest, root_id=archive_id)
        write_once(dest / MANIFEST, manifest)
        manifest_ref = dict(root_id=archive_id, path=MANIFEST, **{k: v for k, v in observe(dest, MANIFEST)[0].items() if k != 'path'})
        return complete(resolver, manifest, manifest_ref, selected, envelopes, ledger, campaign_ledger)


def complete(resolver, manifest, manifest_ref, selected, envelopes, ledger, campaign_ledger):
    """Same writer, immutable payload; append_index already reconciles exact keys."""
    archive_id = manifest_ref['root_id']
    queue_id = 'queue:' + manifest['campaign_segment_id']
    dest = resolver.bindings[archive_id]
    last = selected[-1]
    payload = dict(schema='coast-segment-ledger-v1', **{k: manifest[k] for k in HEADER},
                   campaign_segment_id=manifest['campaign_segment_id'],
                   coordinator_segment_id=last['coordinator_segment_id'], plan_id=last['plan_id'],
                   plan_sha256=last['plan_sha256'], ledger_role='segment', segment_row_sha256=None, kind='archived',
                   close_id=manifest['close_id'], manifest=manifest_ref, inventory=manifest['inventory'],
                   previous_segment_tip_sha256=manifest['original_segment_tip_sha256'],
                   previous_campaign_tip_sha256=manifest['original_campaign_tip_sha256'])
    appended = coast_ledger.append_index(ledger, campaign_ledger, payload, writer='archive_segment.py',
                                         resolver=resolver, root_id=queue_id, raw_provenance=envelopes)
    snapshots = {}
    for source, relative, digest in ((ledger, SEGMENT_SNAPSHOT, appended['segment_row_sha256']),
                                    (campaign_ledger, CAMPAIGN_SNAPSHOT, appended['campaign_row_sha256'])):
        raw = Path(source).read_bytes()
        require(tip(raw) == digest, 'ledger changed after the archived row; use a new close-id')
        target = Path(dest) / relative
        if target.exists() or target.is_symlink():
            ident, _ = observe(dest, relative)
            require((ident['sha256'], ident['bytes']) == (sha256(raw), len(raw)), 'existing snapshot differs; never overwritten')
        else:
            write_retained(dest, relative, raw)
        snapshots[relative] = dict(root_id=archive_id, path=relative, sha256=sha256(raw), bytes=len(raw))
    copied = {canonical(i['retained_ref']): i['retained_ref']['bytes'] for i in manifest['files']
              if i['retained_ref']['root_id'] == archive_id}
    return dict(manifest=manifest_ref, archived_row_sha256=appended['segment_row_sha256'],
                campaign_row_sha256=appended['campaign_row_sha256'], snapshots=snapshots,
                retained_files=len(manifest['files']), copied_bytes=sum(copied.values()),
                cache_candidates=len(manifest['cache_candidates']), metrics=archive_metrics(manifest),
                envelopes=envelopes, scientific_acceptance=False)


def reconcile(resolver, *, campaign_path, ledger, campaign_ledger, head, close_id):
    """Only manifest-durable crashes are recoverable. Earlier residue stays held.

    Revalidate the immutable manifest, original graph and frozen ledger prefixes.
    No new close, changed metadata, appended correction or differing snapshot can
    reuse this close-id. No original evidence is overwritten or removed.
    """
    aid = find_root(resolver.bindings, 'archive:')
    qid = find_root(resolver.bindings, 'queue:')
    dest = resolver.bindings[aid]
    ident, _ = observe(dest, MANIFEST)
    manifest_ref = dict(root_id=aid, **ident)
    manifest = loads(resolver.read(manifest_ref))
    require(manifest['close_id'] == close_id and manifest['campaign_segment_id'] == qid.split(':', 1)[1],
            'reconciliation close identity differs')
    require({k: manifest[k] for k in HEADER} == head, 'reconciliation runtime payload differs')
    root, relative = locate(resolver.bindings, campaign_path)
    ident, _ = observe(resolver.bindings[root], relative)
    require(dict(root_id=root, **ident) == manifest['inventory'], 'reconciliation inventory differs')
    prefixes = []
    for source, key in ((ledger, 'original_segment_tip_sha256'), (campaign_ledger, 'original_campaign_tip_sha256')):
        raw = Path(source).read_bytes() if Path(source).exists() else b''
        rows = coast_ledger.verify_bytes(raw)
        if rows and rows[-1]['kind'] == 'archived' and rows[-1]['close_id'] == close_id:
            require(rows[-1]['manifest'] == manifest_ref, 'reconciliation archived payload differs')
            raw = b''.join(raw.splitlines(keepends=True)[:-1])
            rows = rows[:-1]
        require(tip(raw) == manifest[key], 'reconciliation frozen ledger prefix differs')
        prefixes.append(rows)
    campaign = loads(resolver.read(manifest['inventory']))
    selected = check_inventory(resolver, campaign, prefixes[0])
    require([r['verdict_file'] for r in selected] == manifest['selected_verdicts'], 'reconciliation verdicts differ')
    envelopes = collect_envelopes(resolver, prefixes[0])
    GraphValidator(resolver, raw_provenance=envelopes).document(manifest, root_id=aid)
    def lookup(root_id, path):
        found, _ = observe(resolver.bindings[root_id], path)
        return dict(root_id=root_id, **found)
    traverse(resolver, [campaign] + prefixes[0] + prefixes[1], root_id=qid,
             envelopes=envelopes, head=head, lookup=lookup)
    return complete(resolver, manifest, manifest_ref, selected, envelopes, ledger, campaign_ledger)


def main():
    cli = parser(__doc__)
    cli.add_argument('--campaign', required=True, type=absolute)
    cli.add_argument('--src', required=True, type=absolute, help='Campaign segment root C (must equal the queue binding)')
    cli.add_argument('--dest', required=True, type=absolute, help='New empty close directory A (must equal the archive binding)')
    cli.add_argument('--close-id', required=True)
    cli.add_argument('--ledger', required=True, type=absolute)
    cli.add_argument('--campaign-ledger', required=True, type=absolute)
    cli.add_argument('--header', required=True, type=absolute, help='Card-authenticated runtime header JSON: ' + ','.join(HEADER))
    cli.add_argument('--reserve-bytes', type=int, default=DEFAULT_RESERVE)
    args = cli.parse_args()
    bindings = load_json(args.roots)
    resolver = Resolver(bindings, allowed_root_ids=args.allowed_root_id)
    if args.original_raw_roots:
        resolver.original_raw_roots = load_json(args.original_raw_roots)
    require(Path(resolver.bindings[find_root(resolver.bindings, 'queue:')]) == args.src, '--src differs from the queue binding')
    require(Path(resolver.bindings[find_root(resolver.bindings, 'archive:')]) == args.dest, '--dest differs from the archive binding')
    result = archive(resolver, campaign_path=args.campaign, ledger=args.ledger, campaign_ledger=args.campaign_ledger,
                     head=header(args.header), reserve_bytes=args.reserve_bytes, close_id=args.close_id)
    print(json.dumps(result, sort_keys=True, allow_nan=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(finish(main))
