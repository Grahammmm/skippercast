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
import coast_native as native
import coast_raw as raw_provenance_contracts

SHARED = Path(__file__).resolve().parents[1]
SCHEMAS = SHARED / 'schemas'
# Enumerated producer-native contracts. Only these explicitly named reference
# slots receive the original queue namespace. Unknown path-bearing fields refuse.
NATIVE_FIELDS = {
    'coastal-segment-v1': set(),
    'coastal-frozen-discovery-catalog-v1': set(),
    'coastal-catalog-acquire-bridge-plan-v1': {'selections.*.source', 'selections.*.review', 'selections.*.source_row', 'selections.*.rights.evidence.*'},
    'coastal-catalog-acquire-bridge-dry-run-v1': {'decisions.*.source'},
    'coastal-catalog-acquire-bridge-receipt-v1': {'decisions.*.source', 'jobs.*.input_manifest'},
    native.STORE_JOB: {'input_manifest'},
    'coastal-native-job-v1': {'source', 'review', 'source_row', 'rights.evidence.*'},
    'coastal-private-input-review-v2': set(),
    'coastal-cached-observation-v1': {'source', 'facts.source', 'facts.source_auxiliary.*', 'facts.rights.evidence.*'},
    'coastal-stage-result-v1': {'artifacts.*', 'next_job.input_manifest'},
    'private-mapping-input-v2': {'source', 'review', 'source_row', 'segment', 'valid_support', 'rights.evidence.*', 'native_facts.source', 'native_facts.source_auxiliary.*', 'native_facts.rights.evidence.*'},
    'coastal-mapping-run-v1': {'source', 'segment', 'outputs.*'},
    'coastal-terrain-summary-v1': {'segment'},
}
OBSERVATION_FIELDS = {'expected_packet', 'observed_packet', 'problems', 'observations'}
IDENTITY_ONLY_FIELDS = {'identity_provenance', 'run_author_provenance', 'posted_hashes', 'routing', 'thresholds', 'prompts'}
WORKFLOW_EDGES = {
    'context': 'coast-review-context-v1', 'admission': 'coast-admission-v1',
    'enqueue': 'coast-enqueue-receipt-v1', 'run': 'coast-run-summary-v1',
    'tier1': 'coast-tier1-screen-v1', 'open_report': 'coast-open-report-v1',
    'packet': 'coast-review-packet-v1', 'verdict_file': 'coast-review-verdict-v1',
    'routing': 'coast-review-routing-v1', 'manifest': 'coast-archive-manifest-v1',
    'job': native.STORE_JOB, 'result': 'coastal-stage-result-v1',
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
    def __init__(self, resolver, *, raw_provenance=()):
        self.resolver = resolver
        self.visiting = set()
        self.verified = set()
        self.provenance = raw_provenance_contracts.Provenance(self)
        self.provenance.preflight(raw_provenance)

    def header(self, header):
        definition = loads((SCHEMAS / 'coast-native-execution-v1.schema.json').read_bytes())
        definition['required'] = raw_provenance_contracts.HEADER
        definition['properties']['schema'] = {'const': raw_provenance_contracts.ENVELOPE}
        errors = list(Draft202012Validator(definition, format_checker=FormatChecker()).iter_errors(header))
        if errors:
            raise ValueError('provenance header: ' + errors[0].message)

    def reference(self, ref, *, scope='full_graph', contract=None):
        structured = contract or ref['path'].endswith(('.json', '.jsonl'))
        if structured and ref['bytes'] > 32 * 1024 * 1024:
            raise ValueError('structured receipt exceeds 32 MiB validation bound')
        raw = self.resolver.read(ref, retain=bool(structured))
        if contract in (raw_provenance_contracts.ROW, raw_provenance_contracts.SNAPSHOT):
            rows = raw_provenance_contracts.parse_rows(raw, single=contract == raw_provenance_contracts.ROW)
            self.verified.add((canonical(ref), scope, contract))
            return rows
        if contract:
            document = loads(raw)
            if not isinstance(document, dict) or (contract != native.STORE_JOB and document.get('schema') != contract):
                raise ValueError('reference contract mismatch: ' + contract)
            if contract == native.STORE_JOB:
                native.check(document, contract)
                origins = getattr(self.resolver, 'original_queue_roots', self.resolver.bindings)
                if ref['root_id'] not in origins:
                    raise ValueError('missing original queue root binding')
                native.job_location(document, ref, origins[ref['root_id']])
        if structured and ref['path'].endswith('.json'):
            candidate = loads(raw)
            if isinstance(candidate, dict) and candidate.get('schema') == raw_provenance_contracts.ENVELOPE:
                if not self.provenance.preflighting and canonical(ref) not in self.provenance.envelopes:
                    raise ValueError('envelope reached by traversal was not supplied up front')
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
                self.document(doc, root_id=ref['root_id'], scope=scope, contract=contract, ref=ref)
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

    def document(self, doc, *, root_id, scope='full_graph', contract=None, ref=None):
        if not isinstance(doc, dict):
            raise ValueError('referenced JSON document must be an object')
        name = doc.get('schema', '')
        if not isinstance(name, str):
            raise ValueError('native/workflow schema must be a string')
        if contract == native.STORE_JOB:
            if name:
                raise ValueError('Store job must retain schema-less producer bytes')
            name = contract
        if name == raw_provenance_contracts.ENVELOPE:
            if ref is None:
                raise ValueError('provenance envelope requires explicit supplied Ref')
            if self.provenance.preflighting:
                self.provenance.envelope(doc, ref)
            elif canonical(ref) not in self.provenance.envelopes:
                raise ValueError('envelope reached by traversal was not supplied up front')
            return
        if name == raw_provenance_contracts.VR:
            raw_provenance_contracts.vr_check(doc)
            self.provenance.lineage(doc, ref, root_id)
            from skippercast.coastal.handoff import vr_refinements as vr
            for value, expected in [(doc['source'], 'native-raster-v1'),
                                    (doc['supergrid_table'], vr.TABLE_CONTRACT)] + [(o['artifact'], vr.OUTPUT_CONTRACT) for o in doc['outputs']]:
                native.closed(value, ('path', 'sha256', 'bytes', 'contract'), ('path', 'sha256', 'bytes', 'contract'))
                if value['contract'] != expected or value['path'].endswith(('.json', '.jsonl')):
                    raise ValueError('VR edge contract mismatch')
                edge = native_ref(value, root_id)
                self.resolver.read(edge, retain=False, reject_structured=True)
                self.verified.add((canonical(edge), scope, expected))
            # Metadata must not smuggle additional dependencies.
            for key in ('bag', 'placement', 'convention', 'implementation', 'libs', 'limitations'):
                self.walk(doc[key], root_id=root_id)
            return
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
                if name == 'coast-admission-v1' and key == 'sources':
                    self.provenance.admission(doc)
                    for source in child:
                        for slot, values in source.items():
                            if slot != 'raw_provenance':
                                self.walk(values, root_id=root_id)
                        for edge in source['raw_provenance']:
                            if edge['root_id'] == 'raw:campaign':
                                self.reference(edge)
                            else:
                                self.reference(edge, contract=raw_provenance_contracts.ENVELOPE)
                    continue
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
            try:
                bound = self.provenance.lineage(doc, ref, root_id)
                native.check(doc, name, lineage_bound=bound)
                if name != native.STORE_JOB:
                    self.check_producer(doc)
            except (KeyError, TypeError, IndexError) as error:
                raise ValueError('malformed native producer: ' + name) from error
            self.walk_native(doc, root_id=root_id, contract=name, ref=ref)
        else:
            raise ValueError('unresolved-reference: unsupported JSON producer schema ' + repr(name))

    def walk(self, value, *, root_id):
        if isinstance(value, dict):
            if set(value) == REF_KEYS:
                document = self.reference(value)
                if isinstance(document, dict) and document.get('schema') == raw_provenance_contracts.ENVELOPE:
                    raise ValueError('envelope pinned outside admission raw_provenance')
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

    def walk_native(self, doc, *, root_id, contract, ref=None):
        if not root_id.startswith('queue:'):
            raise ValueError('native adapter requires original queue root namespace')
        allowed = NATIVE_FIELDS[contract]
        def visit(value, path):
            slot = '.'.join(path)
            pattern = '.'.join('*' if p.isdecimal() else p for p in path)
            wildcard = '.'.join(path[:-1] + ['*'])
            if isinstance(value, dict):
                if (slot in allowed or pattern in allowed or wildcard in allowed) and 'path' in value:
                    if set(value) - {'path', 'sha256', 'bytes', 'contract', 'kind'}:
                        raise ValueError('unresolved-reference: unknown native ref field ' + slot)
                    self.native_edge(value, root_id, contract, pattern, doc)
                elif 'path' in value or 'root_id' in value:
                    raise ValueError('unresolved-reference: unknown native ref slot ' + slot)
                elif value is not doc and 'schema' in value and value['schema'] not in native.INLINE and not (contract.startswith('coastal-catalog-acquire-bridge-') and slot == 'catalog'):
                    self.document(value, root_id=root_id, ref=ref if slot == 'mapping_input' else None)
                else:
                    for key, child in value.items():
                        if contract == native.STORE_JOB and key == 'root' and not path:
                            continue  # independently bound original queue spelling; never opened
                        if key.endswith(('_path', '_ref', '_file')):
                            raise ValueError('unresolved-reference: unknown native path field ' + '.'.join(path + [key]))
                        visit(child, path + [key])
            elif isinstance(value, list):
                for i, child in enumerate(value):
                    visit(child, path + [str(i)])
        visit(doc, [])

    def native_edge(self, value, root_id, parent, slot, doc):
        contract = value.get('contract')
        if parent == 'coastal-stage-result-v1':
            supported = {
                'acquire': {'coastal-cached-observation-v1', 'coastal-native-job-v1'},
                'qualify': {'private-mapping-input-v2'},
                'map': {'coastal-mapping-run-v1', 'coastal-normalized-terrain-v1', 'coastal-native-support-v2', 'coastal-terrain-summary-v1'},
            }
            if contract not in supported.get(doc['stage'], set()):
                raise ValueError('unsupported native result artifact contract')
        expected = {
            'source': 'native-raster-v1', 'facts.source': 'native-raster-v1',
            'native_facts.source': 'native-raster-v1',
            'valid_support': 'coastal-native-support-v2',
            'segment': 'coastal-segment-v1', 'review': 'coastal-private-input-review-v2',
            'outputs.terrain': 'coastal-normalized-terrain-v1',
            'outputs.mask': 'coastal-native-support-v2',
            'outputs.cells': 'coastal-terrain-summary-v1',
        }.get(slot)
        if slot.endswith('source_auxiliary.*'):
            expected = 'native-raster-auxiliary-v1'
        if slot.endswith('rights.evidence.*'):
            expected = 'coast-native-rights-evidence-v1'
        if parent == native.STORE_JOB and slot == 'input_manifest':
            # Store deliberately stores a three-field manifest Ref, dropping
            # the input contract. Stage is the independent contract selector.
            stage = doc['stage']
            expected = 'private-mapping-input-v2' if stage == 'map' else 'coastal-native-job-v1'
            if contract is not None and contract != expected:
                raise ValueError('native input contract mismatch')
            contract = expected
        elif expected and contract is not None and contract != expected:
            raise ValueError('native edge contract mismatch: ' + slot)
        elif not contract and expected:
            contract = expected
        ref = native_ref(value, root_id)
        if contract in native.BINARY:
            if ref['path'].endswith(('.json', '.jsonl')):
                raise ValueError('binary contract cannot hide structured provenance')
            self.resolver.read(ref, retain=False, reject_structured=True)
            self.verified.add((canonical(ref), 'full_graph', contract))
        elif contract:
            self.reference(ref, contract=contract)
        else:
            raise ValueError('held: native edge requires an explicit supported contract: ' + slot)

    def check_producer(self, doc):
        """Bounded native metadata adapters; no fetch, Store, or execution calls."""
        from skippercast.coastal.coordinator import catalog_bridge as bridge
        from skippercast.coastal.coordinator.segments import segment
        name = doc['schema']
        canonical(doc)
        fields = {
            'coastal-segment-v1': {'schema', 'segment_id', 'region', 'crs', 'bbox', 'bbox_crs84', 'synthetic', 'boundary_policy', 'halo_m', 'intersection_area_m2', 'outside_support_area_m2'},
            bridge.CATALOG: {'schema', 'region', 'bbox', 'source_revision', 'policy_revision', 'method_revision', 'plan_sha256', 'manifest_sha256', 'checked_from', 'checked_until', 'manifest_status', 'bounded_plan_finished', 'discovery_complete', 'unattempted_queries', 'lead_source_ids', 'usable_source_ids', 'candidates', 'mapping_accepted', 'execution_authorized', 'review_required', 'coordinator_boundary', 'catalog_id'},
            bridge.PLAN: {'schema', 'catalog_id', 'catalog_sha256', 'segment', 'synthetic', 'max_total_bytes', 'budget', 'selections'},
            bridge.DRY_RUN: {'schema', 'plan_sha256', 'catalog', 'segment_id', 'decisions', 'selected_source_ids', 'held_source_ids', 'caps', 'network_requests', 'source_opens', 'source_bytes_read', 'review_required', 'mapping_accepted', 'execution_authorized', 'note', 'would_enqueue'},
        }
        fields[bridge.RECEIPT] = (fields[bridge.DRY_RUN] - {'would_enqueue'}) | {'jobs', 'budget', 'segment'}
        if name in fields and set(doc) - fields[name]:
            raise ValueError('unknown producer field: ' + name)
        if name == 'coastal-segment-v1':
            from pyproj import Transformer
            bbox = doc['bbox']
            expected = segment(bbox[0], bbox[1], region=doc['region'])
            if any(doc.get(k) != v for k, v in expected.items()):
                raise ValueError('lattice ID/projected bbox mismatch')
            inverse = Transformer.from_crs('EPSG:3310', 'OGC:CRS84', always_xy=True)
            if 'bbox_crs84' in doc and not inverse_bounds_equal(doc['bbox_crs84'], list(inverse.transform_bounds(*bbox, densify_pts=41))):
                raise ValueError('lattice CRS84 bbox mismatch')
        elif name == bridge.CATALOG:
            bridge.check_catalog(doc)
        elif name == bridge.PLAN:
            bridge.check_budget(doc.get('budget'))
            if not isinstance(doc.get('selections'), list) or not 1 <= len(doc['selections']) <= bridge.MAX_JOBS:
                raise ValueError('bounded bridge selections required')
        elif name in (bridge.DRY_RUN, bridge.RECEIPT):
            if (doc.get('review_required') is not True or doc.get('execution_authorized') is not False
                    or doc.get('mapping_accepted') is not False or doc.get('network_requests') != 0):
                raise ValueError('bridge is review-required source-free metadata')
            if not isinstance(doc.get('would_enqueue' if name == bridge.DRY_RUN else 'jobs'), list):
                raise ValueError('bridge job population must be a list')

    def crosscheck(self, doc, error_branch):
        name = doc['schema']
        if name == 'coast-native-execution-v1':
            job = self.reference(doc['job'], contract=native.STORE_JOB)
            result = self.reference(doc['result'], contract='coastal-stage-result-v1')
            if not isinstance(job, dict) or not isinstance(result, dict):
                raise ValueError('native execution requires structured job and result')
            for key in ('job_id', 'stage', 'segment_id', 'lease_token', 'code_sha', 'deps_sha', 'params_sha', 'input_manifest_sha'):
                if result[key] != job[key]:
                    raise ValueError('native job/result identity mismatch: ' + key)
            directory = doc['job']['path'].removesuffix('/job.json')
            if doc['result']['root_id'] != doc['job']['root_id'] or doc['result']['path'] != directory + '/output/result.json':
                raise ValueError('native result output location mismatch')
            expected_logs = {directory + '/stdout.log', directory + '/stderr.log'}
            if {r['path'] for r in doc['logs']} != expected_logs or any(r['root_id'] != doc['job']['root_id'] for r in doc['logs']):
                raise ValueError('native execution logs mismatch')
            for artifact in result['artifacts']:
                if not artifact['path'].startswith(directory + '/output/'):
                    raise ValueError('native result artifact outside owned output')
            if result['state'] == 'done':
                expected = {'acquire': 'coastal-native-job-v1', 'qualify': 'private-mapping-input-v2', 'map': 'coastal-mapping-run-v1'}[job['stage']]
                matching = [r for r in result['artifacts'] if r.get('contract') == expected]
                if len(matching) != 1:
                    raise ValueError('native result primary output identity mismatch')
                original = self.reference(native_ref(job['input_manifest'], doc['job']['root_id']),
                    contract='private-mapping-input-v2' if job['stage'] == 'map' else 'coastal-native-job-v1')
                output = self.reference(native_ref(matching[0], doc['job']['root_id']), contract=expected)
                if not isinstance(original, dict) or not isinstance(output, dict):
                    raise ValueError('native execution requires structured input/output')
                if job['stage'] == 'acquire' and output != original:
                    raise ValueError('acquire did not preserve original native manifest')
                if job['stage'] == 'qualify' and any(output[k] != original[k] for k in ('source', 'window', 'rights', 'review')):
                    raise ValueError('qualification output/input identity mismatch')
                if job['stage'] == 'map' and output['mapping_input'] != original:
                    raise ValueError('map output/input identity mismatch')
        if name == 'coast-admission-v1':
            try:
                self.admission(doc)
            except (KeyError, TypeError, IndexError) as error:
                raise ValueError('malformed admission producer binding') from error
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

    def admission(self, doc):
        from skippercast.coastal.coordinator import catalog_bridge as bridge
        from skippercast.coastal.coordinator.segments import from_bbox
        from skippercast.coastal.coordinator.stages import digest
        contracts = {'campaign': 'coast-campaign-v1', 'plan_file': bridge.PLAN,
                     'segment_record': 'coastal-segment-v1', 'catalog': bridge.CATALOG,
                     'dry_run': bridge.DRY_RUN, 'discovery': 'coast-discovery-evidence-v1'}
        values = {k: self.reference(doc[k], contract=v) for k, v in contracts.items()}
        campaign, plan, record, catalog, dry, discovery = (values[k] for k in contracts)
        if campaign['campaign_segment_id'] != doc['campaign_segment_id'] or discovery['catalog'] != doc['catalog']:
            raise ValueError('campaign/discovery binding mismatch')
        # Bound lattice expansion before the native producer constructs its list.
        from pyproj import Transformer
        import math
        west,south,east,north = campaign['bbox_crs84']
        if not (-180 <= west < east <= 180 and -90 <= south < north <= 90):
            raise ValueError('invalid campaign bbox')
        projected = Transformer.from_crs('OGC:CRS84','EPSG:3310',always_xy=True).transform_bounds(west,south,east,north,densify_pts=41)
        if not all(math.isfinite(v) for v in projected):
            raise ValueError('invalid campaign projected bounds')
        x0,y0,x1,y1 = projected
        if (math.ceil(x1/5000)-math.floor(x0/5000)) * (math.ceil(y1/5000)-math.floor(y0/5000)) > 4096:
            raise ValueError('campaign lattice exceeds 4096 record validation bound')
        records = from_bbox(campaign['bbox_crs84'], region=campaign['campaign_segment_id'])
        # Projected lattice fields remain exact. Only inverse projection is
        # subject to the measured, two-ULP libm portability bound.
        if not any({k:v for k,v in r.items() if k != 'bbox_crs84'} ==
                   {k:v for k,v in record.items() if k != 'bbox_crs84'} and
                   inverse_bounds_equal(record['bbox_crs84'], r['bbox_crs84']) for r in records):
            raise ValueError('campaign lattice record mismatch')
        if record['segment_id'] != doc['coordinator_segment_id'] or plan['segment'] != {k: record[k] for k in ('segment_id', 'bbox_crs84')}:
            raise ValueError('plan segment binding mismatch')
        if digest(plan) != doc['plan_sha256'] or dry['plan_sha256'] != doc['plan_sha256']:
            raise ValueError('plan digest binding mismatch')
        bridge.check_plan(plan, self.resolver.read(doc['catalog']), catalog)
        if dry['catalog'] != dict(sha256=doc['catalog']['sha256'], bytes=doc['catalog']['bytes'], catalog_id=catalog['catalog_id'], schema=bridge.CATALOG):
            raise ValueError('dry catalog binding mismatch')
        if (dry['segment_id'] != record['segment_id'] or doc['would_enqueue_count'] != len(dry['would_enqueue'])
                or any(doc[k] != dry[k] for k in ('selected_source_ids', 'held_source_ids'))):
            raise ValueError('dry population/segment binding mismatch')
        decisions = dry['decisions']
        if [d['source_id'] for d in decisions] != [s['source_id'] for s in plan['selections']]:
            raise ValueError('dry decisions population mismatch')
        selected = [d for d in decisions if d['state'] == 'selected']
        if any(d['state'] not in ('selected', 'held') or (d['state'] == 'selected' and d['holds']) for d in decisions):
            raise ValueError('dry decision state/holds mismatch')
        for decision, selection in zip(decisions, plan['selections']):
            if 'source' in decision and decision['source'] != selection['source']:
                raise ValueError('dry source differs from pinned plan')
        checked = dict(segment=plan['segment'], catalog_ref=dry['catalog'], decisions=decisions,
                       selections={s['source_id']: s for s in plan['selections']},
                       selected_bytes=sum(d['source']['bytes'] for d in selected))
        if checked['selected_bytes'] > plan['max_total_bytes'] or any(d['source']['bytes'] > plan['budget']['bytes'] for d in selected):
            raise ValueError('selected sources exceed plan budget')
        expected = bridge._receipt(bridge.DRY_RUN, plan, checked)
        selections = {s['source_id']: s for s in plan['selections']}
        expected['would_enqueue'] = [dict(stage='acquire', source_id=d['source_id'], native_job_sha256=digest(
            bridge.native_job(plan, selections[d['source_id']], d, dry['catalog']))) for d in selected]
        if expected != dry:
            raise ValueError('dry caps/native job binding mismatch')
        if [w['source_id'] for w in doc['windows']] != [s['source_id'] for s in plan['selections']]:
            raise ValueError('plan window population mismatch')
        source_ids = [s['source_id'] for s in doc['sources']]
        if len(set(source_ids)) != len(source_ids) or set(source_ids) != {s['source_id'] for s in plan['selections']}:
            raise ValueError('admission source population mismatch')
        sources = {s['source_id']: s for s in doc['sources']}
        for selection in plan['selections']:
            hot = native_ref(selection['source'], doc['plan_file']['root_id'])
            if hot not in sources[selection['source_id']]['hot_cache']:
                raise ValueError('source hot-cache binding mismatch')
        if not set(doc['selected_source_ids'] + doc['held_source_ids']) <= set(campaign['source_inventory']):
            raise ValueError('source absent from frozen campaign inventory')
        grids = {g['grid_sha256']: g for g in doc['grids']}
        if len(grids) != len(doc['grids']):
            raise ValueError('duplicate grid identity')
        for window, selection in zip(doc['windows'], plan['selections']):
            grid = grids[window['grid_sha256']]
            definition = grid.get('definition')
            if (not definition or digest(definition) != window['grid_sha256'] or window['idx'] != 0
                    or definition['pixel_window'] != selection['window'] or window['pixel_window'] != selection['window']
                    or definition['source_sha256'] != selection['source']['sha256'] or grid['source_id'] != window['source_id']):
                raise ValueError('single-selected grid/window binding mismatch')
            if window['window_key'] not in campaign['intended_windows']:
                raise ValueError('window absent from frozen campaign inventory')
            from pyproj import Transformer
            import math
            col, row, width, height = window['pixel_window']
            bridge._window(window['pixel_window'])
            if col + width > definition['width'] or row + height > definition['height']:
                raise ValueError('window outside raster grid')
            a,b,c,d,e,f = definition['affine_transform']
            x,y = col + width/2, row + height/2
            cx,cy = Transformer.from_crs(definition['raster_crs'], 'EPSG:3310', always_xy=True).transform(a*x+b*y+c,d*x+e*y+f)
            owner = f'seg:3310:{math.floor(cx/5000)*5000}:{math.floor(cy/5000)*5000}:5000'
            if owner != record['segment_id']:
                raise ValueError('pixel centre owner mismatch')
            from shapely.geometry import Polygon, box
            geographic = Transformer.from_crs(definition['raster_crs'], 'OGC:CRS84', always_xy=True)
            corners = [(col,row),(col+width,row),(col+width,row+height),(col,row+height)]
            points = []
            for start,end in zip(corners,corners[1:]+corners[:1]):
                for step in range(42):
                    px = start[0]+(end[0]-start[0])*step/42
                    py = start[1]+(end[1]-start[1])*step/42
                    points.append(geographic.transform(a*px+b*py+c,d*px+e*py+f))
            footprint = Polygon(points)
            if (not footprint.is_valid or footprint.is_empty
                    or footprint.intersection(box(*campaign['bbox_crs84'])).area <= 0
                    or footprint.intersection(box(*record['bbox_crs84'])).area <= 0
                    or any(abs(expected-observed) > 1e-10 for expected,observed in zip(footprint.bounds,window['footprint']))):
                raise ValueError('window footprint binding mismatch')
            overlaps = sorted(r['segment_id'] for r in records if footprint.intersection(box(*r['bbox_crs84'])).area > 0)
            if sorted(window['overlapping_segment_ids']) != overlaps:
                raise ValueError('window overlap inventory mismatch')


def inverse_bounds_equal(observed, expected):
    """Compare inverse-projected bounds within two representable doubles.

    Ubuntu 24.04 and 26.04 with pyproj 3.8.0 / PROJ 9.8.1 produce
    one/two-ULP latitude differences for the committed native lattice fixture.
    This is not a geographic epsilon: hashes, projected cells and pinned
    record-to-plan coordinates remain exact. No relative/decimal tolerance.
    """
    import math
    if not isinstance(observed, list) or len(observed) != 4:
        return False
    for actual, target in zip(observed, expected):
        if isinstance(actual, bool) or not isinstance(actual, (int, float)) or not math.isfinite(actual):
            return False
        lower = math.nextafter(math.nextafter(target, -math.inf), -math.inf)
        upper = math.nextafter(math.nextafter(target, math.inf), math.inf)
        if not lower <= actual <= upper:
            return False
    return True


def validate(value, resolver, *, root_id, raw_provenance=()):
    """No public opt-down flag: the discriminated error union selects edge roles."""
    if root_id not in resolver.bindings:
        raise ValueError('unbound receipt root_id')
    graph = GraphValidator(resolver, raw_provenance=raw_provenance)
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
    parser.add_argument('--original-raw-roots', type=Path, help='Independently admitted absolute JSON origin mapping (not receipt-derived)')
    parser.add_argument('--raw-provenance', type=Path, help='Explicit JSON array of envelope Refs collected from admissions')
    parser.add_argument('--hash-dir', type=Path)
    args = parser.parse_args(argv)
    try:
        if args.hash_dir:
            result = hash_dir(args.hash_dir)
        else:
            if not args.receipt or not args.roots or not args.root_id or not args.allowed_root_id:
                parser.error('receipt requires --roots, --root-id and card-admitted --allowed-root-id')
            resolver = Resolver(loads(args.roots.read_bytes()), allowed_root_ids=args.allowed_root_id)
            if args.original_raw_roots:
                if not args.original_raw_roots.is_absolute() or 'raw:campaign' not in args.allowed_root_id:
                    raise ValueError('original raw roots require absolute JSON and admitted raw:campaign')
                resolver.original_raw_roots = loads(args.original_raw_roots.read_bytes())
            envelopes = loads(args.raw_provenance.read_bytes()) if args.raw_provenance else ()
            validate(loads(args.receipt.read_bytes()), resolver, root_id=args.root_id, raw_provenance=envelopes)
            result = dict(status='structurally_valid', scientific_acceptance=False)
        print(json.dumps(result, sort_keys=True, allow_nan=False))
        return 0
    except (ValueError, OSError, KeyError, TypeError) as error:
        print(str(error), file=sys.stderr)
        return 3


if __name__ == '__main__':
    raise SystemExit(main())
