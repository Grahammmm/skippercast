"""Closed synthetic BAG/raw provenance contracts (v2 + v3); no acquisition/science.

Producer bytes are never rewritten. Origins are independent lexical identities.
Canonical catalog rows, other derivations and supersession remain held.
"""
from datetime import datetime
import json
import re

from coast_refs import REF_KEYS, SHA, ROOT_ID, canonical, loads, native_ref, relative_parts
from coast_native import closed

ENVELOPE = 'coast-raw-provenance-v1'
ROW = 'coastal-prefetch-row-v1'
SNAPSHOT = 'coastal-prefetch-snapshot-v1'
VR = 'coastal-vr-refinement-receipt-v1'
HEADER = 'schema created_utc author_profile author_model card_id code_commit skill_commit'.split()
SELECTION = 'line row raw inventory_row metadata_sha256 originals derivation native_documents'.split()
INVENTORY = 'id title kind format url sha256 horizontal_crs vertical_datum'.split()
ROW_FIELDS = 'url final_url bytes sha256 etag last_modified fetched_at licence segments path review_required verification'.split()
NATIVE = {'coastal-native-job-v1', 'coastal-cached-observation-v1', 'private-mapping-input-v2', 'coastal-mapping-run-v1', VR}


def require(ok, message):
    if not ok:
        raise ValueError(message)


def text(value):
    return isinstance(value, str) and bool(value.strip())


def absolute(value):
    require(isinstance(value, str) and value.startswith('/') and value != '/', 'invalid original absolute origin/path')
    relative_parts(value[1:])
    require(not any(ord(c) == 127 for c in value), 'control in original origin/path')
    return value


def typed(value, *, root=None, suffix=None):
    closed(value, REF_KEYS, REF_KEYS)
    require(isinstance(value['root_id'], str) and ROOT_ID.fullmatch(value['root_id']), 'invalid provenance root')
    relative_parts(value['path'])
    require(isinstance(value['sha256'], str) and SHA.fullmatch(value['sha256']), 'invalid provenance SHA256')
    require(type(value['bytes']) is int and value['bytes'] >= 0, 'invalid provenance bytes')
    if root is not None:
        require(value['root_id'] == root, 'cross-root provenance edge')
    if suffix:
        require(value['path'].endswith(suffix), 'invalid provenance edge suffix')
    return canonical(value)


def inventory(row):
    closed(row, INVENTORY, INVENTORY)
    require(all(text(row[k]) and row[k] != 'unknown' for k in INVENTORY), 'held inventory value')
    require(row['kind'] == 'bathymetry' and row['format'] == 'bag' and SHA.fullmatch(row['sha256']), 'held inventory lane')


