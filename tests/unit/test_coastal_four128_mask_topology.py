"""SC-5b mask-topology pre-scan: pure topology, the --require-holes gate and the
source-free plan. Synthetic masks only; the cached BAG is never opened here."""
import copy
import json
from pathlib import Path

import pytest

from research.scripts import coastal_four128_mask_topology as topo
from tests._support import ROOT
from tests.unit.test_coastal_four128_budget import SIGNED_V7, V7_LIMITS, amendment

SIDE = topo.SIDE
REAL_GUARD = topo.source_guard


@pytest.fixture(autouse=True)
def no_worktree_guard(monkeypatch):
    # plan() resolves the guard at call time; the real guard is exercised on fake
    # code roots below (and in test_coastal_four128_mask_topology_boundary.py), so a
    # stray cache elsewhere in a developer checkout cannot change these results.
    monkeypatch.setattr(topo, 'source_guard', lambda root=None: [])


def empty():
    return [[False] * SIDE for _ in range(SIDE)]


def with_cells(cells):
    grid = empty()
    for r, c in cells:
        grid[r][c] = True
    return grid


def enclosed_hole():
    return with_cells([(60, 60), (60, 61), (61, 60), (61, 61)])  # 2x2 interior hole


def border_notch():
    return with_cells([(0, 10), (0, 11), (1, 10)])  # touches the north edge


def diagonal_pair():
    return with_cells([(40, 40), (41, 41)])  # one region under 8-, two under 4-neighbour


def records(grids):
    return [dict(topo.window_topology(g), label=label, window=list(w))
            for label, g, w in zip(topo.LABELS, grids, topo.WINDOWS)]


def receipt_for(grids):
    windows = records(grids)
    met, reasons = topo.require_holes(windows)
    return dict(schema=topo.SCHEMA, run_tag=topo.RUN_TAG, windows=windows, native_bounds=list(topo.BOUNDS),
                source=dict(opens=1, sha256_recomputed=False),
                require_holes=dict(topo.REQUIRE_HOLES, met=met, reasons=reasons))


# ------------------------------------------------------------------ topology

def test_runs_round_trip_and_are_bounded():
    grid = with_cells([(0, 0), (0, 1), (0, 5), (127, 127), (64, 3)])
    runs = topo.runs_from_mask(grid)
    assert runs == [[0, 0, 2], [0, 5, 1], [64, 3, 1], [127, 127, 1]]
    assert topo.mask_from_runs(runs) == grid
    for bad in ([[0, 0, 2], [0, 2, 1]],   # touching runs are not maximal
                [[1, 0, 1], [0, 0, 1]],   # not row-major
                [[0, 127, 2]],            # past the window edge
                [[0, 0, 0]], [[0, 0, True]], [[128, 0, 1]]):
        with pytest.raises(ValueError):
            topo.mask_from_runs(bad)


def test_enclosed_versus_border_connected():
    hole = topo.window_topology(enclosed_hole())
    assert hole['unsupported_cells'] == 4 and hole['supported_cells'] == SIDE * SIDE - 4
    assert hole['topology_4'] == dict(regions=1, enclosed_regions=1, border_regions=0, enclosed_cells=4,
                                      border_cells=0, largest_enclosed_cells=4)
    assert hole['components_4'] == [dict(cells=4, row_range=[60, 61], col_range=[60, 61],
                                         touches_border=False, enclosed=True)]
    notch = topo.window_topology(border_notch())
    assert notch['unsupported_cells'] == 3
    assert notch['topology_4']['enclosed_regions'] == 0 and notch['topology_4']['border_regions'] == 1
    assert notch['components_4'][0]['touches_border'] is True


def test_four_and_eight_neighbour_topology_are_both_reported():
    pair = topo.window_topology(diagonal_pair())
    assert pair['topology_4']['regions'] == 2 and pair['topology_4']['enclosed_regions'] == 2
    assert pair['topology_8']['regions'] == 1 and pair['topology_8']['enclosed_regions'] == 1
    # A diagonal chain reaching the edge is border-connected under 8 but has an enclosed 4-part.
    chain = topo.window_topology(with_cells([(0, 5), (1, 6), (2, 7)]))
    assert chain['topology_8'] == dict(regions=1, enclosed_regions=0, border_regions=1, enclosed_cells=0,
                                       border_cells=3, largest_enclosed_cells=0)
    assert chain['topology_4']['enclosed_regions'] == 2 and chain['topology_4']['border_regions'] == 1


