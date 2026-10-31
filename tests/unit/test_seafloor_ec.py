"""EC0 seafloor error-correction contract: tolerance, shoal, no-deepening, independence, block class, receipts."""
import copy, functools, json, math, re  # noqa: E401
import pytest
from skippercast.platform import seafloor_ec as ec
from tests._support import ROOT

SHA, SIG = 'b' * 64, [9, 9, 'EPSG:32610', 2.0, -80.0, -1.0, -20.5]
H = {'ec_version': '1.0', 'source_id': 'usgs-pb', 'counts': {}, 'disposition': 'FIX'}
FIX = {'kind': 'hole', 'cells': 3, 'bbox': [1, 1, 2, 2], 'before_min_m': -21.0, 'after_m': -20.0}
APPLY = {**H, 'schema': 'ec-apply-v1', 'detect_sha256': SHA, 'input_sha256': SHA, 'corrected_sha256': SHA, 'fixes': [FIX],
         'provenance_sha256': SHA, 'cell_m': 2.0, 'deepened_cells': 0, 'duplicate_signature': SIG}
FILL = {'cells': 3, 'bbox': [1, 1, 2, 2], 'disposition': 'fill', 'ring_shallowest_m': -20.0, 'ring_range_m': 1.0}
DETECT = {**H, 'schema': 'ec-detect-v1', 'path_sha256': SHA, 'cell_m': 2.0, 'crs': 'EPSG:32610', 'width': 9, 'height': 9,
          'nodata': -9999.0, 'pits': [], 'spikes': [], 'sentinel_cells': 0, 'duplicate_signature': SIG,
          'holes': [FILL, {'cells': 40, 'bbox': [5, 5, 9, 9], 'disposition': 'hole'}],  # the second is over-size
          'fixture': {'refused': False, 'reasons': []}, 'sign': {'refused': False, 'positive_fraction': 0, 'reason': None}}
PAIR = {'second_source_id': 'noaa-bags', 'second_file_sha256': SHA, 'independent': True, 'reason': 'ok', 'mad_m': 0.1,
        'datums': ['MLLW', 'MLLW'], 'comparable': True, 'jointly_valid_cells': 1, 'mean_signed_diff_m': 0.25,
        'verified_cells': 1, 'conflict_cells': 0, 'datum_suspect': False}
VERIFY = {**H, 'schema': 'ec-verify-v1', 'apply_sha256': SHA, 'provenance_sha256': SHA, 'pairs': [PAIR]}
SRC = {'source_id': 'usgs-pb', 'status': 'PASS', 'counts': {}, 'second_surveys': [], 'second_survey_needed_cells': 0,
       'receipts': {'detect': 'D.json', 'apply': 'A.json', 'verify': 'V.json'}}
REGION = {'schema': 'region-correct-v1', 'ec_version': '1.0', 'region_id': 'mb', 'not_corrected': [], 'inputs': [],
          'run': {'author_runtime': 'x', 'author_family': 'y'}, 'operator_asks': [], 'outputs': [], 'ec_sha256': SHA,
          'sources': [SRC, {**SRC, 'status': 'REFUSED', 'receipts': {'detect': 'D.json'}}]}  # EC4: detect only
def edit(doc, path, *value):  # check_receipt of a copy with the key at path deleted (or set to the one value)
    *steps, last = [int(s) if s.isdigit() else s for s in re.findall(r'\w+', path)]
    new = copy.deepcopy(doc); node = functools.reduce(lambda n, s: n[s], steps, new)  # noqa: E702
    node.__setitem__(last, *value) if value else node.pop(last)
    return ec.check_receipt(doc['schema'], new)
def test_tolerance_shoal_no_deepening_and_value_errors():  # tol is the DESIGN formula (spec's 2.74 at 100 m is a slip)
    assert ec.tol_m(0) == 1.0 and abs(ec.tol_m(50) - 1.64) <= 0.01 and abs(ec.tol_m(100) - 2.79) <= 0.01
    assert ec.tol_m(-100) == ec.tol_m(100) and abs(ec.tol_m(20) - 1.127) <= 0.001  # EC3 relies on 1.2 m > tol(20)
    assert [ec.hole_max_cells(c) for c in (2, 4, 8, 16)] == [9, 4, 1, 0] and ec.shoal_pick([-12.0, -9.5, -30.0]) == -9.5
    cases = (([-10, -11], [1]), ([-10, -11], []), ([-10, -9], [1]))  # deepened, untreated changed, shallower fix
    assert [ec.no_deepening([-10, -10], after, treated) for after, treated in cases] == [[1], [1], []]
    nan = [math.nan, -5.0]  # a filled hole was nodata; NaN -> NaN is unchanged; an untreated hole silently filled
    assert [ec.no_deepening(nan, a, t) for a, t in (([-20.0, -5.0], [0]), (nan, []), ([-20.0, -5.0], []))] == [[], [], [0]]
    for f, *args in ((ec.shoal_pick, []), (ec.no_deepening, [-1.0], [-1.0, -2.0], []), (ec.block_class, [12]),
                     (ec.no_deepening, [-1.0], [-1.0], [1]), (ec.no_deepening, [-1.0], [-1.0], [-1]), (ec.block_class, [])):
        with pytest.raises(ValueError): f(*args)
