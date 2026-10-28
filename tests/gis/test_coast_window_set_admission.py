"""#806 window-set admission through the producer-bound shared validator (GIS, offline).

The shared fixture factory builds a real window-set plan (one source tiled into
512x512 native windows), runs the real bridge dry run, and records one admission
window per native window. The validator re-derives the dry run, caps, window
population, grid tiling, pixel-centre owner and footprints; every tamper refuses.
Structurally valid evidence only, never scientific acceptance.
"""
import copy

import pytest

from tests.coast_contract_factory import load_helper, materialize

pytestmark = pytest.mark.gis
refs = load_helper('coast_refs')
validator = load_helper('validate_coast_receipt')
versions = load_helper('coast_receipt_versions')


@pytest.fixture(scope='module')
def graph(tmp_path_factory):
    tmp = tmp_path_factory.mktemp('window-set')
    instances, bindings = materialize(tmp, windows=4)
    return instances, refs.Resolver(bindings, allowed_root_ids=bindings)


def check(doc, resolver):
    return validator.validate(doc, resolver, root_id='queue:synthetic')


def test_window_set_admission_enqueue_and_run_validate(graph):
    instances, resolver = graph
    admission = instances['admission']
    check(admission, resolver)
    (grid,) = admission['grids']
    assert grid['definition']['tiling_version'] == 'window-set-v1'
    assert (grid['cols'], grid['rows'], grid['total']) == (4, 1, 4)
    assert [w['idx'] for w in admission['windows']] == [0, 1, 2, 3]
    assert len({w['window_key'] for w in admission['windows']}) == 4
    enqueue, run = instances['enqueue-receipt'], instances['run-summary']
    check(enqueue, resolver)
    check(run, resolver)
    assert [j['window_key'] for j in enqueue['jobs']] == [w['window_key'] for w in admission['windows']]
    # One per-window producer-cells record per window, in window order; no aggregate.
    assert [c['window_key'] for c in run['window_cells']] == [w['window_key'] for w in admission['windows']]
    assert [c['window_index'] for c in run['window_cells']] == [0, 1, 2, 3]
    assert all(c['producer'] is None and c['unknown'] for c in run['window_cells'])  # held: explicit unknowns
    assert run['sequence'] == 0 and run['continuation_of'] is None
    assert run['store_status_evidence']['kind'] == 'legacy_embedded'


def tampered(graph, change):
    instances, resolver = graph
    doc = copy.deepcopy(instances['admission'])
    change(doc)
    return doc, resolver


def drop_last(doc):
    doc['windows'].pop()


def reorder(doc):
    doc['windows'][0], doc['windows'][1] = doc['windows'][1], doc['windows'][0]


def shift_pixel_window(doc):
    doc['windows'][1]['pixel_window'] = doc['windows'][2]['pixel_window']


def grid_cols(doc):
    doc['grids'][0]['cols'] = 2


def grid_total(doc):
    doc['grids'][0]['total'] = 3


def footprint(doc):
    doc['windows'][2]['footprint'][0] += 1e-6


def overlap(doc):
    doc['windows'][3]['overlapping_segment_ids'] = []


def single_grid_for_set(doc):
    grid = doc['grids'][0]
    grid.update(cols=1, rows=1, total=1)


@pytest.mark.parametrize('change,message', [
    (drop_last, 'plan window population mismatch'),
    (reorder, 'window'),
    (shift_pixel_window, 'plan window population mismatch'),
    (grid_cols, 'window-set grid/window binding mismatch'),
    (grid_total, 'window-set grid/window binding mismatch'),
    (single_grid_for_set, 'window-set grid/window binding mismatch'),
    (footprint, 'window footprint binding mismatch'),
    (overlap, 'window overlap inventory mismatch'),
])
def test_window_set_admission_tamper_refuses(graph, change, message):
    doc, resolver = tampered(graph, change)
    with pytest.raises(ValueError, match=message):
        check(doc, resolver)


def test_window_set_tiling_change_breaks_grid_digest(graph):
    def change(doc):
        doc['grids'][0]['definition']['tiling']['anchor'][0] += 1e-6
    doc, resolver = tampered(graph, change)
    with pytest.raises(ValueError, match='grid/window source binding mismatch'):
        check(doc, resolver)


def test_single_selected_definition_cannot_stand_in_for_window_set(graph):
    from skippercast.coastal.coordinator.stages import digest

    def change(doc):
        grid = doc['grids'][0]
        definition = {k: v for k, v in grid['definition'].items() if k != 'tiling'}
        definition.update(tiling_version='single-selected-v1', pixel_window=doc['windows'][0]['pixel_window'])
        sha = digest(definition)
        grid.update(definition=definition, grid_sha256=sha, cols=1, rows=1, total=1)
        for window in doc['windows']:
            window['grid_sha256'] = sha
    doc, resolver = tampered(graph, change)
    with pytest.raises(ValueError):
        check(doc, resolver)


def test_v1_shared_run_contract_is_refused_for_v2_slot(graph):
    instances, resolver = graph
    run = instances['run-summary']
    graph_validator = validator.GraphValidator(resolver)
    with pytest.raises(ValueError, match='reference contract mismatch'):
        graph_validator.reference(run['legacy_run'], contract=versions.RUN_V2)