def test_counts_are_not_proof_of_holes():
    # Same unsupported count in every window; only the topology differs.
    notches = [border_notch()] * 4
    met, reasons = topo.require_holes(records(notches))
    assert not met and any('no enclosed' in r for r in reasons)
    grids = [border_notch(), border_notch(), with_cells([(60, 60), (60, 61), (61, 60)]), border_notch()]
    met, reasons = topo.require_holes(records(grids))
    assert met and reasons == []


def test_require_holes_per_window_minimum_and_supported_floor():
    met, reasons = topo.require_holes(records([enclosed_hole(), empty(), enclosed_hole(), enclosed_hole()]))
    assert not met and reasons == ['windows without an unsupported cell: B']
    mostly_holes = [[c > 2 or r > 100 for c in range(SIDE)] for r in range(SIDE)]  # < 8192 supported
    met, reasons = topo.require_holes(records([enclosed_hole(), enclosed_hole(), mostly_holes, enclosed_hole()]))
    assert not met and "supported-pair floor: C" in reasons[0]
    assert not topo.require_holes(records([enclosed_hole()] * 3))[0]


def test_whole_window_unsupported_is_bounded():
    full = [[True] * SIDE for _ in range(SIDE)]
    record = topo.window_topology(full)
    assert record['whole_window_unsupported'] is True
    assert len(record['unsupported_row_runs']) == SIDE
    checker = [[(r + c) % 2 == 0 for c in range(SIDE)] for r in range(SIDE)]
    with pytest.raises(ValueError, match='bounded receipt'):
        topo.window_topology(checker)


def test_receipt_verification_recomputes_from_runs_and_detects_tampering():
    doc = receipt_for([enclosed_hole(), border_notch(), diagonal_pair(), border_notch()])
    assert doc['require_holes']['met'] is True
    out = topo.verify_receipt(json.loads(json.dumps(doc)))
    assert out['met'] is True
    assert [w['enclosed_4'] for w in out['per_window']] == [1, 0, 2, 0]
    for mutate in (lambda d: d['windows'][0]['topology_4'].update(enclosed_regions=5),
                   lambda d: d['windows'][1]['components_4'][0].update(enclosed=True),
                   lambda d: d['windows'][2].update(unsupported_cells=1),
                   lambda d: d['windows'][0]['unsupported_row_runs'].pop(),
                   lambda d: d['require_holes'].update(met=False),
                   lambda d: d['source'].update(opens=2),
                   lambda d: d['source'].update(sha256_recomputed=True),
                   lambda d: d['windows'][3].update(window=[4146, 3488, 128, 128]),
                   lambda d: d['windows'].reverse(),
                   lambda d: d.update(native_bounds=[0, 0, 0, 0]),
                   lambda d: d.update(run_tag='20261020p2')):
        bad = copy.deepcopy(doc)
        mutate(bad)
        with pytest.raises(ValueError):
            topo.verify_receipt(bad)


def review_for(raw, **changes):
    review = dict(schema=topo.REVIEW_SCHEMA, status='ACCEPTED_TOPOLOGY_OBSERVATION_ONLY', independent=True,
                  receipt=dict(sha256=topo.digest(raw), bytes=len(raw)), require_holes_met=True,
                  scientific_acceptance=False, holds=[],
                  reviewer=dict(profile='sol-reviewer', model='gpt-6.1-sol'))
    review.update(changes)
    return review


def test_independent_review_gate():
    raw = topo.encoded(receipt_for([enclosed_hole(), border_notch(), diagonal_pair(), border_notch()]))
    assert topo.validate_review(review_for(raw), raw)['met'] is True
    for changes in (dict(reviewer=dict(profile='opus-coder', model='gpt-6.1-sol')),
                    dict(reviewer=dict(profile='sol-reviewer', model='claude-opus-5-5')),
                    dict(independent=False), dict(holds=['hold']), dict(scientific_acceptance=True),
                    dict(status='ACCEPTED'), dict(require_holes_met=False),
                    dict(receipt=dict(sha256='0' * 64, bytes=len(raw)))):
        with pytest.raises(ValueError):
            topo.validate_review(review_for(raw, **changes), raw)
    # A reviewer cannot accept a receipt whose own gate fails.
    failing = topo.encoded(receipt_for([border_notch()] * 4))
    with pytest.raises(ValueError):
        topo.validate_review(review_for(failing), failing)