def test_independence_and_block_class():
    bag, topo = {'id': 'noaa-bags', 'adapter': 'bag'}, {'id': 'bluetopo', 'adapter': 'bluetopo-geotiff-source-review'}
    usgs, gebco, ind = {'id': 'usgs-pb', 'adapter': 'geotiff'}, dict(topo, adapter='gebco-grid-deep-fill'), ec.independent
    assert ind(topo, 'a.tif', usgs, 'b.tif') == (False, 'compilation:bluetopo-geotiff-source-review')
    assert ind(usgs, 'b.tif', gebco, 'a.tif', duplicate=True) == (False, 'compilation:gebco-grid-deep-fill')
    assert ind(bag, 'H11879_MB_2m_MLLW_1of5.tif', bag, 'BAG__H11879_MB_4m_MLLW_2of5.tif') == (False, 'same-acquisition:H11879')
    others = ((bag, 'H13151_MB_4m.bag', 1), (bag, 'H13151_MB_4m.bag', 0), (bag, 'x_H13151.bag', 0), (usgs, 'c.tif', 0))
    assert [ind(usgs, 'b.tif', e, f, bool(d)) for e, f, d in others] == \
        [(False, 'duplicate'), (True, 'ok'), (False, 'unknown-acquisition'), (False, 'same-acquisition:usgs-pb')]
    assert [ec.block_class(c) for c in ([10, 10, 40], [10, 20, 30], [30, 30], [10, 11], [30, 0], [10, 50], [30, 10])] == \
        ['unresolved', 'filled', 'verified', 'measured', 'unresolved', 'unresolved', 'measured']
    assert {ec.REASON_OF(c) for c in (40, 41, 42, 43, 0)} == set(ec.UNRESOLVED_REASONS) and ec.REASON_OF(10) == 'measured'
def test_check_receipt_names_the_failing_key_and_doc_rule():
    assert [ec.check_receipt(d['schema'], d) for d in (APPLY, DETECT, VERIFY, REGION)] == [[]] * 4  # complete controls
    assert all(json.dumps(d, allow_nan=False) for d in (APPLY, DETECT, VERIFY, REGION))  # the canonical writer agrees
    for path, value in {'provenance_sha256': None, 'ec_version': '0.9', 'deepened_cells': 1, 'input_sha256': 'B' * 64,
                        'counts.bogus': 2, 'disposition': 'OK', 'fixes[0].bbox': [1, 2], 'schema': 'ec-detect-v1'}.items():
        problems = edit(APPLY, path, value)
        assert problems and all(p.startswith(path.split('.')[0]) for p in problems), (path, problems)
    assert edit(APPLY, 'provenance_sha256') == ['provenance_sha256: missing'] and edit(APPLY, 'fixes[0].after_m') == \
        ['fixes[0].after_m: missing'] and ec.check_receipt('ec-apply-v1', []) == ['receipt: missing or not an object']
    assert ec.check_receipt('ec-apply-v9', APPLY) == ["schema: unknown receipt kind 'ec-apply-v9'"]
    text = ' '.join((ROOT / 'docs' / 'seafloor-ec.md').read_text().split())
    assert 'A machine-valid receipt is review-required, not acceptance; nothing here converts a datum or certifies' \
        ' navigation.' in text and '/home/' not in text and '/Users/' not in text
def test_nullable_keys_are_still_required_and_numbers_finite():
    for doc, path in ((DETECT, 'nodata'), (DETECT, 'sign.reason'), (DETECT, 'holes[0].ring_range_m'),
                      (VERIFY, 'pairs[0].mean_signed_diff_m'), (VERIFY, 'pairs[0].mad_m'),
                      (REGION, 'sources[0].receipts.verify'), (REGION, 'sources[1].receipts.detect')):
        assert edit(doc, path) == [f'{path}: missing'], path
    for status in ('PASS', 'FIX', 'VERIFY', 'UNRESOLVED', 'refused'):  # only an exact REFUSED source is detect-only
        problems = set(edit(REGION, 'sources[0]', {**SRC, 'status': status, 'receipts': {'detect': 'D.json'}}))
        assert {'sources[0].receipts.apply: missing', 'sources[0].receipts.verify: missing'} <= problems, status
    assert len(edit(DETECT, 'holes[1].disposition', 'Hole')) == 2  # over-size (ring keys omitted) only by exact wording
    for doc, path in ((DETECT, 'nodata'), (DETECT, 'sign.positive_fraction'), (VERIFY, 'pairs[0].mad_m'),
                      (VERIFY, 'pairs[0].mean_signed_diff_m')):
        assert edit(doc, path, None) == [] and edit(doc, path, -1.5) == []  # null (unavailable) and finite controls
        assert [edit(doc, path, bad) for bad in (math.nan, math.inf, -math.inf)] == [[f'{path}: not num']] * 3, path
    assert edit(APPLY, 'fixes[0].bbox', [1, 1, math.nan, 2]) == ['fixes[0].bbox: not bbox']
    for bad in ([5, 5, 5, 5], [1, 1, 2.0, 2], [-1, 0, 1, 1], [2, 1, 1, 2]):  # bbox is end-exclusive ints: col0 < col1
        assert edit(APPLY, 'fixes[0].bbox', bad) == ['fixes[0].bbox: not bbox'], bad
    assert edit(APPLY, 'fixes[0].bbox', [5, 5, 6, 6]) == []  # one cell at row 5, col 5
