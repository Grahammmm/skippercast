"""Seafloor error correction (EC0): the shared contract every EC tool imports. Stdlib only.
Provenance codes, thresholds, tolerance and shoal helpers, the acquisition/independence rule, receipt schemas
with `check_receipt`, and the GeoJSON property contract. Depths are elevation-up metres (water < 0). Nothing here
reads a raster, converts a datum or certifies navigation; a machine-valid receipt is review-required, not
acceptance. See docs/seafloor-ec.md.
"""
from collections import namedtuple
from pathlib import PurePath
from types import MappingProxyType
import math
import re

from .depth_contours import SHA256

EC_VERSION = '1.0'
CODES = MappingProxyType({
    'nodata': 0, 'measured': 10, 'measured-suspect-shoal': 11, 'filled-hole': 20, 'filled-pit': 21, 'verified': 30,
    'unresolved-hole': 40, 'unresolved-conflict': 41, 'unresolved-ring-range': 42, 'unresolved-datum-suspect': 43,
    'masked-sentinel': 50})
_NAME = {code: name for name, code in CODES.items()}
_CLASS = {0: 'nodata', 1: 'measured', 2: 'filled', 3: 'verified', 4: 'unresolved', 5: 'masked'}

def CLASS_OF(code):
    """Class of a provenance code by its tens digit; ValueError for a code not in CODES."""
    if isinstance(code, bool) or code not in _NAME: raise ValueError(f'unknown provenance code: {code!r}')
    return _CLASS[code // 10]

def REASON_OF(code):
    """The code name without its class prefix: 41 -> 'conflict', 20 -> 'hole', 10 -> 'measured', 0 -> 'nodata'."""
    return _NAME[code].removeprefix(CLASS_OF(code) + '-')

# Thresholds (DESIGN §5); THRESHOLDS bundles them read-only for the EC tools.
def hole_max_cells(cell_m): return min(9, int(64 // (cell_m * cell_m)))
def hole_ring_max_range_m(shallowest_m): return max(2.0, 0.10 * abs(shallowest_m))
def outlier_min_m(ring_median_m): return max(3.0, 0.20 * abs(ring_median_m))
OUTLIER_MAX_CELLS = 2
SENTINELS = (-9999.0, 9999.0, -999999.0, 1e6, 5000.0, 32767.0, -32767.0, 3.4028234663852886e38, -3.4028234663852886e38)
PLAUSIBLE_M = (-3000.0, 100.0)
FIXTURE_PATH = re.compile(r'(pytest-basetemp|/fixtures?/|/scratch/|synthetic|invented|generated-template|sample\.tif$)')
FIXTURE_MIN_PIXELS = 4096
FIXTURE_MAX_DISTINCT = 3
SIGN_POSITIVE_FRACTION = 0.99
DATUM_SUSPECT = MappingProxyType({'min_cells': 1000, 'max_mad_m': 0.5})
_T = ('hole_max_cells', 'hole_ring_max_range_m', 'outlier_min_m', 'OUTLIER_MAX_CELLS', 'SENTINELS', 'PLAUSIBLE_M',
      'FIXTURE_PATH', 'FIXTURE_MIN_PIXELS', 'FIXTURE_MAX_DISTINCT', 'SIGN_POSITIVE_FRACTION', 'DATUM_SUSPECT')
THRESHOLDS = namedtuple('Thresholds', _T)(*(globals()[name] for name in _T))

def tol_m(depth_m):
    """Agreement tolerance in metres (IHO S-44 Order 1a TVU, doubled). It compares; it never corrects."""
    return 2.0 * math.sqrt(0.5 ** 2 + (0.013 * abs(depth_m)) ** 2)

def shoal_pick(values):
    """The shallowest (largest elevation-up) value of a non-empty iterable."""
    values = list(values)
    if not values: raise ValueError('shoal_pick: no values')
    return max(values)

def no_deepening(before, after, treated):
    """Indices where a treated cell got deeper or an untreated cell changed at all; [] means PASS."""
    if len(before) != len(after): raise ValueError('no_deepening: before and after differ in length')
    treated = set(treated)
    if any(not 0 <= i < len(before) for i in treated): raise ValueError('no_deepening: treated index out of range')
    same = lambda b, a: a == b or (math.isnan(a) and math.isnan(b))  # noqa: E731
    return [i for i, (b, a) in enumerate(zip(before, after)) if ((a < b) if i in treated else not same(b, a))]

COMPILATION_ADAPTERS = frozenset({'bluetopo-geotiff-source-review', 'nbs-modeling-geotiff', 'gebco-grid-deep-fill',
                                  'gmrt-gridserver-deep-fill', 'ncei-footprint-discovery'})
BAG_ADAPTERS = frozenset({'bag', 'noaa-native-vr-bag'})

def acquisition_key(source_entry, file_name):
    """BAG: the survey id from the file name (the region_build.survey_id rule) or None; otherwise the catalog id."""
    if source_entry.get('adapter') in BAG_ADAPTERS:
        name = PurePath(file_name).name.removeprefix('BAG__').split('_')[0]
        return name if re.fullmatch(r'[A-Z]\d{5}', name) else None
    return source_entry.get('id')

def independent(a_entry, a_file, b_entry, b_file, duplicate=False):
    """(bool, reason): only different, known, non-compilation acquisitions that are not duplicates verify."""
    for entry in (a_entry, b_entry):
        if entry.get('adapter') in COMPILATION_ADAPTERS: return False, f"compilation:{entry['adapter']}"
    if duplicate: return False, 'duplicate'
    a_key, b_key = acquisition_key(a_entry, a_file), acquisition_key(b_entry, b_file)
    if a_key is None or b_key is None: return False, 'unknown-acquisition'
    return (False, f'same-acquisition:{a_key}') if a_key == b_key else (True, 'ok')

# Receipt schemas: required keys -> type word ('x?' may be null or absent), nested dict, or [item schema].
DISPOSITIONS = ('PASS', 'FIX', 'VERIFY', 'UNRESOLVED', 'REFUSED')
_OUTLIER = {'cells': 'int', 'bbox': 'bbox', 'ring_median_m': 'num', 'deviation_m': 'num'}
_HEAD = {'schema': 'str', 'ec_version': 'str', 'source_id': 'str'}
SCHEMAS = MappingProxyType({
    'ec-detect-v1': {**_HEAD, 'path_sha256': 'sha256', 'cell_m': 'num', 'crs': 'str', 'width': 'int', 'height': 'int',
                     'nodata': 'num?', 'counts': 'counts', 'pits': [_OUTLIER], 'spikes': [_OUTLIER],
                     'holes': [{'cells': 'int', 'bbox': 'bbox', 'ring_shallowest_m': 'num?', 'ring_range_m': 'num?',
                                'disposition': 'str'}],
                     'sentinel_cells': 'int', 'fixture': {'refused': 'bool', 'reasons': 'list'},
                     'sign': {'refused': 'bool', 'positive_fraction': 'num?', 'reason': 'str?'},
                     'duplicate_signature': 'sig', 'disposition': 'disposition'},
    'ec-apply-v1': {**_HEAD, 'detect_sha256': 'sha256', 'input_sha256': 'sha256', 'corrected_sha256': 'sha256',
                    'provenance_sha256': 'sha256', 'cell_m': 'num', 'counts': 'counts', 'duplicate_signature': 'sig',
                    'fixes': [{'kind': 'str', 'cells': 'int', 'bbox': 'bbox', 'before_min_m': 'num', 'after_m': 'num'}],
                    'deepened_cells': 'int', 'disposition': 'disposition'},
    'ec-verify-v1': {**_HEAD, 'apply_sha256': 'sha256', 'provenance_sha256': 'sha256', 'counts': 'counts',
                     'pairs': [{'second_source_id': 'str', 'second_file_sha256': 'sha256', 'independent': 'bool',
                                'reason': 'str', 'datums': 'datums', 'comparable': 'bool', 'jointly_valid_cells': 'int',
                                'mean_signed_diff_m': 'num?', 'mad_m': 'num?', 'verified_cells': 'int',
                                'conflict_cells': 'int', 'datum_suspect': 'bool'}],
                     'disposition': 'disposition'},
    'region-correct-v1': {
        'schema': 'str', 'ec_version': 'str', 'region_id': 'str', 'run': {'author_runtime': 'str', 'author_family': 'str'},
        'sources': [{'source_id': 'str', 'status': 'disposition', 'counts': 'counts', 'second_surveys': 'list',
                     'second_survey_needed_cells': 'int', 'receipts': {'detect': 'str', 'apply': 'str?', 'verify': 'str?'}}],
        'not_corrected': [{'source_id': 'str', 'reason': 'str'}], 'operator_asks': 'list',
        'inputs': [{'source_id': 'str', 'sha256': 'sha256'}], 'outputs': [{'path': 'str', 'sha256': 'sha256'}],
        'ec_sha256': 'sha256'},
})
_num = lambda v: isinstance(v, (int, float)) and not isinstance(v, bool)  # noqa: E731
_int = lambda v: isinstance(v, int) and not isinstance(v, bool)  # noqa: E731
_seq = lambda n, ok: lambda v: isinstance(v, list) and len(v) == n and all(ok(x) for x in v)  # noqa: E731
_TYPE = {'str': lambda v: isinstance(v, str), 'num': _num, 'int': _int, 'bool': lambda v: isinstance(v, bool),
         'list': lambda v: isinstance(v, list), 'sha256': lambda v: isinstance(v, str) and bool(SHA256.fullmatch(v)),
         'bbox': _seq(4, _num), 'sig': _seq(7, lambda x: _num(x) or isinstance(x, str)),
         'datums': _seq(2, lambda x: isinstance(x, str)), 'disposition': lambda v: v in DISPOSITIONS,
         'counts': lambda v: isinstance(v, dict) and all(_int(n) for n in v.values())}

def _check(spec, doc, where, out):
    if not isinstance(doc, dict): return out.append(f'{where.rstrip(".") or "receipt"}: missing or not an object') or out
    for key, want in spec.items():
        path, value = f'{where}{key}', doc.get(key)
        if isinstance(want, dict):
            _check(want, value, path + '.', out)
        elif isinstance(want, list):
            items = value if isinstance(value, list) else out.append(f'{path}: missing or not a list') or ()
            for i, item in enumerate(items):
                _check(want[0], item, f'{path}[{i}].', out)
        elif want.endswith('?') and value is None:
            continue
        elif key not in doc:
            out.append(f'{path}: missing')
        elif not _TYPE[want.rstrip('?')](value):
            out.append(f'{path}: not {want.rstrip("?")}')
        elif want == 'counts':
            out.extend(f'{path}.{name}: unknown code' for name in value if name not in CODES)
    return out

def check_receipt(kind, doc):
    """Problems with one EC receipt; [] = machine-valid, which is review-required, not acceptance."""
    if kind not in SCHEMAS: return [f'schema: unknown receipt kind {kind!r}']
    out = _check(SCHEMAS[kind], doc, '', [])
    if isinstance(doc, dict):
        if doc.get('schema') != kind: out.append(f'schema: expected {kind}')
        if doc.get('ec_version') != EC_VERSION: out.append(f'ec_version: expected {EC_VERSION}')
        if kind == 'ec-apply-v1' and doc.get('deepened_cells') != 0: out.append('deepened_cells: must be 0')
    return out

# GeoJSON property contract (EC5 writes, EC6 draws, EC8 reviews).
PROVENANCE_CLASSES = ('measured', 'filled', 'verified')
UNRESOLVED_KIND = 'unresolved-area'
UNRESOLVED_REASONS = ('hole', 'conflict', 'ring-range', 'datum-suspect', 'nodata')
SHOAL_HINT_KEY = 'shoal_hint_ft'

def block_class(codes):
    """Class of a builder block from its native codes (DESIGN §3.2); ValueError when empty or unknown."""
    classes = {CLASS_OF(code) for code in codes}
    if not classes: raise ValueError('block_class: no codes')
    if classes & {'unresolved', 'nodata', 'masked'}: return 'unresolved'
    if 'filled' in classes: return 'filled'
    return 'verified' if classes == {'verified'} else 'measured'