# ------------------------------------------------------------------ source-free plan

def synthetic_amendment(tmp_path, **changes):
    doc = amendment()
    doc.update(run_tag=topo.RUN_TAG, cash=dict(maximum=0, new_spend=0),
               read_plan=dict(pre_scan_opens=1, run_admissions=8, retries=0, downloads=0, network_requests=0,
                              extra_source_identity_reads=0, pre_scan_reservation_bytes=36757568),
               retained_output=dict(prescan_reservation_bytes=1048576, prior_retained_bytes=89163592))
    for key, value in changes.items():
        doc[key].update(value) if isinstance(value, dict) else doc.update({key: value})
    p = tmp_path / 'amendment.json'
    p.write_text(json.dumps(doc))
    return p


@pytest.fixture
def ledger(monkeypatch):
    monkeypatch.setattr(topo, '_ledger_limits', lambda raw: dict(V7_LIMITS))


def test_pinned_geometry_matches_the_shared_partial_pins():
    assert topo.pinned_geometry() is True
    assert list(topo.COUNT_ONLY_MASK_INVALID) == [14, 4, 299, 18]


def test_plan_never_touches_the_source(tmp_path, ledger, monkeypatch):
    opened = []
    monkeypatch.setattr(topo, 'open_source', lambda *a, **k: opened.append(a))
    plan = topo.plan(synthetic_amendment(tmp_path), project=tmp_path, head='a' * 40)
    assert opened == [] and topo.OPENS == []
    assert plan['source_opened'] is False and plan['windows'] == [list(w) for w in topo.WINDOWS]
    assert plan['output_root'] == str(tmp_path / 'outputs/sc5-partial-20261020p1-prescan')
    assert plan['amendment']['remaining_run_allowance_bytes'] == 8 * 36757568
    assert plan['amendment']['charged_in_advance'] is True and plan['amendment']['refunds'] is False
    assert plan['receipt_max_bytes'] == 1048576
    command = ' '.join(plan['command'])
    assert 'RuntimeMaxSec=180' in command and 'MemoryMax=1073741824' in command and ' scan ' in command
    assert not (tmp_path / 'outputs').exists()


@pytest.mark.parametrize('changes', [
    dict(run_tag='20261020r3'),
    dict(read_plan=dict(pre_scan_opens=2)),
    dict(read_plan=dict(retries=1)),
    dict(read_plan=dict(downloads=1)),
    dict(read_plan=dict(pre_scan_reservation_bytes=1)),
    dict(retained_output=dict(prescan_reservation_bytes=2097152)),
    dict(cash=dict(maximum=1)),
    dict(source=dict(sc5_geometry_prescan_charged_bytes=0)),
])
def test_plan_refuses_a_different_read_plan(tmp_path, ledger, changes):
    with pytest.raises(ValueError, match='exactly one precharged pre-scan open'):
        topo.plan(synthetic_amendment(tmp_path, **changes), project=tmp_path)


def test_plan_binds_the_reviewed_ledger_head(tmp_path):
    # Unpatched: synthetic bytes are not the signed head.
    with pytest.raises(ValueError, match='charge ledger head'):
        topo.plan(synthetic_amendment(tmp_path), project=tmp_path)
    if SIGNED_V7[0].is_file():  # maintainer machine: the genuine signed bytes plan cleanly
        plan = topo.plan(SIGNED_V7[0], project=tmp_path)
        assert plan['amendment']['sha256'] == SIGNED_V7[1]
        assert plan['amendment']['limits'] == V7_LIMITS


def test_existing_output_root_is_preserved(tmp_path, ledger):
    (tmp_path / 'outputs/sc5-partial-20261020p1-prescan').mkdir(parents=True)
    with pytest.raises(ValueError, match='preserve it'):
        topo.plan(synthetic_amendment(tmp_path), project=tmp_path)


def test_source_is_opened_at_most_once(monkeypatch):
    monkeypatch.setattr(topo, 'OPENS', [])
    calls = []
    assert topo.open_source('/x/source.bag', lambda p: calls.append(p) or 'dataset') == 'dataset'
    with pytest.raises(RuntimeError, match='once'):
        topo.open_source('/x/source.bag', lambda p: calls.append(p))
    assert calls == ['/x/source.bag']


