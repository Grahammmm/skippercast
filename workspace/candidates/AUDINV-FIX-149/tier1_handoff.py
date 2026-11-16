"""Inert offline candidate. Explicit admitted JSON metadata only; no native IO/dispatch."""
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PACKAGE = Path(__file__).resolve().parent
BASES = json.loads((PACKAGE / 'BASES.json').read_text())
REF_PATH = 'skills/coast-campaign-shared/scripts/coast_refs.py'
raw = (ROOT / REF_PATH).read_bytes()
if hashlib.sha256(raw).hexdigest() != BASES['sources'][REF_PATH]:
    raise ValueError('reference implementation source drift')
spec = importlib.util.spec_from_file_location('audinv149_refs', ROOT / REF_PATH)
refs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(refs)
spec = importlib.util.spec_from_file_location('audinv149_bands', PACKAGE / 'depth_bands.py')
bands = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bands)


def _index(items):
    if not isinstance(items, list) or len(items) > 64:
        raise ValueError('bounded explicit metadata refs required')
    indexed = {}
    for ref in items:
        if not isinstance(ref, dict) or set(ref) != refs.REF_KEYS:
            raise ValueError('explicit typed Ref required')
        refs.relative_parts(ref['path'])
        if (not isinstance(ref['sha256'], str) or not refs.SHA.fullmatch(ref['sha256'])
                or type(ref['bytes']) is not int or not 0 <= ref['bytes'] <= 65536
                or not isinstance(ref['root_id'], str) or not refs.ROOT_ID.fullmatch(ref['root_id'])
                or not ref['path'].endswith('.json')):
            raise ValueError('bounded JSON metadata Ref required')
        key = (ref['root_id'], ref['path'])
        if key in indexed:
            raise ValueError('duplicate/conflicting metadata path')
        indexed[key] = ref
    return indexed


def handoff(receipt, posted_manifest, *, admitted_refs, bindings, admitted_samples=None):
    """Caller independently supplies admission, manifest, roots, and optional samples.

    Only admitted JSON leaves are read (never traverse a tree). Native sources are
    copied AS_RECORDED. Return a new review-required result; never write a receipt.
    """
    out = {'state': 'HELD', 'review': 'REVIEW_REQUIRED', 'integrity_holds': [],
           'input_receipt': deepcopy(receipt), 'acquire_count': None,
           'qualification_count': None, 'map_count': None, 'mask': None,
           'valid_cells_by_band': None, 'deepest_mapped_cell_m': None,
           'quality': 'unavailable', 'visual_certified': False,
           'native_sources': {'status': 'AS_RECORDED', 'refs': []}}
    for key in ('attempt', 'window_key', 'status', 'attempt_history'):
        out[key] = deepcopy(receipt.get(key)) if isinstance(receipt, dict) else None
    try:
        if not isinstance(receipt, dict):
            raise ValueError('receipt must be an object')
        out['native_sources']['refs'] = deepcopy(receipt.get('native_sources', []))
        admitted, posted = _index(admitted_refs), _index(posted_manifest)
        if admitted != posted:
            raise ValueError('posted path/hash/bytes tuples differ from admission')
        resolver = refs.Resolver(bindings, allowed_root_ids={k[0] for k in admitted})
        documents = [refs.loads(resolver.read(ref)) for ref in admitted.values()]
        if receipt not in documents:
            raise ValueError('receipt not bound to verified admitted metadata')
        if not receipt.get('attempt') or not receipt.get('window_key'):
            raise ValueError('missing attempt/window identity')
        stages = receipt.get('stages', {})
        if not isinstance(stages, dict):
            raise ValueError('stages must be an object')
        acquire = stages.get('acquire', {})
        if not isinstance(acquire, dict):
            raise ValueError('acquire must be an object')
        count = acquire.get('count')
        if count is not None and (type(count) is not int or count < 0):
            raise ValueError('invalid measured acquire count')
        out['acquire_count'] = count
        held = acquire.get('status') != 'PASS' or receipt.get('status') != 'COMPLETED'
        if held:
            if any(stages.get(s) not in (None, {}) for s in ('qualify', 'map')):
                raise ValueError('later stage claimed after terminal acquire/status HOLD')
            return out
        for stage, target in (('qualify', 'qualification_count'), ('map', 'map_count')):
            entry = stages.get(stage, {})
            if not isinstance(entry, dict):
                raise ValueError(f'{stage} must be an object')
            if entry.get('status') != 'PASS':
                if stage == 'qualify' and stages.get('map') not in (None, {}):
                    raise ValueError('map claimed after qualification HOLD')
                return out
            count = entry.get('count')
            if type(count) is not int or count < 0:
                raise ValueError('missing/invalid observed stage count')
            out[target] = count
        out['state'] = 'REVIEW_REQUIRED'
        if admitted_samples is not None:
            sample = deepcopy(admitted_samples)
            for key in ('attempt', 'window_key'):
                if sample.pop(key, None) != receipt[key]:
                    raise ValueError('stale sample identity')
            if sample.get('producer') != stages['map'].get('producer'):
                raise ValueError('sample producer mismatch')
            out.update(bands.depth_bands(**sample))
            if sum(out['valid_cells_by_band'].values()) != out['map_count']:
                raise ValueError('sample/map count mismatch')
    except (ValueError, TypeError, KeyError, OSError) as error:
        out.update(state='HELD', qualification_count=None, map_count=None, mask=None,
                   valid_cells_by_band=None, deepest_mapped_cell_m=None)
        out['integrity_holds'].append(str(error))
    return out
