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
from coast_refs import Resolver, REF_KEYS, canonical, loads, native_ref, object_digest
from coast_sample import sample, window_dir, window_key
import coast_receipt_versions as versions

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
    'coastal-native-job-v1': {'source', 'review', 'source_row', 'rights.evidence.*'},
    'coastal-cached-observation-v1': {'source', 'facts.source', 'facts.source_auxiliary.*'},
    'coastal-stage-result-v1': {'artifacts.*', 'next_job.input_manifest'},
    'private-mapping-input-v2': {'source', 'review', 'source_row', 'valid_support', 'rights.evidence.*', 'native_facts.source',
                                 'native_facts.source_auxiliary.*', 'native_facts.rights.evidence.*'},
    'coastal-mapping-run-v1': {'source', 'outputs.*'},
    'coastal-terrain-summary-v1': set(),
    # Leaf producer contracts reached from plan/job/mapping-input slots.
    'coastal-private-input-review-v2': set(),
    'vertical-v1': set(),
    'vertical-observation-v1': set(),
}
VERTICAL_OBSERVATION_FIELDS = {'schema', 'source_sha256', 'header', 'header_sha256', 'facts', 'conflicts', 'sign_hint',
                               'units', 'datum', 'scale', 'offset', 'scale_offset_applied'}
REVIEW_FIELDS = {'schema', 'independent', 'reviewer_id', 'facts_digest', 'checked_at', 'valid_until', 'decision', 'holds_added'}
# Rights evidence slots carry a producer-declared contract. Only these leaf
# contracts are understood; each is validated strictly in rights_evidence().
RIGHTS_SLOTS = {'selections.*.rights.evidence.*', 'rights.evidence.*', 'native_facts.rights.evidence.*'}
RIGHTS_CONTRACTS = {'coastal-rights-evidence-v1', 'synthetic-fixture-evidence-v1'}
# private-mapping-input-v2 exact producer shape (handoff/mapping_input.produce).
MAPPING_INPUT_FIELDS = {'schema', 'producer', 'segment_id', 'source', 'source_row', 'metadata_sha256', 'segment', 'window',
                        'declared_vertical', 'rights', 'synthetic', 'native_facts', 'valid_support', 'facts_digest',
                        'machine_holds', 'review', 'publication_prohibited'}
NATIVE_FACT_FIELDS = {'header', 'observed_vertical', 'vertical', 'source', 'source_auxiliary', 'source_lineage',
                      'raw_valid_values_sha256', 'valid_count', 'valid_fraction', 'support', 'depth_values_sha256',
                      'libs', 'implementation', 'segment', 'rights', 'synthetic'}
OPTIONAL_NATIVE_FACT_FIELDS = {'deep_lane_support'}
# mapping_input.bind_segment() support record embedded at native_facts.segment.
BOUND_SEGMENT_FIELDS = {'schema', 'segment_id', 'region', 'crs', 'bbox', 'boundary_policy', 'halo_m',
                        'intersection_area_m2', 'outside_support_area_m2'}
OBSERVATION_FIELDS = {'expected_packet', 'observed_packet', 'problems', 'observations'}
IDENTITY_ONLY_FIELDS = {'identity_provenance', 'run_author_provenance', 'posted_hashes', 'routing', 'thresholds', 'prompts'}
WORKFLOW_EDGES = {
    'context': 'coast-review-context-v1', 'admission': 'coast-admission-v1',
    'enqueue': versions.ENQUEUE_V2, 'run': versions.RUN_V2,
    'legacy_enqueue': versions.ENQUEUE_V1, 'legacy_run': versions.RUN_V1,
    'tier1': 'coast-tier1-screen-v1', 'open_report': 'coast-open-report-v1',
    'packet': 'coast-review-packet-v1', 'verdict_file': 'coast-review-verdict-v1',
    'routing': 'coast-review-routing-v1', 'manifest': 'coast-archive-manifest-v1',
}
# Native PC9 records keep their v1 IDs and are validated by legacy(), never by
# the generic shared edge walk (their nested keys have native meanings).
LEGACY = {versions.ENQUEUE_V1, versions.RUN_V1, versions.INTENT_V1}
CONTINUABLE = {'deadline', 'max_ticks', 'not_claimable'}


