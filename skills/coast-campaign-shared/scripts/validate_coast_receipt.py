"""Offline rev4 receipt validation: schema, confined refs and edge-aware graph.

Exit 0 means structurally self-consistent evidence, NEVER scientific acceptance.
Normal receipts always traverse the full supported graph. Integrity-error receipts
verify trusted identity snapshots but leave failed downstream expectations diagnostic.
"""
import argparse
import json
import os
from pathlib import Path
import sys

from jsonschema import Draft202012Validator, FormatChecker
from coast_refs import Resolver, REF_KEYS, canonical, loads, native_ref
from coast_sample import sample, window_dir, window_key

SHARED = Path(__file__).resolve().parents[1]
SCHEMAS = SHARED / 'schemas'
# Enumerated producer-native contracts. Only these explicitly named reference
# slots receive the original queue namespace. Unknown path-bearing fields refuse.
NATIVE_FIELDS = {
    'coastal-native-job-v1': {'source', 'review', 'source_row', 'rights.evidence.*'},
    'coastal-cached-observation-v1': {'source', 'facts.source', 'facts.source_auxiliary.*'},
    'coastal-stage-result-v1': {'artifacts.*', 'next_job.input_manifest'},
    'private-mapping-input-v2': {'source', 'review', 'source_row', 'valid_support', 'rights.evidence.*', 'native_facts.source', 'native_facts.source_auxiliary.*'},
    'coastal-mapping-run-v1': {'source', 'outputs.*'},
    'coastal-terrain-summary-v1': set(),
}
OBSERVATION_FIELDS = {'expected_packet', 'observed_packet', 'problems', 'observations'}
IDENTITY_ONLY_FIELDS = {'identity_provenance', 'run_author_provenance', 'posted_hashes', 'routing', 'thresholds', 'prompts'}
WORKFLOW_EDGES = {
    'context': 'coast-review-context-v1', 'admission': 'coast-admission-v1',
    'enqueue': 'coast-enqueue-receipt-v1', 'run': 'coast-run-summary-v1',
    'tier1': 'coast-tier1-screen-v1', 'open_report': 'coast-open-report-v1',
    'packet': 'coast-review-packet-v1', 'verdict_file': 'coast-review-verdict-v1',
    'routing': 'coast-review-routing-v1', 'manifest': 'coast-archive-manifest-v1',
}


def validate_schema(value):
    if not isinstance(value, dict) or not isinstance(value.get('schema'), str):
        raise ValueError('workflow receipt needs a schema')
    name = value['schema']
    if not name.startswith('coast-') or not name.endswith('-v1') or '/' in name or '\\' in name:
        raise ValueError('unknown workflow schema')
    path = SCHEMAS / (name + '.schema.json')
    if not path.is_file():
        raise ValueError('unknown workflow schema: ' + name)
    definition = loads(path.read_bytes())
    Draft202012Validator.check_schema(definition)
    validator = Draft202012Validator(definition, format_checker=FormatChecker())
    errors = sorted(validator.iter_errors(value), key=lambda e: str(list(e.path)))
    if errors:
        raise ValueError('schema ' + name + ': ' + '; '.join(e.message for e in errors[:3]))
    canonical(value)  # no nonfinite numbers even if supplied as Python object
    return value