def parse_rows(raw, *, single=False):
    from skippercast.coastal.prefetch import SEGMENTS
    require(raw and raw.endswith(b'\n') and b'\r' not in raw, 'prefetch snapshot requires LF lines')
    lines = raw.splitlines(keepends=True)
    require(not single or len(lines) == 1, 'prefetch row must be one line')
    rows = []
    for line in lines:
        row = loads(line)
        closed(row, ROW_FIELDS, ROW_FIELDS)
        for key in ('url', 'final_url', 'licence'):
            require(text(row[key]), 'invalid prefetch ' + key)
        require(type(row['bytes']) is int and row['bytes'] >= 0, 'invalid prefetch bytes')
        require(isinstance(row['sha256'], str) and SHA.fullmatch(row['sha256']), 'invalid prefetch digest')
        require(all(row[k] is None or isinstance(row[k], str) for k in ('etag', 'last_modified')), 'invalid HTTP metadata')
        stamp = row['fetched_at']
        require(isinstance(stamp, str) and re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(\.[0-9]{6})?\+00:00', stamp), 'invalid prefetch timestamp')
        require(datetime.fromisoformat(stamp).isoformat() == stamp, 'noncanonical prefetch timestamp')
        segments = row['segments']
        require(isinstance(segments, list) and segments and all(isinstance(s, str) and s in SEGMENTS for s in segments), 'invalid prefetch segments')
        require(segments == sorted(set(segments), key=SEGMENTS.index), 'noncanonical prefetch segments')
        absolute(row['path'])
        require(row['review_required'] is True and row['verification'] in ('publisher-sha256', 'http-size-and-local-sha256'), 'invalid prefetch review/verification')
        require(line == (json.dumps(row, sort_keys=True) + '\n').encode(), 'non-producer prefetch line bytes')
        require(not rows or rows[-1]['url'] < row['url'], 'duplicate/unsorted prefetch URL')
        rows.append(row)
    return rows


def occurrences(doc):
    """Only audited inline lineage slots; never recursive key-name inference."""
    name = doc.get('schema')
    result = []
    if name in ('coastal-native-job-v1', 'private-mapping-input-v2', VR):
        result.append((doc.get('source_row'), doc.get('metadata_sha256'), doc['source']))
    if name in ('coastal-cached-observation-v1', 'private-mapping-input-v2'):
        facts = doc['facts' if name == 'coastal-cached-observation-v1' else 'native_facts']
        lineage = facts.get('source_lineage', {})
        closed(lineage, ('source_row', 'metadata_sha256'))
        result.append((lineage.get('source_row'), lineage.get('metadata_sha256'), facts['source']))
    if name == 'coastal-mapping-run-v1':
        require(doc['mapping_input'].get('schema') == 'private-mapping-input-v2', 'unsupported inline mapping input')
        result.extend(occurrences(doc['mapping_input']))
    return result


def binding(doc, selection, root, outputs):
    result = []
    for row, metadata, source in occurrences(doc):
        require(row == selection['inventory_row'] and metadata == selection['metadata_sha256'], 'native inventory/metadata identity mismatch')
        bound = native_ref(source, root)
        # Originals and emitted outputs are different identity classes; never
        # compare an inventory BAG digest to the immediate GTiff digest.
        require(bound in selection['originals'] or bound in outputs, 'native source lacks original/derivation binding')
        result.append(bound)
    require(result and all(r == result[0] for r in result), 'inconsistent native source occurrences')
    return (selection['inventory_row'], selection['metadata_sha256'], result[0])


def vr_check(doc):
    closed(doc, 'schema producer source source_row metadata_sha256 survey_id bag placement outputs supergrid_table convention implementation libs not_for_navigation publication_prohibited limitations'.split(),
           'schema producer source source_row metadata_sha256 survey_id bag placement outputs supergrid_table convention implementation libs not_for_navigation publication_prohibited limitations'.split())
    require(doc['producer'] == 'coastal.handoff.vr_refinements' and doc['not_for_navigation'] is True and doc['publication_prohibited'] is True, 'invalid VR producer/prohibitions')
    inventory(doc['source_row'])
    require(isinstance(doc['metadata_sha256'], str) and SHA.fullmatch(doc['metadata_sha256']), 'invalid VR metadata identity')
    nested = {
        'bag': 'overview_shape overview_resolution_m overview_bounds horizontal_crs vertical_datum vertical_wkt uncertainty_type nodata active_supergrids refinement_records active_refinement_records trailing_padding_records valid_refinement_cells resolution_classes',
        'placement': 'policy lattice_tolerance_m interpolation resampling value_change overlap science_ruling_required max_abs_displacement_m',
        'convention': 'geolocation gdal_probe_supergrids refinement_rows elevation',
    }
    for key, fields in nested.items():
        closed(doc[key], fields.split(), fields.split())
    canonical(doc)  # rejects NaN/infinity, including direct Python API callers
    require(text(doc['survey_id']), 'invalid VR survey identity')
    def number(value):
        return type(value) in (int, float)
    def vector(value, size, predicate=number):
        return isinstance(value, list) and len(value) == size and all(predicate(v) for v in value)
    def count(value):
        return type(value) is int and value >= 0
    bag = doc['bag']
    require(vector(bag['overview_shape'], 2, count) and vector(bag['overview_resolution_m'], 2)
            and vector(bag['overview_bounds'], 4) and number(bag['nodata']), 'invalid VR overview')
    require(all(text(bag[k]) for k in ('horizontal_crs', 'vertical_datum', 'vertical_wkt', 'uncertainty_type')), 'invalid VR BAG metadata')
    require(all(count(bag[k]) for k in ('active_supergrids', 'refinement_records', 'active_refinement_records', 'trailing_padding_records', 'valid_refinement_cells')), 'invalid VR counts')
    require(isinstance(bag['resolution_classes'], list) and all(vector(v, 2) for v in bag['resolution_classes']), 'invalid VR resolution classes')
    placement = doc['placement']
    require(placement['policy'] in ('exact_lattice', 'nearest_cell') and
            all(placement[k] == 'none' for k in ('interpolation', 'resampling', 'value_change')) and
            placement['overlap'] == 'refused' and type(placement['science_ruling_required']) is bool and
            number(placement['lattice_tolerance_m']) and number(placement['max_abs_displacement_m']), 'invalid VR placement')
    convention = doc['convention']
    require(all(text(convention[k]) for k in ('geolocation', 'refinement_rows', 'elevation')) and
            isinstance(convention['gdal_probe_supergrids'], list) and
            all(vector(v, 2, count) for v in convention['gdal_probe_supergrids']), 'invalid VR conventions')
    closed(doc['implementation'], ('vr_refinements.py', 'common.py', 'bottom_targets.py'), ('vr_refinements.py', 'common.py', 'bottom_targets.py'))
    require(all(isinstance(v, str) and SHA.fullmatch(v) for v in doc['implementation'].values()), 'invalid VR implementation')
    closed(doc['libs'], ('numpy', 'rasterio', 'h5py', 'pyproj', 'gdal'), ('numpy', 'rasterio', 'h5py', 'pyproj', 'gdal'))
    require(all(text(v) for v in doc['libs'].values()), 'invalid VR library versions')
    require(isinstance(doc['outputs'], list) and doc['outputs'], 'missing VR outputs')
    fields = 'id artifact resolution_m lattice_anchor transform shape supergrids refinement_cells valid_cells max_abs_displacement_m values_sha256'.split()
    ids = []
    for output in doc['outputs']:
        closed(output, fields, fields)
        require(text(output['id']) and output['id'] not in ids, 'duplicate VR output')
        ids.append(output['id'])
        require(all(vector(output[k], size) for k, size in (('resolution_m', 2), ('lattice_anchor', 2), ('transform', 6), ('max_abs_displacement_m', 2))) and
                vector(output['shape'], 2, count) and all(count(output[k]) for k in ('supergrids', 'refinement_cells', 'valid_cells')) and
                isinstance(output['values_sha256'], str) and SHA.fullmatch(output['values_sha256']), 'invalid VR output metadata')
    require(isinstance(doc['limitations'], list) and all(isinstance(v, str) for v in doc['limitations']), 'invalid VR limitations')


class Provenance:
    def __init__(self, graph):
        self.graph = graph
        self.envelopes = {}
        self.native = {}
        self.preflighting = True
        self.pending = {}
        self.plan_registry = {}
        self.raw_registry = {}

    def preflight(self, refs):
        graph = self.graph
        require(isinstance(refs, (list, tuple)), 'raw_provenance must be an explicit finite sequence')
        distinct = {}
        for ref in refs:
            key = typed(ref, suffix='.json')
            require(ref['root_id'].startswith('queue:'), 'envelope requires queue root')
            distinct[key] = ref
        # Individual validation can temporarily bind its own native closure, but
        # no other envelope may repair it. Public registration occurs only after
        # all individual preflights and symmetric conflict checks succeed.
        for key, ref in distinct.items():
            self.pending = {}
            # No earlier envelope's traversal may repair this closure.
            graph.verified.clear()
            graph.reference(ref, contract=ENVELOPE)
        self.pending = {}
        self.preflighting = False

    @staticmethod
    def register(registry, key, value, label):
        require(key not in registry or registry[key] == value, 'conflicting ' + label)
        registry[key] = value

    def origins(self):
        resolver = self.graph.resolver
        origins = getattr(resolver, 'original_raw_roots', {})
        require(isinstance(origins, dict) and set(origins) == {'raw:campaign'}, 'missing/extra original raw root binding')
        origin = absolute(origins['raw:campaign'])
        others = getattr(resolver, 'original_queue_roots', resolver.bindings)
        for root, path in others.items():
            if root.startswith(('queue:', 'repo:')):
                other = absolute(str(path))
                require(not (origin == other or origin.startswith(other + '/') or other.startswith(origin + '/')), 'overlapping original origins')
        return origin

    def envelope(self, doc, ref):
        from skippercast.coastal.coordinator import catalog_bridge as bridge
        graph = self.graph
        root = ref['root_id']
        closed(doc, HEADER + ['source_id', 'plan', 'snapshot', 'selections'], HEADER + ['source_id', 'plan', 'snapshot', 'selections'])
        # Reuse the exact common-header schema, without introducing native fields.
        header = {k: doc[k] for k in HEADER}
        require(text(doc['source_id']), 'invalid envelope source_id')
        graph.header(header)
        typed(doc['plan'], root=root, suffix='.json')
        typed(doc['snapshot'], root=root, suffix='.jsonl')
        plan = graph.reference(doc['plan'], contract=bridge.PLAN)
        matching = [s for s in plan['selections'] if s.get('source_id') == doc['source_id']]
        require(len(matching) == 1, 'plan source_id absent/duplicated')
        chosen = matching[0]
        rows = graph.reference(doc['snapshot'], contract=SNAPSHOT)
        snapshot_lines = graph.resolver.read(doc['snapshot']).splitlines(keepends=True)
        origin = self.origins()
        require(isinstance(doc['selections'], list) and doc['selections'], 'missing provenance selections')
        previous = 0
        row_keys, raw_paths = set(), set()
        bindings = []
        for selection in doc['selections']:
            closed(selection, SELECTION, SELECTION)
            line = selection['line']
            require(type(line) is int and previous < line <= len(rows), 'duplicate/invalid selected line')
            previous = line
            row_key = typed(selection['row'], root=root, suffix='.jsonl')
            raw_key = typed(selection['raw'], root='raw:campaign')
            require(row_key not in row_keys and selection['raw']['path'] not in raw_paths, 'duplicate selected row/raw')
            row_keys.add(row_key)
            raw_paths.add(selection['raw']['path'])
            row = graph.reference(selection['row'], contract=ROW)[0]
            require(graph.resolver.read(selection['row']) == snapshot_lines[line - 1], 'selected row bytes differ from snapshot line')
            raw = selection['raw']
            require(row['path'] == origin + '/' + raw['path'] and all(row[k] == raw[k] for k in ('sha256', 'bytes')), 'selected raw origin/identity mismatch')
            inventory(selection['inventory_row'])
            inv = selection['inventory_row']
            require(inv == chosen.get('source_row') and inv['url'] == row['url'] and inv['sha256'] == raw['sha256'], 'plan/inventory/raw identity mismatch')
            metadata = selection['metadata_sha256']
            require(isinstance(metadata, str) and SHA.fullmatch(metadata), 'invalid metadata SHA256')
            require('metadata_sha256' not in chosen or chosen['metadata_sha256'] == metadata, 'plan metadata identity mismatch')
            graph.resolver.read(raw, retain=False, reject_structured=True)
            graph.verified.add((raw_key, 'full_graph', 'raw-payload'))
            originals = selection['originals']
            require(isinstance(originals, list) and originals, 'missing originals')
            original_keys = []
            for original in originals:
                original_keys.append(typed(original, root=root))
                require(all(original[k] == raw[k] for k in ('sha256', 'bytes')), 'original BAG/raw mismatch')
                graph.resolver.read(original, retain=False, reject_structured=True)
                graph.verified.add((canonical(original), 'full_graph', 'native-raster-v1'))
            require(len(set(original_keys)) == len(original_keys), 'duplicate original Ref')
            outputs = []
            derivation = selection['derivation']
            if derivation is not None:
                typed(derivation, root=root)
                vr = loads(graph.resolver.read(derivation))
                require(vr.get('schema') == VR, 'unsupported derivation contract')
                vr_check(vr)
                require(native_ref(vr['source'], root) in originals, 'VR source is not original BAG')
                outputs = [native_ref(o['artifact'], root) for o in vr['outputs']]
                value = binding(vr, selection, root, [])
                self.pending[canonical(derivation)] = value
                bindings.append((canonical(derivation), value))
                graph.reference(derivation, contract=VR)
            require(native_ref(chosen['source'], root) in originals + outputs, 'plan source lacks original/derivation binding')
            documents = selection['native_documents']
            require(isinstance(documents, list), 'native_documents must be array')
            keys = []
            for document in documents:
                key = typed(document, root=root)
                keys.append(key)
                value_doc = loads(graph.resolver.read(document))
                require(value_doc.get('schema') in NATIVE, 'unsupported provenance native document')
                value = binding(value_doc, selection, root, outputs)
                self.pending[key] = value
                bindings.append((key, value))
            require(len(set(keys)) == len(keys), 'duplicate native document Ref')
            # All entries are provisionally bound before traversal so nested native
            # documents work in either order. Unlisted nested lineage still refuses.
            for document in documents:
                graph.reference(document, contract=loads(graph.resolver.read(document))['schema'])
            self.register(self.raw_registry, raw_key, (inv, metadata, frozenset(original_keys)), 'raw identity')
        self.register(self.plan_registry, (canonical(doc['plan']), doc['source_id']), canonical(ref), 'plan selection envelopes')
        for key, value in bindings:
            self.register(self.native, key, value, 'native identity')
        self.envelopes[canonical(ref)] = doc

    def lineage(self, doc, ref, root):
        entries = occurrences(doc)
        if not any(row is not None for row, _, _ in entries):
            return False
        require(ref is not None, 'held: lineage requires registered native document Ref')
        key = canonical(ref)
        registry = self.pending if self.preflighting else self.native
        require(key in registry, 'held: unregistered native lineage')
        expected_row, expected_metadata, expected_source = registry[key]
        for row, metadata, source in entries:
            require(row == expected_row and metadata == expected_metadata and native_ref(source, root) == expected_source, 'registered native lineage mismatch')
        return True

    def admission(self, doc):
        root = 'queue:' + doc['campaign_segment_id']
        for source in doc['sources']:
            refs = source['raw_provenance']
            for ref in refs:
                typed(ref)
                if ref['root_id'] == 'raw:campaign':
                    continue
                typed(ref, root=root, suffix='.json')
                key = canonical(ref)
                require(key in self.envelopes, 'unregistered admission provenance envelope')
                env = self.envelopes[key]
                require(env['source_id'] == source['source_id'] and env['plan'] == doc['plan_file'], 'admission envelope source/plan mismatch')
                require(all(s['raw'] in refs for s in env['selections']), 'selected raw absent from admission source')