def validate_schema(value):
    if not isinstance(value, dict) or not isinstance(value.get('schema'), str):
        raise ValueError('workflow receipt needs a schema')
    name = value['schema']
    if not name.startswith('coast-') or not name.endswith(('-v1', '-v2')) or '/' in name or '\\' in name:
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
    if name == versions.RUN_V2:
        keys = [w['window_key'] for w in value['windows']]
        partition = [k for group in value['partition'].values() for k in group]
        if len(set(keys)) != len(keys) or sorted(keys) != sorted(partition):
            raise ValueError('run partition does not cover each window exactly once')
        for w in value['windows']:
            if w['window_key'] not in value['partition'][w['state']]:
                raise ValueError('window state/partition mismatch')
        if value['ticks_used'] > value['max_ticks']:
            raise ValueError('ticks_used exceeds max_ticks')
        # Exactly one per-window cells record, in window order; no aggregate.
        cells = value['window_cells']
        if ([c['window_key'] for c in cells] != keys or [c['window_index'] for c in cells] != list(range(len(keys)))
                or [c['state'] for c in cells] != [w['state'] for w in value['windows']]):
            raise ValueError('window_cells must hold one record per window in window order')
        for c in cells:
            measured = c['producer'] is not None
            if measured != (c['producer_contract'] is not None) or (measured and c['state'] != 'map_done'):
                raise ValueError('window_cells producer binding inconsistent')
            if not measured and (any(c[k] is not None for k in versions.STATS + ('native_valid_count',)) or not c['unknown']):
                raise ValueError('unmeasured window must be explicitly unknown, never zero-filled')
        evidence = value['store_status_evidence']
        if evidence['source'] != value['legacy_run']:
            raise ValueError('legacy embedded status must bind to the original run receipt')
        if (value['sequence'] == 0) != (value['continuation_of'] is None):
            raise ValueError('zero-based run sequence/continuation mismatch')
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
        if name in LEGACY:
            validate_schema(doc)
            try:
                self.legacy(doc, root_id=root_id)
            except (KeyError, TypeError, IndexError) as error:
                raise ValueError('malformed legacy PC9 receipt: ' + name) from error
        elif name.startswith('coast-'):
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
            try:
                self.check_producer(doc)
            except (KeyError, TypeError, IndexError) as error:
                raise ValueError('malformed native producer: ' + name) from error
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
                    if set(value) - {'path', 'sha256', 'bytes', 'contract', 'kind'}:
                        raise ValueError('unresolved-reference: unknown native ref field ' + slot)
                    if pattern in RIGHTS_SLOTS:
                        self.rights_evidence(value, doc, path, root_id=root_id)
                    else:
                        self.reference(native_ref(value, root_id))
                elif 'path' in value or 'root_id' in value:
                    raise ValueError('unresolved-reference: unknown native ref slot ' + slot)
                elif contract == 'private-mapping-input-v2' and slot == 'native_facts.segment':
                    self.bound_segment(value, doc)
                elif value is not doc and 'schema' in value and not (contract.startswith('coastal-catalog-acquire-bridge-') and slot == 'catalog'):
                    self.document(value, root_id=root_id)
                else:
                    for key, child in value.items():
                        if key.endswith(('_path', '_ref', '_file')):
                            raise ValueError('unresolved-reference: unknown native path field ' + '.'.join(path + [key]))
                        visit(child, path + [key])
            elif isinstance(value, list):
                for i, child in enumerate(value):
                    visit(child, path + [str(i)])
        visit(doc, [])

    def rights_evidence(self, value, doc, path, *, root_id):
        """Producer-declared rights evidence leaf (authenticated.py rules).

        Structural PC9 records may carry no evidence (review-required, never
        execution-authorized); any evidence that IS present must be a declared,
        hash-bound, source-specific leaf. Validation never grants qualification.
        """
        contract = value.get('contract')
        if contract not in RIGHTS_CONTRACTS:
            raise ValueError('unresolved-reference: unknown rights evidence contract at ' + '.'.join(path))
        owner = doc
        for part in path[:path.index('rights')]:
            owner = owner[int(part)] if isinstance(owner, list) else owner[part]
        rights = owner['rights']
        if not isinstance(rights, dict) or set(rights) - {'private_use', 'evidence'} or rights.get('private_use') is not True:
            raise ValueError('rights evidence requires declared private use')
        source = owner.get('source')
        synthetic = owner.get('synthetic', doc.get('synthetic'))
        evidence = loads(self.resolver.read(native_ref(value, root_id)))
        if contract == 'synthetic-fixture-evidence-v1':
            # Synthetic stand-in only: never valid for a non-synthetic producer record.
            if evidence != {'synthetic': True} or synthetic is not True:
                raise ValueError('synthetic rights evidence outside a synthetic producer record')
            return
        from datetime import datetime
        def epoch(stamp):
            if not isinstance(stamp, str) or not stamp.endswith('Z'):
                raise ValueError('rights evidence timestamps must be UTC')
            return datetime.fromisoformat(stamp[:-1] + '+00:00').timestamp()
        if (not isinstance(evidence, dict) or evidence.get('schema') != contract or evidence.get('independent') is not True
                or not isinstance(evidence.get('reviewer_id'), str) or not evidence['reviewer_id'].strip()
                or evidence.get('private_use') is not True
                or evidence.get('decision') != 'accepted_private_processing_conditional_on_exact_expected_source_identity'
                or evidence.get('accepted_source_rights_for_declared_private_purpose') is not True
                or evidence.get('holds_added') != [] or not isinstance(source, dict)
                or evidence.get('source_sha256') != source.get('sha256') or evidence.get('source_bytes') != source.get('bytes')
                or evidence.get('synthetic', False) is not (synthetic is True)):
            raise ValueError('independent source-specific rights binding invalid')
        if not epoch(evidence.get('checked_at')) < epoch(evidence.get('valid_until')):
            raise ValueError('rights evidence validity window invalid')

    def bound_segment(self, value, doc):
        """Exact mapping_input.bind_segment() support record (no lattice bbox_crs84)."""
        import math
        if not isinstance(value, dict) or set(value) != BOUND_SEGMENT_FIELDS:
            raise ValueError('unknown producer field: native_facts.segment')
        x0, y0 = (int(p) for p in value['segment_id'].split(':')[2:4])
        if (value['schema'] != 'coastal-segment-v1' or value['segment_id'] != doc['segment_id'] or value['crs'] != 'EPSG:3310'
                or value['bbox'] != [x0, y0, x0 + 5000, y0 + 5000] or not isinstance(value['region'], str) or not value['region']
                or value['boundary_policy'] != 'all_valid_native_support_contained' or value['halo_m'] != 0):
            raise ValueError('bound native segment identity mismatch')
        inside, outside = value['intersection_area_m2'], value['outside_support_area_m2']
        if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or v < 0 for v in (inside, outside)):
            raise ValueError('bound native segment areas invalid')
        holds = doc['machine_holds']
        if (inside <= 0) != ('native_support_disjoint_from_segment' in holds) or (outside > 1e-6) != ('native_support_outside_segment' in holds):
            raise ValueError('bound native segment holds mismatch')

    def check_producer(self, doc):
        """Bounded native metadata adapters; no fetch, Store, or execution calls."""
        from skippercast.coastal.coordinator import catalog_bridge as bridge
        from skippercast.coastal.coordinator.segments import segment
        name = doc['schema']
        canonical(doc)
        fields = {
            'coastal-segment-v1': {'schema', 'segment_id', 'region', 'crs', 'bbox', 'bbox_crs84', 'synthetic'},
            bridge.CATALOG: {'schema', 'region', 'bbox', 'source_revision', 'policy_revision', 'method_revision', 'plan_sha256', 'manifest_sha256', 'checked_from', 'checked_until', 'manifest_status', 'bounded_plan_finished', 'discovery_complete', 'unattempted_queries', 'lead_source_ids', 'usable_source_ids', 'candidates', 'mapping_accepted', 'execution_authorized', 'review_required', 'coordinator_boundary', 'catalog_id'},
            bridge.PLAN: {'schema', 'catalog_id', 'catalog_sha256', 'segment', 'synthetic', 'max_total_bytes', 'budget', 'selections'},
            bridge.DRY_RUN: {'schema', 'plan_sha256', 'catalog', 'segment_id', 'decisions', 'selected_source_ids', 'held_source_ids', 'caps', 'network_requests', 'source_opens', 'source_bytes_read', 'review_required', 'mapping_accepted', 'execution_authorized', 'note', 'would_enqueue'},
        }
        fields[bridge.RECEIPT] = (fields[bridge.DRY_RUN] - {'would_enqueue'}) | {'jobs', 'budget', 'segment'}
        if name in fields and set(doc) - fields[name]:
            raise ValueError('unknown producer field: ' + name)
        if name == 'coastal-private-input-review-v2':
            # handoff/common.review_holds() binding rules, checked structurally.
            import re
            from datetime import datetime
            def epoch(stamp):
                if not isinstance(stamp, str) or not stamp.endswith('Z'):
                    raise ValueError('review timestamps must be UTC')
                return datetime.fromisoformat(stamp[:-1] + '+00:00').timestamp()
            if (set(doc) != REVIEW_FIELDS or doc['independent'] is not True or not isinstance(doc['reviewer_id'], str)
                    or not doc['reviewer_id'].strip() or doc['reviewer_id'].startswith('coastal.')
                    or not isinstance(doc['facts_digest'], str) or not re.fullmatch('[0-9a-f]{64}', doc['facts_digest'])
                    or doc['decision'] not in ('qualified_private_terrain', 'accept')
                    or not isinstance(doc['holds_added'], list) or any(not isinstance(h, str) or not h for h in doc['holds_added'])
                    or not epoch(doc['checked_at']) < epoch(doc['valid_until'])):
                raise ValueError('independent input review binding invalid')
        if name == 'vertical-v1':
            from skippercast.coastal import vertical
            if not isinstance(vertical.validate(doc), list):
                raise ValueError('vertical block invalid')
        if name == 'vertical-observation-v1':
            # vertical.from_raster() output: exact fields, header digest recomputed.
            from skippercast.coastal import vertical
            if set(doc) != VERTICAL_OBSERVATION_FIELDS or doc['header_sha256'] != vertical.digest(doc['header']):
                raise ValueError('vertical observation binding invalid')
        if name == 'private-mapping-input-v2':
            from skippercast.coastal.coordinator.stages import digest
            facts = doc['native_facts']
            if set(doc) != MAPPING_INPUT_FIELDS:
                raise ValueError('unknown producer field: ' + name)
            if not isinstance(facts, dict) or not NATIVE_FACT_FIELDS <= set(facts) or set(facts) - NATIVE_FACT_FIELDS - OPTIONAL_NATIVE_FACT_FIELDS:
                raise ValueError('unknown producer field: ' + name + ' native_facts')
            # produce(): facts.update(rights=rights, synthetic=...) and facts_digest=digest(facts).
            if (facts['rights'] != doc['rights'] or facts['synthetic'] != doc['synthetic'] or facts['source'] != doc['source']
                    or doc['facts_digest'] != digest(facts) or doc['publication_prohibited'] is not True):
                raise ValueError('mapping input native facts binding mismatch')
        if name == 'coastal-segment-v1':
            from pyproj import Transformer
            bbox = doc['bbox']
            expected = segment(bbox[0], bbox[1], region=doc['region'])
            if any(doc.get(k) != v for k, v in expected.items()):
                raise ValueError('lattice ID/projected bbox mismatch')
            inverse = Transformer.from_crs('EPSG:3310', 'OGC:CRS84', always_xy=True)
            if not inverse_bounds_equal(doc.get('bbox_crs84'), list(inverse.transform_bounds(*bbox, densify_pts=41))):
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

    def legacy(self, doc, *, root_id):
        """Native PC9v1 receipts: exact schema plus producer bindings, original queue only."""
        from skippercast.coastal.coordinator import catalog_bridge as bridge
        name = doc['schema']
        if not root_id.startswith('queue:'):
            raise ValueError('legacy PC9 receipts require the original queue root namespace')
        def edge(ref, contract=None):
            if ref['root_id'] != root_id:
                raise ValueError('legacy PC9 reference leaves its queue namespace')
            # Producer contract labels are enforced on JSON documents; binary
            # artifacts (GeoTIFF support/terrain) are bound by exact SHA/bytes.
            label = contract or (ref.get('contract') if ref['path'].endswith('.json') else None)
            return self.reference(versions.typed(ref), contract=label)
        admission = edge(doc['admission'], 'coast-admission-v1')
        bridge_doc = edge(doc['bridge'], bridge.RECEIPT)
        if any(doc[k] != admission[k] for k in ('campaign_segment_id', 'coordinator_segment_id', 'plan_id', 'plan_sha256')):
            raise ValueError('legacy receipt identity differs from admission')
        if name == versions.INTENT_V1:
            return
        if name == versions.ENQUEUE_V1:
            intent = edge(doc['intent'], versions.INTENT_V1)
            if (intent['bridge'] != doc['bridge'] or intent['admission'] != doc['admission']
                    or intent['code_sha'] != doc['code_sha'] or intent['deps_sha'] != doc['deps_sha']):
                raise ValueError('legacy intent binding mismatch')
            jobs = doc['jobs']
            if (len(jobs) != len(admission['windows']) or len(jobs) != len(bridge_doc['jobs'])
                    or len({j['root_job_id'] for j in jobs}) != len(jobs)):
                raise ValueError('legacy enqueue population mismatch')
            for entry, window, job in zip(jobs, admission['windows'], bridge_doc['jobs']):
                if (entry['window_key'] != window['window_key'] or entry['source_id'] != job['source_id']
                        or entry['input_manifest'] != dict(job['input_manifest'], root_id=root_id)):
                    raise ValueError('legacy enqueue root manifest mismatch')
                edge(entry['input_manifest'])
            return
        enqueue = edge(doc['enqueue'], versions.ENQUEUE_V1)
        if doc['admission'] != enqueue['admission'] or doc['bridge'] != enqueue['bridge'] or (doc['code_sha'], doc['deps_sha']) != (enqueue['code_sha'], enqueue['deps_sha']):
            raise ValueError('legacy run/enqueue binding mismatch')
        if doc['enqueued_job_ids'] != [j['root_job_id'] for j in enqueue['jobs']]:
            raise ValueError('legacy run enqueued job population mismatch')
        if [(w['window_key'], w['source_id'], w['root_job_id']) for w in doc['windows']] != [
                (j['window_key'], j['source_id'], j['root_job_id']) for j in enqueue['jobs']]:
            raise ValueError('legacy run window population mismatch')
        counts = {state: sum(w['state'] == state for w in doc['windows']) for state in versions.STATES}
        if any(doc['counts'][k] != v for k, v in counts.items()) or doc['counts']['windows'] != len(doc['windows']):
            raise ValueError('legacy run counts mismatch')
        if doc['bridge_caps'] != bridge_doc['caps'] or doc['ticks_used'] > doc['max_ticks']:
            raise ValueError('legacy run caps/ticks mismatch')
        if doc['continuation_of'] is None:
            if doc['sequence'] != 0:
                raise ValueError('legacy run sequence is zero-based')
        else:
            previous = edge(doc['continuation_of'], versions.RUN_V1)
            if (previous['enqueue'] != doc['enqueue'] or previous['stop_reason'] not in CONTINUABLE
                    or doc['sequence'] != previous['sequence'] + 1):
                raise ValueError('legacy continuation not authorized')
        for window in doc['windows']:
            for info in window['stages'].values():
                if info['state'] == 'missing':
                    continue
                edge(info['input_manifest'])
                if info['result_ref'] is not None:
                    edge(info['result_ref'], 'coastal-stage-result-v1')
                for product in info['products'].values():
                    edge(product)
        # store_status is inherited embedded evidence: schema-checked only, never
        # treated as an independently produced or store-consistent snapshot.

    def run_v2(self, doc):
        legacy = self.reference(doc['legacy_run'], contract=versions.RUN_V1)
        enqueue = self.reference(doc['enqueue'], contract=versions.ENQUEUE_V2)
        if versions.typed(legacy['enqueue']) != enqueue['legacy_enqueue']:
            raise ValueError('v2 run enqueue differs from legacy run enqueue')
        previous_ref = doc['continuation_of']
        if previous_ref is not None:
            previous = self.reference(previous_ref, contract=versions.RUN_V2)
            if legacy['continuation_of'] is None or previous['legacy_run'] != versions.typed(legacy['continuation_of']):
                raise ValueError('v2 continuation differs from legacy continuation')
        if doc != versions.run_v2(legacy, doc['legacy_run'], doc['enqueue'], previous_ref):
            raise ValueError('v2 run differs from hash-bound adapter output')
        for cells in doc['window_cells']:
            if cells['producer'] is None:
                continue
            producer = self.reference(cells['producer'], contract=cells['producer_contract'])
            depth = producer['depth_m']
            def numeric(value):
                return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None
            if (producer['native_valid_count'] != cells['native_valid_count']
                    or any(cells[k] != numeric(depth.get(k)) for k in versions.STATS)):
                raise ValueError('window cells statistics differ from producer record')

    def crosscheck(self, doc, error_branch):
        name = doc['schema']
        if name == versions.ENQUEUE_V2:
            legacy = self.reference(doc['legacy_enqueue'], contract=versions.ENQUEUE_V1)
            if doc != versions.enqueue_v2(legacy, doc['legacy_enqueue']):
                raise ValueError('v2 enqueue differs from hash-bound adapter output')
        if name == versions.RUN_V2:
            self.run_v2(doc)
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
        # PC9 producer records may carry synthetic=True; bridge_run._context binds it
        # to plan.synthetic. Only that exact producer label is excluded from the
        # lattice comparison, and only when the plan agrees.
        lattice = {k: v for k, v in record.items() if k != 'bbox_crs84'}
        if 'synthetic' in record:
            if record['synthetic'] is not True or plan.get('synthetic') is not True:
                raise ValueError('synthetic segment record without synthetic plan')
            del lattice['synthetic']
        # Projected lattice fields remain exact. Only inverse projection is
        # subject to the measured, two-ULP libm portability bound.
        if not any({k:v for k,v in r.items() if k != 'bbox_crs84'} == lattice and
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