def _consistency(value):
    name = value['schema']
    if name == 'coast-admission-v1':
        keys = [w['window_key'] for w in value['windows']]
        if len(set(keys)) != len(keys):
            raise ValueError('duplicate admission window_key')
        for w in value['windows']:
            if w['window_key'] != window_key(w['source_id'], w['grid_sha256'], w['idx']) or w['window_dir'] != window_dir(w['window_key']):
                raise ValueError('window identity/directory digest mismatch')
            if w['owner_segment_id'] != value['coordinator_segment_id']:
                raise ValueError('window owner differs from plan coordinator')
        # would_enqueue_count describes the producer dry-run list, not all
        # admission windows: held/cache-miss windows remain in windows[].
    if name == 'coast-run-summary-v1':
        keys = [w['window_key'] for w in value['windows']]
        partition = [k for group in value['partition'].values() for k in group]
        if len(set(keys)) != len(keys) or sorted(keys) != sorted(partition):
            raise ValueError('run partition does not cover each window exactly once')
        for w in value['windows']:
            if w['window_key'] not in value['partition'][w['state']]:
                raise ValueError('window state/partition mismatch')
        if value['ticks_used'] > value['max_ticks']:
            raise ValueError('ticks_used exceeds max_ticks')
    if name == 'coast-review-packet-v1':
        if value['integrity_ok']:
            population = value['population']

            # bridge hash is fetched from context in graph validation; structural
            # sample invariants remain enforced even before resolving the context.
            selected = value['sample']
            if selected['map_done'] != sorted(population['map_done']) or selected['eligible'] != sorted(population['eligible']):
                raise ValueError('packet sample population mismatch')
            target = max(8, (len(population['map_done']) + 7) // 8)
            if selected['target'] != target or selected['size'] != min(target,len(population['eligible'])) or len(selected['selected']) != selected['size']:
                raise ValueError('non-clamped sample')
            if set(population['eligible']) & set(population['flagged']):
                raise ValueError('flagged windows cannot be eligible')

        elif not any(f['severity'] == 'must' for f in value['flags']):
            raise ValueError('diagnostic packet must contain an integrity finding')
    if name == 'coast-open-report-v1':
        if value['integrity_ok'] != value['measurements_trusted']:
            raise ValueError('invalid integrity cannot trust measurements')
        if not value['integrity_ok'] and not value['problems']:
            raise ValueError('invalid open-report requires diagnostic problem')
    if name == 'coast-segment-ledger-v1':
        if (value['ledger_role'] == 'campaign') != (value['segment_row_sha256'] is not None):
            raise ValueError('campaign index must pin segment row SHA')
    if name == 'coast-archive-manifest-v1':
        mapping = {}
        for item in value['files']:
            source, retained = item['source_ref'], item['retained_ref']
            if source['sha256'] != retained['sha256'] or source['bytes'] != retained['bytes']:
                raise ValueError('archive retained bytes differ from source')
            if not retained['root_id'].startswith(('archive:', 'raw:')):
                raise ValueError('archive retained_ref must use archive/raw')
            if source['path'].endswith(('ledger.jsonl','ARCHIVE-MANIFEST.json')):
                raise ValueError('archive manifest excludes ledger snapshots and itself')
            key = canonical(source)
            if key in mapping and mapping[key] != retained:
                raise ValueError('ambiguous archive mapping')
            mapping[key] = retained
    if name == 'coast-release-list-v1':
        if value['total_files'] != len(value['candidates']) or value['total_bytes'] != sum(c['size'] for c in value['candidates']):
            raise ValueError('release totals mismatch')


class GraphValidator:
    def __init__(self, resolver):
        self.resolver = resolver
        self.visiting = set()
        self.verified = set()

    def reference(self, ref, *, scope='full_graph', contract=None):
        structured = contract or ref['path'].endswith(('.json', '.jsonl'))
        if structured and ref['bytes'] > 32 * 1024 * 1024:
            raise ValueError('structured receipt exceeds 32 MiB validation bound')
        raw = self.resolver.read(ref, retain=bool(structured))
        if contract:
            document = loads(raw)
            if not isinstance(document, dict) or document.get('schema') != contract:
                raise ValueError('reference contract mismatch: ' + contract)
        key = (canonical(ref), scope, contract)
        if key in self.visiting:
            raise ValueError('cyclic receipt graph')
        if key in self.verified:
            return loads(raw) if contract or ref['path'].endswith('.json') else None
        self.visiting.add(key)
        try:
            doc = None
            if contract or ref['path'].endswith('.json'):
                doc = loads(raw)
                self.document(doc, root_id=ref['root_id'], scope=scope)
            elif ref['path'].endswith('.jsonl'):
                from coast_ledger import verify_bytes
                for row in verify_bytes(raw):
                    self.document(row, root_id=ref['root_id'])
            else:
                doc = None
            self.verified.add(key)
            return doc
        finally:
            self.visiting.remove(key)

    def document(self, doc, *, root_id, scope='full_graph'):
        if not isinstance(doc, dict):
            raise ValueError('referenced JSON document must be an object')
        name = doc.get('schema', '')
        if name.startswith('coast-'):
            validate_schema(doc)
            _consistency(doc)
            if scope == 'identity_snapshot':
                if name != 'coast-review-context-v1':
                    raise ValueError('identity_snapshot applies only to context edges')
                for key in IDENTITY_ONLY_FIELDS:
                    if key in WORKFLOW_EDGES:
                        self.reference(doc[key], contract=WORKFLOW_EDGES[key])
                    else:
                        self.walk(doc[key], root_id=root_id)
                return
            error_branch = ((name == 'coast-review-verdict-v1' and doc['evidence_status'] == 'invalid') or
                            (name == 'coast-open-report-v1' and not doc['integrity_ok']) or
                            (name == 'coast-segment-ledger-v1' and doc.get('validation_scope') == 'identity_snapshot'))
            if name == 'coast-review-context-v1' and doc['mode'] == 'diagnostic':
                raise ValueError('diagnostic context is not a full-graph scientific input')
            for key, child in doc.items():
                if key in OBSERVATION_FIELDS:
                    continue  # schema-validated diagnostic scalars, not Ref edges
                if key == 'context' and error_branch:
                    self.reference(child, scope='identity_snapshot', contract=WORKFLOW_EDGES[key])
                elif key in WORKFLOW_EDGES and child is not None:
                    self.reference(child, contract=WORKFLOW_EDGES[key])
                else:
                    self.walk(child, root_id=root_id)
            self.crosscheck(doc, error_branch)
        elif not name and set(doc) == {'version','edge_step_should_m','edge_step_must_m','mask_continuity_min','tier1_valid_fraction_min','tier1_edge_valid_min','tier1_slope_p99_max_deg','history'}:
            definition = loads((SHARED/'config/tier2-thresholds.schema.json').read_bytes())
            errors = list(Draft202012Validator(definition).iter_errors(doc))
            if errors:
                raise ValueError('threshold schema: ' + errors[0].message)
        elif name in NATIVE_FIELDS:
            self.walk_native(doc, root_id=root_id, contract=name)
        else:
            raise ValueError('unresolved-reference: unsupported JSON producer schema ' + repr(name))

    def walk(self, value, *, root_id):
        if isinstance(value, dict):
            if set(value) == REF_KEYS:
                self.reference(value)
            elif 'path' in value or 'root_id' in value:
                raise ValueError('unresolved-reference: untyped or unknown path-bearing field')
            elif isinstance(value.get('schema'),str):
                self.document(value, root_id=root_id)
            else:
                for child in value.values():
                    self.walk(child, root_id=root_id)
        elif isinstance(value, list):
            for child in value:
                self.walk(child, root_id=root_id)

    def walk_native(self, doc, *, root_id, contract):
        if not root_id.startswith('queue:'):
            raise ValueError('native adapter requires original queue root namespace')
        allowed = NATIVE_FIELDS[contract]
        def visit(value, path):
            slot = '.'.join(path)
            pattern = '.'.join('*' if p.isdecimal() else p for p in path)
            wildcard = '.'.join(path[:-1] + ['*'])
            if isinstance(value, dict):
                if (slot in allowed or pattern in allowed or wildcard in allowed) and 'path' in value:
                    self.reference(native_ref(value, root_id))
                elif 'path' in value or 'root_id' in value:
                    raise ValueError('unresolved-reference: unknown native ref slot ' + slot)
                elif value is not doc and 'schema' in value:
                    self.document(value, root_id=root_id)
                else:
                    for key, child in value.items():
                        visit(child, path + [key])
            elif isinstance(value, list):
                for i, child in enumerate(value):
                    visit(child, path + [str(i)])
        visit(doc, [])

    def crosscheck(self, doc, error_branch):
        name = doc['schema']
        if 'context' in doc:
            context = loads(self.resolver.read(doc['context']))
            for key in ('campaign_segment_id','coordinator_segment_id','plan_id','plan_sha256','review_round','attempt'):
                if doc[key] != context[key]:
                    raise ValueError('context identity/attempt mismatch: ' + key)
            if name == 'coast-review-packet-v1' and doc['integrity_ok']:
                expected = sample(doc['population']['map_done'], doc['population']['eligible'],
                                  plan_sha256=doc['plan_sha256'], bridge_sha256=context['bridge']['sha256'])
                if doc['sample'] != expected:
                    raise ValueError('deterministic sample mismatch')
        if name == 'coast-review-verdict-v1':
            report = loads(self.resolver.read(doc['open_report']))
            if report['context'] != doc['context'] or report['integrity_ok'] == error_branch:
                raise ValueError('verdict/open-report integrity or context mismatch')
            for key in ('expected_packet','observed_packet','reviewer_model','reviewer_provenance'):
                if doc[key] != report[key]:
                    raise ValueError('verdict/open-report mismatch: ' + key)
            context = loads(self.resolver.read(doc['context']))
            if doc['reviewer_model'] == context['run_author_model']:
                raise ValueError('same actual author/reviewer model')
        if name == 'coast-segment-ledger-v1' and doc['kind'] == 'verdict':
            verdict = loads(self.resolver.read(doc['verdict_file']))
            for key in ('verdict','packet','open_report','context','validation_scope'):
                if doc[key] != verdict[key]:
                    raise ValueError('ledger/verdict mismatch: ' + key)


def validate(value, resolver, *, root_id):
    """No public opt-down flag: the discriminated error union selects edge roles."""
    if root_id not in resolver.bindings:
        raise ValueError('unbound receipt root_id')
    graph = GraphValidator(resolver)
    graph.document(value, root_id=root_id)
    return value


def hash_dir(path):
    """Hash every regular file with the same no-follow resolver; no symlink skips."""
    path = Path(path).absolute()
    resolver = Resolver({'queue:hash': str(path)}, allowed_root_ids={'queue:hash'})
    result = []
    for directory, dirs, files in os.walk(path, followlinks=False):
        for name in dirs:
            if (Path(directory)/name).is_symlink():
                raise ValueError('hash-dir refuses symlink directory')
        for name in files:
            file = Path(directory)/name
            if file.is_symlink() or not file.is_file():
                raise ValueError('hash-dir refuses symlinks and nonregular files')
            # hash through a no-follow FD; reference verified again before output.
            from coast_refs import directory_fd, relative_parts
            parts = relative_parts(file.relative_to(path).as_posix())
            with directory_fd(file.parent) as fd:
                leaf = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW, dir_fd=fd)
                try:
                    import hashlib
                    digest = hashlib.sha256()
                    size = 0
                    with os.fdopen(leaf, 'rb', closefd=False) as stream:
                        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                            digest.update(chunk)
                            size += len(chunk)
                finally:
                    os.close(leaf)
            ref = dict(root_id='queue:hash',path=file.relative_to(path).as_posix(),sha256=digest.hexdigest(),bytes=size)
            resolver.read(ref, retain=False)
            result.append(ref)
    return sorted(result,key=lambda r:r['path'])


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('receipt', nargs='?', type=Path)
    parser.add_argument('--roots', type=Path)
    parser.add_argument('--allowed-root-id', action='append', default=[], help='Repeat card-admitted root IDs (independent of roots file)')
    parser.add_argument('--root-id', help='Original receipt namespace')
    parser.add_argument('--hash-dir', type=Path)
    args = parser.parse_args(argv)
    try:
        if args.hash_dir:
            result = hash_dir(args.hash_dir)
        else:
            if not args.receipt or not args.roots or not args.root_id or not args.allowed_root_id:
                parser.error('receipt requires --roots, --root-id and card-admitted --allowed-root-id')
            resolver = Resolver(loads(args.roots.read_bytes()), allowed_root_ids=args.allowed_root_id)
            validate(loads(args.receipt.read_bytes()), resolver, root_id=args.root_id)
            result = dict(status='structurally_valid', scientific_acceptance=False)
        print(json.dumps(result, sort_keys=True, allow_nan=False))
        return 0
    except (ValueError, OSError, KeyError, TypeError) as error:
        print(str(error), file=sys.stderr)
        return 3


if __name__ == '__main__':
    raise SystemExit(main())
