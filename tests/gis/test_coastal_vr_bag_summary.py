"""verify() rederives the whole VR BAG summary from the source before it returns ok."""
import copy
import json

import h5py
import numpy as np
import pytest

from skippercast.coastal.handoff import vr_refinements as vr
from skippercast.coastal.handoff.common import ref
from tests.gis.test_coastal_vr_refinements import NODATA, emit, refinement_blocks, vr_bag  # noqa: F401

pytestmark = pytest.mark.gis

SUCCESS = dict(ok=True, placement='exact_lattice', outputs=3, supergrids=4, refinement_cells=50, valid_cells=48)
REFUSED = r'receipt BAG (semantics|summary) differ(s)? from source'
# One well-shaped but source-contradicting value per BAG summary field.
FORGED = dict(
    overview_shape=[1, 1], overview_resolution_m=[1.0, 1.0], overview_bounds=[0.0, 0.0, 1.0, 1.0],
    horizontal_crs='forged', vertical_datum='NAVD88', vertical_wkt='forged', uncertainty_type='forged',
    nodata=-9999.0, active_supergrids=999, refinement_records=999, active_refinement_records=0,
    trailing_padding_records=0, valid_refinement_cells=0, resolution_classes=[[999.0, 999.0]])


def snapshot(root):
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in sorted(root.rglob('*')) if p.is_file()}


def tampered(receipt, edit):
    changed = json.loads(json.dumps(receipt))
    edit(changed['bag'])
    return changed


def test_source_accounting_is_independent_of_the_summary(vr_bag):
    root, source, _, _, _ = vr_bag
    with h5py.File(source) as bag:
        meta = bag['BAG_root']['varres_metadata'][:]
        stored = bag['BAG_root']['varres_refinements'].shape[1]
    active = int(meta['dimensions_x'][meta['dimensions_x'] > 0].size)
    blocks = refinement_blocks(source)
    cells = sum(b.size for b in blocks.values())
    valid = sum(int((np.isfinite(b['depth']) & (b['depth'] != NODATA)).sum()) for b in blocks.values())
    summary = emit(vr_bag)['bag']
    assert (active, stored, cells, stored - cells, valid) == (4, 53, 50, 3, 48)
    assert (summary['active_supergrids'], summary['refinement_records'], summary['active_refinement_records'],
            summary['trailing_padding_records'], summary['valid_refinement_cells']) == (4, 53, 50, 3, 48)
    assert summary['overview_shape'] == [6, 6]
    assert [list(c) for c in summary['resolution_classes']] == [[2.0, 2.0], [3.0, 3.0]]


def test_in_memory_and_serialized_receipts_both_verify(vr_bag):
    root = vr_bag[0]
    receipt = emit(vr_bag)
    assert isinstance(receipt['bag']['resolution_classes'][0], tuple)
    assert vr.verify(root, receipt) == SUCCESS
    path = root / 'derived' / 'vr-refinements-receipt.json'
    assert isinstance(json.loads(path.read_text())['bag']['resolution_classes'][0], list)
    assert vr.verify(root, ref(root, path, vr.SCHEMA)) == SUCCESS


@pytest.mark.parametrize('field', sorted(FORGED))
def test_each_source_summary_claim_is_verified(vr_bag, field):
    root = vr_bag[0]
    receipt = emit(vr_bag)
    assert FORGED[field] != json.loads(json.dumps(receipt['bag'][field]))
    with pytest.raises(ValueError, match=REFUSED):
        vr.verify(root, tampered(receipt, lambda bag: bag.__setitem__(field, FORGED[field])))


@pytest.mark.parametrize('field', sorted(FORGED))
def test_serialized_rebound_receipt_is_not_a_shortcut(vr_bag, field):
    root = vr_bag[0]
    receipt = emit(vr_bag)
    path = root / 'rebound-receipt.json'
    path.write_text(json.dumps(tampered(receipt, lambda bag: bag.__setitem__(field, FORGED[field]))))
    artifact = ref(root, path, vr.SCHEMA)
    assert artifact['bytes'] == path.stat().st_size
    with pytest.raises(ValueError, match=REFUSED):
        vr.verify(root, artifact)


@pytest.mark.parametrize('field', sorted(FORGED))
def test_missing_summary_field_is_refused(vr_bag, field):
    root = vr_bag[0]
    with pytest.raises(ValueError, match=REFUSED):
        vr.verify(root, tampered(emit(vr_bag), lambda bag: bag.pop(field)))


def test_extra_summary_field_is_refused(vr_bag):
    root = vr_bag[0]
    with pytest.raises(ValueError, match=REFUSED):
        vr.verify(root, tampered(emit(vr_bag), lambda bag: bag.__setitem__('unreviewed', 1)))


@pytest.mark.parametrize('field, value', [
    ('active_supergrids', 4.0), ('active_supergrids', '4'), ('refinement_records', 53.0),
    ('trailing_padding_records', 3.0), ('valid_refinement_cells', 48.0), ('overview_shape', [6.0, 6.0]),
    ('resolution_classes', [[2, 2], [3, 3]]), ('resolution_classes', [[3.0, 3.0], [2.0, 2.0]])])
def test_equal_looking_substitutions_are_refused(vr_bag, field, value):
    root = vr_bag[0]
    with pytest.raises(ValueError, match=REFUSED):
        vr.verify(root, tampered(emit(vr_bag), lambda bag: bag.__setitem__(field, value)))


def test_nearest_cell_summary_does_not_grant_science_approval(vr_bag):
    root = vr_bag[0]
    receipt = emit(vr_bag, placement='nearest_cell', output_dir='nearest')
    assert receipt['placement']['science_ruling_required'] is True
    assert vr.verify(root, receipt)['placement'] == 'nearest_cell'
    with pytest.raises(ValueError, match=REFUSED):
        vr.verify(root, tampered(receipt, lambda bag: bag.__setitem__('active_supergrids', 999)))
    assert receipt['placement']['science_ruling_required'] is True


def test_verify_never_repairs_the_receipt_or_inputs(vr_bag):
    root = vr_bag[0]
    receipt = emit(vr_bag)
    forged = tampered(receipt, lambda bag: bag.__setitem__('uncertainty_type', 'forged'))
    before = snapshot(root)
    assert vr.verify(root, receipt) == SUCCESS
    with pytest.raises(ValueError, match=REFUSED):
        vr.verify(root, forged)
    assert snapshot(root) == before
    assert forged['bag']['uncertainty_type'] == 'forged'
    assert copy.deepcopy(receipt)['bag'] == receipt['bag']
