"""EC0 seafloor error-correction contract: tolerance, shoal, no-deepening, independence, block class, receipts."""
import math

import pytest

from skippercast.platform import seafloor_ec as ec
from tests._support import ROOT

SHA, SIG = 'b' * 64, [100, 100, 'EPSG:32610', 2.0, -80.0, -1.0, -20.5]
APPLY = {'schema': 'ec-apply-v1', 'ec_version': '1.0', 'source_id': 'usgs-point-buchon', 'detect_sha256': SHA,
         'input_sha256': SHA, 'corrected_sha256': SHA, 'provenance_sha256': SHA, 'cell_m': 2.0,
         'fixes': [{'kind': 'hole', 'cells': 3, 'bbox': [1, 1, 2, 2], 'before_min_m': -21.0, 'after_m': -20.0}],
         'counts': {'measured': 9990, 'filled-hole': 3}, 'duplicate_signature': SIG, 'deepened_cells': 0,
         'disposition': 'FIX'}


def test_tolerance_thresholds_and_shoal_rule():
    # DESIGN §5 formula; 2 x sqrt(0.25 + 1.69) = 2.786 at 100 m (the EC0 spec's 2.74 is an arithmetic slip)
    assert ec.tol_m(0) == 1.0 and abs(ec.tol_m(50) - 1.64) <= 0.01 and abs(ec.tol_m(100) - 2.79) <= 0.01
    assert ec.tol_m(-100) == ec.tol_m(100) and abs(ec.tol_m(20) - 1.127) <= 0.001  # EC3 relies on 1.2 m > tol(20)
    assert [ec.hole_max_cells(c) for c in (2, 4, 8, 16)] == [9, 4, 1, 0]
    assert ec.THRESHOLDS.hole_max_cells is ec.hole_max_cells and ec.THRESHOLDS.DATUM_SUSPECT['min_cells'] == 1000
    assert ec.shoal_pick([-12.0, -9.5, -30.0]) == -9.5 and ec.shoal_pick(iter([-3.0])) == -3.0
    with pytest.raises(ValueError): ec.shoal_pick([])


def test_no_deepening_flags_deeper_and_untreated_changes_only():
    cases = (([-10, -11], [1]), ([-10, -11], []), ([-10, -9], [1]))  # deepened, untreated changed, shallower fix
    assert [ec.no_deepening([-10, -10], after, treated) for after, treated in cases] == [[1], [1], []]
    assert ec.no_deepening([math.nan, -5.0], [-20.0, -5.0], treated=[0]) == []  # a filled hole was nodata
    assert ec.no_deepening([math.nan, -5.0], [math.nan, -5.0], treated=[]) == []
    assert ec.no_deepening([math.nan, -5.0], [-20.0, -5.0], treated=[]) == [0]  # untreated hole silently filled
    for before, after, treated in (([-1.0], [-1.0, -2.0], []), ([-1.0], [-1.0], [1]), ([-1.0], [-1.0], [-1])):
        with pytest.raises(ValueError): ec.no_deepening(before, after, treated)


def test_independence_rule():
    bag, topo = {'id': 'noaa-bags', 'adapter': 'bag'}, {'id': 'bluetopo', 'adapter': 'bluetopo-geotiff-source-review'}
    usgs = {'id': 'usgs-point-buchon', 'adapter': 'geotiff'}
    assert ec.independent(topo, 'a.tif', usgs, 'b.tif') == (False, 'compilation:bluetopo-geotiff-source-review')
    assert ec.independent(usgs, 'b.tif', dict(topo, adapter='gebco-grid-deep-fill'), 'a.tif') == \
        (False, 'compilation:gebco-grid-deep-fill')
    assert ec.independent(bag, 'H11879_MB_2m_MLLW_1of5.tif', dict(bag, id='other'), 'BAG__H11879_MB_4m_MLLW_2of5.tif') \
        == (False, 'same-acquisition:H11879')
    assert ec.independent(usgs, 'b.tif', bag, 'H13151_MB_4m.bag', duplicate=True) == (False, 'duplicate')
    assert ec.independent(usgs, 'b.tif', bag, 'H13151_MB_4m.bag') == (True, 'ok')
    assert ec.independent(usgs, 'b.tif', bag, 'survey_H13151.bag') == (False, 'unknown-acquisition')
    assert ec.independent(usgs, 'b.tif', dict(usgs), 'c.tif') == (False, 'same-acquisition:usgs-point-buchon')


def test_block_class_and_code_classes():
    assert [ec.block_class(c) for c in ([10, 10, 40], [10, 20, 30], [30, 30], [10, 11])] == \
        ['unresolved', 'filled', 'verified', 'measured']
    assert ec.block_class([30, 0]) == ec.block_class([10, 50]) == 'unresolved' and ec.block_class([30, 10]) == 'measured'
    assert (ec.CLASS_OF(43), ec.REASON_OF(41), ec.REASON_OF(10)) == ('unresolved', 'conflict', 'measured')
    assert {ec.REASON_OF(c) for c in (40, 41, 42, 43, 0)} == set(ec.UNRESOLVED_REASONS)
    for bad in ([], [12], [True]):
        with pytest.raises(ValueError): ec.block_class(bad)


def test_check_receipt_names_the_failing_key():
    assert ec.check_receipt('ec-apply-v1', APPLY) == []
    cases = {'provenance_sha256': {'provenance_sha256': None}, 'ec_version': {'ec_version': '0.9'},
             'deepened_cells': {'deepened_cells': 1}, 'counts.bogus': {'counts': {'measured': 1, 'bogus': 2}},
             'input_sha256': {'input_sha256': 'B' * 64}, 'disposition': {'disposition': 'OK'},
             'fixes[0].bbox': {'fixes': [dict(APPLY['fixes'][0], bbox=[1, 2])]}, 'schema': {'schema': 'ec-detect-v1'}}
    for key, change in cases.items():
        problems = ec.check_receipt('ec-apply-v1', {**APPLY, **change})
        assert problems and all(p.startswith(key) for p in problems), (key, problems)
    assert ec.check_receipt('ec-apply-v1', {k: v for k, v in APPLY.items() if k != 'provenance_sha256'}) == \
        ['provenance_sha256: missing']
    assert ec.check_receipt('ec-apply-v1', []) == ['receipt: missing or not an object']
    assert ec.check_receipt('ec-apply-v9', APPLY) == ["schema: unknown receipt kind 'ec-apply-v9'"]


def test_doc_states_review_rule_and_has_no_home_paths():
    text = (ROOT / 'docs' / 'seafloor-ec.md').read_text()
    assert 'A machine-valid receipt is review-required, not acceptance; nothing here converts a datum or certifies' \
        ' navigation.' in ' '.join(text.split())
    assert '/home/' not in text and '/Users/' not in text