def test_resource_envelope_and_clean_head(tmp_path):
    files = {'/proc/self/cgroup': '0::/user.slice/u.service\n',
             '/sys/fs/cgroup/user.slice/u.service/memory.max': '1073741824\n',
             '/sys/fs/cgroup/user.slice/u.service/pids.max': '32\n'}
    assert topo.resource_envelope(files.__getitem__)['readings'] == {'memory.max': '1073741824', 'pids.max': '32'}
    for key, value in (('memory.max', 'max\n'), ('pids.max', '4096\n')):
        bad = dict(files, **{'/sys/fs/cgroup/user.slice/u.service/' + key: value})
        with pytest.raises(ValueError, match='bounded unit'):
            topo.resource_envelope(bad.__getitem__)

    class Done:
        def __init__(self, out):
            self.stdout = out

    calls = []

    def git(outputs):
        it = iter(outputs)
        return lambda argv, **k: calls.append(argv) or Done(next(it))
    assert topo.clean_head('a' * 40, run=git(['a' * 40 + '\n', '', ''])) == 'a' * 40
    # The third query lists IGNORED entries (stale bytecode, stray modules) in the imported trees.
    assert calls[2][-3:] == ['--', 'src/skippercast', 'research/scripts'] and '--ignored' in calls[2]
    for head, outputs in (('a' * 40, ['b' * 40, '', '']),
                          ('a' * 40, ['a' * 40, ' M research/scripts/x.py', '']),
                          ('a' * 40, ['a' * 40, '?? src/skippercast/stray.py', '']),
                          ('a' * 40, ['a' * 40, '', '!! src/skippercast/coastal/__pycache__/x.pyc']),
                          ('a' * 40, ['a' * 40, '', '!! research/scripts/__pycache__/']),
                          ('a' * 7, ['a' * 7, '', '']), (None, ['', '', ''])):
        with pytest.raises(ValueError, match='clean reviewed head'):
            topo.clean_head(head, run=git(outputs))


def fake_code_root(tmp_path):
    root = tmp_path / 'code'
    for tree in topo.IMPORTED_TREES:
        (root / tree).mkdir(parents=True)
    guard = root / topo.GUARD_RELATIVE
    guard.parent.mkdir(parents=True)
    guard.write_bytes((ROOT / topo.GUARD_RELATIVE).read_bytes())
    (root / 'src/skippercast/__init__.py').write_text('')
    (root / 'research/scripts/coastal_four128_resources.py').write_text('')
    return root


def test_source_guard_covers_every_imported_tree(tmp_path):
    root = fake_code_root(tmp_path)
    assert REAL_GUARD(root) == [str(root / t) for t in topo.IMPORTED_TREES]
    hazards = [('src/skippercast/__pycache__', 'dir', 'bytecode'),
               ('src/skippercast/coastal/x.cpython-312.pyc', 'file', 'bytecode'),
               ('research/scripts/__pycache__', 'dir', 'bytecode'),
               ('research/scripts/coastal_four128_resources.pyc', 'file', 'bytecode'),
               ('src/skippercast/linked.py', 'link', 'symlink'),
               ('research/scripts/linked.py', 'link', 'symlink')]
    for rel, kind, message in hazards:
        p = root / rel
        if kind == 'dir':
            p.mkdir()
        elif kind == 'file':
            p.write_bytes(b'')
        else:
            p.symlink_to(root / 'src/skippercast/__init__.py')
        with pytest.raises(ValueError, match=message):
            REAL_GUARD(root)
        p.rmdir() if kind == 'dir' else p.unlink()
    assert REAL_GUARD(root)
    # The guard itself must be a regular reviewed file, loaded from source.
    guard = root / topo.GUARD_RELATIVE
    guard.rename(guard.with_name('real.py'))
    guard.symlink_to(guard.with_name('real.py'))
    with pytest.raises(ValueError, match='regular file'):
        REAL_GUARD(root)


def test_scan_checks_head_and_guard_before_any_project_import(tmp_path, monkeypatch):
    order = []
    monkeypatch.setattr(topo, 'pinned_geometry', lambda: order.append('import') or True)
    monkeypatch.setattr(topo, 'amendment_reference', lambda p: order.append('amendment') or {})

    def refuse(step):
        def fail(*a):
            order.append(step)
            raise ValueError('synthetic ' + step + ' refusal')
        return fail
    opened = []
    for git, guard, expected in ((refuse('head'), lambda: order.append('guard'), ['head']),
                                 (lambda h: order.append('head') or h, refuse('guard'), ['head', 'guard'])):
        order.clear()
        with pytest.raises(ValueError, match='synthetic'):
            topo.scan(tmp_path / 'amendment.json', 'a' * 40, project=tmp_path, opener=opened.append,
                      envelope=lambda: {}, git=git, guard=guard)
        assert order == expected
    assert opened == [] and not (tmp_path / 'outputs').exists()


