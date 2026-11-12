"""EC receipt numbers: a finite JSON integer is valid exactly, however large; no float conversion is involved."""
import copy, json, math  # noqa: E401
import pytest
from skippercast.platform import seafloor_ec as ec
from tests.unit.test_seafloor_ec import APPLY, DETECT, REGION, VERIFY, edit

BIG = 10 ** 400  # 401 digits: below the interpreter's integer-digit limit, far above float range
# (document, path) for every ordinary num slot, nullable num slot and one duplicate_signature member exercised
PLAIN = ((DETECT, 'cell_m'), (APPLY, 'cell_m'), (APPLY, 'fixes[0].after_m'), (APPLY, 'fixes[0].before_min_m'),
         (DETECT, 'holes[0].ring_range_m'))
NULLABLE = ((DETECT, 'nodata'), (DETECT, 'sign.positive_fraction'), (VERIFY, 'pairs[0].mad_m'),
            (VERIFY, 'pairs[0].mean_signed_diff_m'))
SIG_PATHS = [f'duplicate_signature[{i}]' for i in range(7)]  # all seven signature members


def test_finite_integer_numbers_need_no_float_conversion():
    for doc, path in PLAIN + NULLABLE:
        for value in (BIG, -BIG, 0, -7, 12):
            before = copy.deepcopy(doc)
            assert edit(doc, path, value) == [], (path, value)
            assert doc == before  # the validator never mutates its input
    probe = copy.deepcopy(DETECT)
    probe['cell_m'] = BIG
    assert json.loads(json.dumps(probe, allow_nan=False))['cell_m'] == BIG  # canonical JSON keeps the exact integer
    assert ec.check_receipt('ec-detect-v1', json.loads(json.dumps(probe))) == [] and probe['cell_m'] == BIG


def test_nullable_numeric_slots_accept_finite_int_keep_null():
    for doc, path in NULLABLE:
        assert edit(doc, path, None) == [] and edit(doc, path, BIG) == [] and edit(doc, path, -BIG) == []
        assert edit(doc, path) == [f'{path}: missing']  # a missing key is still a problem, never a silent null


def test_signature_members_share_safe_predicate():
    for doc in (DETECT, APPLY):
        for path in SIG_PATHS:
            assert edit(doc, path, BIG) == [] and edit(doc, path, -BIG) == [], path
            assert edit(doc, path, 'EPSG:32610') == []  # existing string handling is retained
            assert edit(doc, path, True) == ['duplicate_signature: not sig'], path
            assert [edit(doc, path, bad) for bad in (math.nan, math.inf, -math.inf)] == \
                [['duplicate_signature: not sig']] * 3, path
        assert edit(doc, 'duplicate_signature', [BIG] * 6) == ['duplicate_signature: not sig']  # wrong length
        assert edit(doc, 'duplicate_signature', [BIG] * 7) == []


def test_later_problems_are_still_accumulated():
    control = copy.deepcopy(APPLY)
    control['cell_m'] = 2
    control['disposition'] = 'OK'
    control['fixes'] = [{**control['fixes'][0], 'bbox': [1, 2]}, 'bad']
    del control['provenance_sha256']
    huge = copy.deepcopy(control)
    huge['cell_m'] = BIG
    expected = ec.check_receipt('ec-apply-v1', control)
    assert len(expected) >= 4 and ec.check_receipt('ec-apply-v1', huge) == expected


def test_finite_float_and_nonnumeric_matrix_unchanged():
    extrema = (0.0, -0.0, -1.5, 1.7976931348623157e308, -1.7976931348623157e308, 5e-324, 3, -3)
    for doc, path in PLAIN + NULLABLE:
        assert [edit(doc, path, v) for v in extrema] == [[]] * len(extrema), path
        bad = (True, False, '1', [], {}, math.nan, math.inf, -math.inf)
        assert [edit(doc, path, v) for v in bad] == [[f'{path}: not num']] * len(bad), path
    assert edit(DETECT, 'width', BIG) == [] and edit(DETECT, 'width', 2.0) == ['width: not int']  # int slots unchanged
    assert edit(APPLY, 'fixes[0].bbox', [1, 1, BIG, 2]) == []


@pytest.mark.parametrize('doc', (APPLY, DETECT, VERIFY, REGION), ids=lambda d: d['schema'])
def test_all_receipt_kinds_and_review_hold_stay_intact(doc):
    kind = doc['schema']
    assert ec.check_receipt(kind, doc) == []
    assert edit(doc, 'schema', 'ec-bogus-v9') == ['schema: expected ' + kind]
    assert edit(doc, 'ec_version', '0.9') == [f'ec_version: expected {ec.EC_VERSION}']
    assert ec.check_receipt('ec-apply-v1', dict(APPLY, deepened_cells=1)) == ['deepened_cells: must be 0']
