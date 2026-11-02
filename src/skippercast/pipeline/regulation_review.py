"""Collect official review evidence; apply explicit, hash-bound review decisions.

Collection never approves a rule. Read the packet, edit the registry, then supply
a decision for each source and a fingerprint of the reviewed legal content.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import re
from pathlib import Path
import sys
from zoneinfo import ZoneInfo

from ..platform.contracts import REPO, ID, atomic_json, read_json, within
from .collect import Client, source, stamp
from .parsers import watch_content
from .regulations import content_hash, regulatory_snapshot, validate_bindings, watch_jobs


def jurisdiction_files(ident, root=REPO):
    if not ID.fullmatch(ident):
        raise ValueError('Invalid jurisdiction ID')
    jurisdiction = read_json(within(root, f'jurisdictions/{ident}.json'))
    registry_path = within(root / 'dist', jurisdiction['regulations_asset'])
    registry = read_json(registry_path)
    validate_bindings(jurisdiction, registry)
    return jurisdiction, registry, registry_path


def collect_packet(ident, output, root=REPO, now=None):
    now = now or datetime.now(timezone.utc)
    jurisdiction, registry, _ = jurisdiction_files(ident, root)
    output = Path(output)
    if output.exists() and not output.is_dir():
        raise ValueError('Packet output is not a folder')
    if output.exists() and any(output.iterdir()):
        raise ValueError('Use a new packet directory; preserve previous evidence')
    output.mkdir(parents=True, exist_ok=True)

    def fetch(job):
        source_id = job[0]
        if not ID.fullmatch(source_id):
            raise ValueError('Invalid source ID')
        class ReviewClient(Client):
            def get(self, url, as_json=False, as_pdf=False, as_binary=False):
                if as_pdf:
                    body = super().get(url, as_pdf=True, as_binary=True)
                    if not body.startswith(b'%PDF-'):
                        raise ValueError('Expected PDF')
                    (output / (source_id + '.pdf')).write_bytes(body)
                    return {'content_sha256': hashlib.sha256(body).hexdigest(), 'normalization': 'pdf-bytes-v1',
                            'interpretation': 'manual review required', 'permission_to_fish': None}
                body = super().get(url, as_json, as_pdf, as_binary)
                if isinstance(body, str):
                    (output / (source_id + '.html')).write_text(body)
                    (output / (source_id + '.txt')).write_text(watch_content(body))
                return body
        return source_id, source(*job, now=now, client_factory=ReviewClient)

    with ThreadPoolExecutor(max_workers=4) as pool:
        sources = dict(pool.map(fetch, watch_jobs(jurisdiction['watches'])))
    packet = {'schema_version': 1, 'jurisdiction_id': ident, 'collected_at': stamp(now),
              'completed_at': stamp(), 'rules_content_sha256': content_hash(registry), 'sources': sources}
    atomic_json(output / 'packet.json', packet)
    atomic_json(output / 'coverage.json', coverage(registry, sources, now))
    return packet


def coverage(registry, sources, now, source_scope_ids=None):
    snapshot = regulatory_snapshot(sources, now, registry, source_scope_ids)
    local_date = now.astimezone(ZoneInfo(registry['timezone'])).date().isoformat()
    report = {'jurisdiction_id': registry['jurisdiction_id'], 'revision': registry['revision'],
            'reviewed_at': registry['reviewed_at'], 'valid_through': registry['valid_through'],
            'rules_review_status': snapshot['rules_review_status'],
            'source_scope_ids': snapshot.get('source_scope_ids'),
            'valid_for_current_date': registry['valid_from'] <= local_date <= registry['valid_through'],
            'checked_at': snapshot['checked_at'], 'review_required': snapshot['review_required'],
            'checks': snapshot['checks'],
            'areas': {p['id']: {'name': p['name'], 'required_sources': p['source_ids'],
                'live_clearance_required': p.get('live_clearance_required', False),
                'issues': [s for s in p['source_ids'] if snapshot['checks'][s]['status'] != 'unchanged']}
                for p in registry.get('area_notices', [])},
            'species': {ident: {'name': p['name'], 'required_sources': p['source_ids'],
                'issues': [s for s in p['source_ids'] if snapshot['checks'][s]['status'] != 'unchanged']}
                for ident, p in registry['species'].items()}}
    if source_scope_ids is not None:
        # Assessment describes coverage, never approval. Keep conservative legacy
        # issues (including omitted sources) and required_sources unchanged.
        for group in ('species', 'areas'):
            for row in report[group].values():
                omitted = [s for s in row['required_sources']
                           if snapshot['checks'][s]['status'] == 'out-of-scope']
                row['out_of_scope_sources'] = omitted
                row['assessment_status'] = ('evaluated' if not omitted else
                    'not-evaluated' if len(omitted) == len(row['required_sources']) else 'partial')
    return report


def _check_shapes(packet, decision):
    """Name a malformed field (never its value) before any review rule runs."""
    def _iso(value):
        try:
            return isinstance(value, str) and bool(datetime.fromisoformat(value.replace('Z', '+00:00')))
        except ValueError:
            return False
    if not isinstance(packet, dict) or not isinstance(decision, dict):
        raise ValueError('packet and decision must be objects')
    if not _iso(decision.get('reviewed_at')):
        raise ValueError('decision.reviewed_at must be an ISO time string')
    if not isinstance(decision.get('sources', {}), dict):
        raise ValueError('decision.sources must be an object')
    for ident, choice in decision.get('sources', {}).items():
        if not isinstance(choice, dict) or not isinstance(choice.get('note', ''), str):
            raise ValueError(f'decision.sources.{ident} must be an object')
    if not isinstance(packet.get('sources'), dict):
        raise ValueError('packet.sources must be an object')
    for ident, record in packet['sources'].items():
        if not isinstance(record, dict) or not isinstance(record.get('data') or {}, dict):
            raise ValueError(f'packet.sources.{ident} must be an object')
        if record.get('data_retrieved_at') not in (None, '') and not _iso(record['data_retrieved_at']):
            raise ValueError(f'packet.sources.{ident}.data_retrieved_at must be an ISO time string')


def approved_registry(registry, jurisdiction, packet, decision, now=None):
    """Pure review gate: fail on stale, changed, cross-jurisdiction or incomplete evidence."""
    now = now or datetime.now(timezone.utc)
    _check_shapes(packet, decision)
    validate_bindings(jurisdiction, registry)
    if packet.get('jurisdiction_id') != jurisdiction['id'] or decision.get('jurisdiction_id') != jurisdiction['id']:
        raise ValueError('Review belongs to another jurisdiction')
    if decision.get('rules_content_sha256') != content_hash(registry):
        raise ValueError('Legal content changed since the review decision')
    if set(decision.get('reviewed_species', [])) != set(registry['species']):
        raise ValueError('Every published species needs an explicit review')
    if set(decision.get('sources', {})) != set(registry['sources']):
        raise ValueError('Every required source needs a review decision')
    reviewed = datetime.fromisoformat(decision['reviewed_at'].replace('Z', '+00:00'))
    if reviewed.tzinfo is None or not -1 <= (now-reviewed).total_seconds()/3600 <= 36:
        raise ValueError('Review time must be recent and timezone-aware')
    if not isinstance(decision.get('revision'), str) or not decision['revision']:
        raise ValueError('A review revision is required')
    data = deepcopy(registry)
    for ident, spec in data['sources'].items():
        record = packet['sources'].get(ident, {})
        choice = decision['sources'][ident]
        observed = record.get('data') or {}
        retrieved = datetime.fromisoformat(record['data_retrieved_at'].replace('Z', '+00:00')) if record.get('data_retrieved_at') else None
        if choice.get('content_sha256') != observed.get('content_sha256') or len(choice.get('note', '').strip()) < 20:
            raise ValueError(f'Review must name the inspected hash and conclusion: {ident}')
        if choice.get('decision') not in ('approve', 'hold'):
            raise ValueError(f'Choose approve or hold for {ident}')
        if record.get('url') != spec['url']:
            raise ValueError(f'Source identity changed for {ident}')
        if choice['decision'] == 'approve':
            if record.get('status') != 'ok' or not retrieved or retrieved.tzinfo is None or not -1 <= (now-retrieved).total_seconds()/3600 <= 36:
                raise ValueError(f'No fresh matching source for {ident}')
            if not re.fullmatch(r'[a-f0-9]{64}', choice.get('content_sha256') or '') or not observed.get('normalization'):
                raise ValueError(f'Approval requires a valid fingerprint and normalizer: {ident}')
            if retrieved > reviewed:
                raise ValueError(f'Review predates source retrieval: {ident}')
        spec['approved_content_sha256'] = choice['content_sha256'] if choice['decision'] == 'approve' else None
        spec['reviewed_at'] = decision['reviewed_at']
        spec['review_note'] = choice['note']
        if choice['decision'] == 'approve' and spec['normalization'] != observed['normalization']:
            raise ValueError(f'Normalizer changed after source review: {ident}')
    data['revision'] = decision['revision']
    data['reviewed_at'] = decision['reviewed_at']
    data['review_record'] = decision.get('record_path')
    data['approved_rules_content_sha256'] = decision['rules_content_sha256']
    return regulatory_snapshot(packet['sources'], now, data)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    collect = commands.add_parser('collect')
    collect.add_argument('--jurisdiction', required=True)
    collect.add_argument('--output', type=Path, required=True)
    apply = commands.add_parser('apply')
    apply.add_argument('--jurisdiction', required=True)
    apply.add_argument('--packet', type=Path, required=True)
    apply.add_argument('--decision', type=Path, required=True)
    fingerprint = commands.add_parser('fingerprint')
    fingerprint.add_argument('--jurisdiction', required=True)
    args = parser.parse_args()
    try:
        _run(args)
    except (ValueError, OSError) as e:
        if args.command == 'fingerprint':
            raise
        print(f'regulation review refused: {e}', file=sys.stderr)
        return 1
    return 0


def _run(args):
    if args.command == 'collect':
        result = collect_packet(args.jurisdiction, args.output)
        print(json.dumps({'jurisdiction_id': args.jurisdiction, 'sources': {k: v['status'] for k,v in result['sources'].items()}}))
    else:
        jurisdiction, registry, path = jurisdiction_files(args.jurisdiction)
        if args.command == 'fingerprint':
            print(content_hash(registry))
        else:
            result = approved_registry(registry, jurisdiction, read_json(args.packet), read_json(args.decision))
            atomic_json(path, result, indent=2)
            print(json.dumps({'revision': result['revision'], 'review_required': result['review_required']}))


if __name__ == '__main__':
    raise SystemExit(main())