def test_plan_runs_the_guard_before_any_project_import(tmp_path, monkeypatch):
    order = []
    monkeypatch.setattr(topo, 'pinned_geometry', lambda: order.append('import') or True)

    def refuse(root=None):
        order.append('guard')
        raise ValueError('synthetic guard refusal')
    with pytest.raises(ValueError, match='synthetic guard'):
        topo.plan(tmp_path / 'amendment.json', project=tmp_path, guard=refuse)
    assert order == ['guard']


def test_attempt_claim_is_atomic_durable_and_never_reused(tmp_path):
    out = tmp_path / 'outputs' / topo.OUTPUT_NAME
    claim = topo.claim_attempt(out, dict(run_tag=topo.RUN_TAG))
    raw = (out / topo.CLAIM_NAME).read_bytes()
    assert claim == dict(name=topo.CLAIM_NAME, sha256=topo.digest(raw), bytes=len(raw))
    doc = json.loads(raw)
    assert doc['status'] == 'ATTEMPT_CLAIMED_SOLE_OPEN_CONSUMED' and doc['refund'] is False and doc['retry'] is False
    # A racer that passed the absence check still loses at the atomic mkdir.
    with pytest.raises(ValueError, match='already claimed'):
        topo.claim_attempt(out, dict(run_tag=topo.RUN_TAG))
    assert (out / topo.CLAIM_NAME).read_bytes() == raw
    # A failure record never replaces the claim, and only one is kept.
    assert topo.record_failure(out, 'read', OSError('x' * 5000)) == out / topo.FAILURE_NAME
    failure = json.loads((out / topo.FAILURE_NAME).read_text())
    assert failure['phase'] == 'read' and len(failure['error']) == topo.FAILURE_MESSAGE_CHARS
    assert topo.record_failure(out, 'receipt', OSError('again')) is None
    assert sorted(p.name for p in out.iterdir()) == [topo.CLAIM_NAME, topo.FAILURE_NAME]
    with pytest.raises(ValueError, match='bounded reservation'):
        topo.claim_attempt(tmp_path / 'big', dict(blob='x' * topo.CLAIM_MAX_BYTES))
    assert not (tmp_path / 'big').exists()
    linked = tmp_path / 'linked-outputs'
    linked.symlink_to(tmp_path / 'outputs')
    with pytest.raises(ValueError, match='symlink'):
        topo.claim_attempt(linked / 'x', {})


def test_receipt_is_bounded_and_never_overwritten(tmp_path):
    out = tmp_path / 'outputs' / topo.OUTPUT_NAME
    with pytest.raises(ValueError, match='claimed attempt'):
        topo.write_receipt(out, dict(schema=topo.SCHEMA))
    assert not out.exists()
    claim = topo.claim_attempt(out, {})
    path, sha, size = topo.write_receipt(out, dict(schema=topo.SCHEMA), claimed_bytes=claim['bytes'])
    assert path.read_bytes() == topo.encoded(dict(schema=topo.SCHEMA)) and size == len(path.read_bytes())
    with pytest.raises(FileExistsError):
        topo.write_receipt(out, dict(schema=topo.SCHEMA))
    other = tmp_path / 'other'
    topo.claim_attempt(other, {})
    # The whole output root (claim + failure reserve + receipt) stays inside 1 MiB.
    with pytest.raises(ValueError, match='1 MiB'):
        topo.write_receipt(other, dict(blob='x' * (topo.RECEIPT_MAX_BYTES - topo.FAILURE_MAX_BYTES)),
                           claimed_bytes=1)
    assert not (other / topo.RECEIPT_NAME).exists()


def test_script_is_source_free_except_the_scan_path():
    text = (ROOT / 'research/scripts/coastal_four128_mask_topology.py').read_text()
    assert 'import h5py' not in text and 'hashlib.sha256(Path' not in text and 'urllib' not in text
    assert text.count('open_source(') == 2  # the definition and the single call in scan()
