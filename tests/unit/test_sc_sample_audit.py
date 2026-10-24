"""SC-SAMPLE-AUDIT: read-only composition report for a fixed coast-sample-v1 sample.

Offline synthetic fixtures only. Tests are plain functions (no pytest import) so the
staged acceptance runner can execute them in-process with the installed python3; pytest
collects them normally through pyproject testpaths/python_files. Test names carry the
acceptance row: test_a1_* focused, test_a2_* producer contract, test_a3_* negative.
"""
import contextlib
import copy
import hashlib
import io
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / 'tests' / 'fixtures' / 'sc_sample_audit'
PRODUCER_PATH = ROOT / 'skills' / 'coast-campaign-shared' / 'scripts' / 'coast_sample.py'
AUDIT_PATH = ROOT / 'scripts' / 'coast_diagnostics' / 'sample_coverage.py'


def _load(name, path):
    # Explicit file loads: skills/ and scripts/ are not product packages; no sys.path edits.
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        sys.modules.pop(name, None)
        raise
    return module


RUNNER_PATH = ROOT / 'scripts' / 'accept_sc_sample_audit.py'

producer = _load('_sc_sample_audit_test_producer', PRODUCER_PATH)
audit = _load('sc_sample_audit_sample_coverage', AUDIT_PATH)
runner = _load('_sc_sample_audit_runner_under_test', RUNNER_PATH)


@contextlib.contextmanager
def real_tmpdir():
    """Temporary directory addressed by its physical path (macOS /var and /tmp are links)."""
    with tempfile.TemporaryDirectory(prefix='sc-sample-audit-') as tmp:
        yield Path(os.path.realpath(tmp))


class RecordingOs:
    """In-memory double for the audit module's os: records every open/lstat path."""

    def __init__(self):
        self.opened, self.lstated = [], []

    def __getattr__(self, name):
        return getattr(os, name)

    def open(self, path, *args, **kwargs):
        self.opened.append(os.fspath(path))
        return os.open(path, *args, **kwargs)

    def lstat(self, path, *args, **kwargs):
        self.lstated.append(os.fspath(path))
        return os.lstat(path, *args, **kwargs)


@contextlib.contextmanager
def recording_os():
    double = RecordingOs()
    original = audit.os
    audit.os = double
    try:
        yield double
    finally:
        audit.os = original


def raises_refused(reason, fn, *args, **kwargs):
    try:
        fn(*args, **kwargs)
    except audit.SampleAuditRefused as error:
        assert error.reason == reason, (error.reason, reason, str(error))
        return error
    raise AssertionError('expected SampleAuditRefused(%s)' % reason)


def tree_snapshot(path):
    """Every entry below path, never following symlinks."""
    entries = []
    for current, dirs, files in os.walk(path, followlinks=False):
        for name in dirs + files:
            entries.append(os.path.relpath(os.path.join(current, name), path))
    return sorted(entries)

GROUP_FIELDS = ('map_done', 'eligible', 'selected', 'eligible_unselected', 'ineligible')
REPORT_FIELDS = {
    'report_version', 'method_version', 'verdict', 'warning', 'input_sha256', 'bindings',
    'sample', 'populations', 'totals', 'groups',
}


def h(label):
    return hashlib.sha256(label.encode()).hexdigest()


PLAN = h('sc-sample-audit-test-plan')
BRIDGE = h('sc-sample-audit-test-bridge')


def raises_invalid(reason, fn, *args, **kwargs):
    try:
        fn(*args, **kwargs)
    except audit.SampleAuditInvalid as error:
        assert error.reason == reason, (error.reason, reason, str(error))
        return error
    raise AssertionError('expected SampleAuditInvalid(%s)' % reason)


def focused_fixture():
    return json.loads((FIXTURES / 'focused_population.json').read_text(encoding='utf-8'))


def populations(layout):
    done, eligible = [], []
    for row in layout:
        for index in range(row['map_done']):
            key = producer.window_key(row['source_id'], row['grid_sha256'], index)
            done.append(key)
            if index < row['eligible']:
                eligible.append(key)
    return done, eligible


def focused_document():
    fixture = focused_fixture()
    done, eligible = populations(fixture['layout'])
    document = producer.sample(done, eligible, plan_sha256=fixture['plan_sha256'],
                               bridge_sha256=fixture['bridge_sha256'])
    return fixture, document


def assert_report_complete(report, document):
    """Independent completeness assertion: every input key in exactly one group/population."""
    groups = report['groups']
    seen = {}
    for field in GROUP_FIELDS:
        seen[field] = []
    for row in groups:
        assert set(row) == {'source_id', 'grid_sha256'} | set(GROUP_FIELDS) | {f + '_count' for f in GROUP_FIELDS}
        for field in GROUP_FIELDS:
            assert row[field] == sorted(row[field])
            assert row[field + '_count'] == len(row[field])
            for key in row[field]:
                source_id, grid, _ = key.rsplit('#', 2)
                assert (source_id, grid) == (row['source_id'], row['grid_sha256'])
            seen[field].extend(row[field])
        assert row['map_done_count'] == row['eligible_count'] + row['ineligible_count']
        assert row['eligible_count'] == row['selected_count'] + row['eligible_unselected_count']
    pairs = [(row['source_id'], row['grid_sha256']) for row in groups]
    assert pairs == sorted(set(pairs)), 'groups must be unique and sorted'
    assert sorted(seen['map_done']) == document['map_done'], 'report incomplete: map_done'
    assert sorted(seen['eligible']) == document['eligible'], 'report incomplete: eligible'
    assert sorted(seen['selected']) == document['selected'], 'report incomplete: selected'
    expected_pairs = sorted({tuple(k.rsplit('#', 2)[:2]) for k in document['map_done']})
    assert pairs == expected_pairs, 'report incomplete: groups'
    totals = report['totals']
    for field in GROUP_FIELDS:
        assert totals[field] == len(seen[field])
    assert totals['groups'] == len(groups)


# ---------------------------------------------------------------- A1 focused


def test_a1_fixture_counts_match_hand_recorded_expectations():
    fixture, document = focused_document()
    report = audit.audit_sample(document, fixture['plan_sha256'], fixture['bridge_sha256'])
    expected = fixture['expected']
    assert report['sample']['target'] == expected['target']
    assert report['sample']['size'] == expected['size']
    got = [{k: row[k] for k in expected['groups'][0]} for row in report['groups']]
    assert got == expected['groups']
    assert report['totals'] == expected['totals']
    assert_report_complete(report, document)


def test_a1_zero_selected_group_visible():
    fixture, document = focused_document()
    report = audit.audit_sample(document, fixture['plan_sha256'], fixture['bridge_sha256'])
    beta = [row for row in report['groups'] if row['source_id'] == 'beta']
    assert len(beta) == 1, 'eligible-but-unselected source must not be omitted'
    assert beta[0]['eligible_count'] == 2 and beta[0]['selected_count'] == 0
    assert beta[0]['selected'] == [] and beta[0]['eligible_unselected_count'] == 2


def test_a1_no_eligible_group_stays_visible_as_ineligible():
    fixture, document = focused_document()
    report = audit.audit_sample(document, fixture['plan_sha256'], fixture['bridge_sha256'])
    gamma = [row for row in report['groups'] if row['source_id'] == 'gamma']
    assert len(gamma) == 1
    assert gamma[0]['eligible_count'] == 0 and gamma[0]['ineligible_count'] == 2
    assert gamma[0]['ineligible'] == gamma[0]['map_done']


def test_a1_selected_list_preserved_and_totals_reconcile():
    fixture, document = focused_document()
    original = copy.deepcopy(document)
    report = audit.audit_sample(document, fixture['plan_sha256'], fixture['bridge_sha256'])
    assert document == original, 'input document must not be mutated'
    assert report['sample']['selected'] == original['selected']
    assert json.dumps(report['sample']['selected']) == json.dumps(original['selected'])
    assert report['totals']['selected'] == original['size'] == len(original['selected'])
    assert report['totals']['map_done'] == len(original['map_done'])
    assert report['totals']['eligible'] == len(original['eligible'])
    assert report['totals']['eligible_unselected'] + report['totals']['selected'] == report['totals']['eligible']
    assert report['totals']['ineligible'] + report['totals']['eligible'] == report['totals']['map_done']
    assert_report_complete(report, original)


def test_a1_report_is_complete():
    fixture, document = focused_document()
    report = audit.audit_sample(document, fixture['plan_sha256'], fixture['bridge_sha256'])
    assert_report_complete(report, document)


def test_a1_empty_populations_zero_counts_no_invented_eligibility():
    document = producer.sample([], [], plan_sha256=PLAN, bridge_sha256=BRIDGE)
    report = audit.audit_sample(document, PLAN, BRIDGE)
    assert report['groups'] == []
    assert report['populations'] == {'map_done': 'EMPTY', 'eligible': 'EMPTY', 'selected': 'EMPTY'}
    assert set(report['totals'].values()) == {0}
    grid = h('grid-empty-eligible')
    done = [producer.window_key('solo', grid, i) for i in range(3)]
    document = producer.sample(done, [], plan_sha256=PLAN, bridge_sha256=BRIDGE)
    report = audit.audit_sample(document, PLAN, BRIDGE)
    assert report['populations'] == {'map_done': 'PRESENT', 'eligible': 'EMPTY', 'selected': 'EMPTY'}
    assert len(report['groups']) == 1
    row = report['groups'][0]
    assert row['eligible_count'] == 0 and row['selected_count'] == 0 and row['ineligible_count'] == 3
    assert_report_complete(report, document)


def test_a1_absent_population_is_not_empty_population():
    document = producer.sample([], [], plan_sha256=PLAN, bridge_sha256=BRIDGE)
    absent = dict(document)
    del absent['eligible']
    raises_invalid('missing_field', audit.audit_sample, absent, PLAN, BRIDGE)


def test_a1_bad_seed_plan_bridge_or_membership_invalid():
    fixture, document = focused_document()
    plan, bridge = fixture['plan_sha256'], fixture['bridge_sha256']
    raises_invalid('seed_mismatch', audit.audit_sample, dict(document, seed=h('other-seed')), plan, bridge)
    raises_invalid('seed_mismatch', audit.audit_sample, document, h('other-plan'), bridge)
    raises_invalid('seed_mismatch', audit.audit_sample, document, plan, h('other-bridge'))
    raises_invalid('invalid_binding', audit.audit_sample, document, plan.upper(), bridge)
    raises_invalid('invalid_binding', audit.audit_sample, document, plan, bridge[:-1])
    unselected = sorted(set(document['eligible']) - set(document['selected']))[0]
    swapped = sorted(document['selected'][1:] + [unselected])
    raises_invalid('selected_mismatch', audit.audit_sample, dict(document, selected=swapped), plan, bridge)
    ineligible = sorted(set(document['map_done']) - set(document['eligible']))[0]
    forged = sorted(document['selected'][1:] + [ineligible])
    raises_invalid('selected_not_eligible', audit.audit_sample, dict(document, selected=forged), plan, bridge)


def test_a1_report_carries_input_hash_warning_and_no_authority():
    fixture, document = focused_document()
    report = audit.audit_sample(document, fixture['plan_sha256'], fixture['bridge_sha256'])
    assert set(report) == REPORT_FIELDS
    canonical = json.dumps(document, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
    assert report['input_sha256'] == hashlib.sha256(canonical).hexdigest()
    assert report['bindings'] == {'plan_sha256': fixture['plan_sha256'],
                                  'bridge_sha256': fixture['bridge_sha256'], 'seed': document['seed']}
    for phrase in ('not source quality', 'coverage', 'eligibility proof', 'scientific acceptance'):
        assert phrase in report['warning']
    assert report['verdict'] == 'COMPOSITION_REPORTED_REVIEW_REQUIRED'
    text = json.dumps(report).lower()
    for word in ('approved', 'admitted', '"hold', 'quota', 'resample'):
        assert word not in text


# ---------------------------------------------------------------- A2 producer contract


def _grid(label):
    return h('sc-sample-audit-contract-' + label)


def _layout_doc(layout, plan=PLAN, bridge=BRIDGE, order=None):
    done, eligible = populations(layout)
    if order is not None:
        done, eligible = order(done), order(eligible)
    return producer.sample(done, eligible, plan_sha256=plan, bridge_sha256=bridge)


def test_a2_sizes_below_at_and_above_clamped_target():
    cases = {
        'below': [{'source_id': 's', 'grid_sha256': _grid('a'), 'map_done': 10, 'eligible': 5}],
        'at': [{'source_id': 's', 'grid_sha256': _grid('a'), 'map_done': 10, 'eligible': 8}],
        'above': [{'source_id': 's', 'grid_sha256': _grid('a'), 'map_done': 10, 'eligible': 10}],
        'scaled': [{'source_id': 's', 'grid_sha256': _grid('a'), 'map_done': 70, 'eligible': 40},
                   {'source_id': 't', 'grid_sha256': _grid('b'), 'map_done': 30, 'eligible': 2}],
    }
    expected = {'below': (8, 5), 'at': (8, 8), 'above': (8, 8), 'scaled': (13, 13)}
    for name, layout in cases.items():
        document = _layout_doc(layout)
        assert (document['target'], document['size']) == expected[name], name
        report = audit.audit_sample(document, PLAN, BRIDGE)
        assert (report['sample']['target'], report['sample']['size']) == expected[name]
        assert report['totals']['selected'] == expected[name][1]
        assert_report_complete(report, document)


def test_a2_multiple_grids_for_one_source_are_separate_groups():
    layout = [{'source_id': 'multi', 'grid_sha256': _grid(str(i)), 'map_done': 3, 'eligible': 2}
              for i in range(5)]
    document = _layout_doc(layout)
    report = audit.audit_sample(document, PLAN, BRIDGE)
    assert len(report['groups']) == 5
    assert {row['source_id'] for row in report['groups']} == {'multi'}
    assert sorted(row['grid_sha256'] for row in report['groups']) == sorted(_grid(str(i)) for i in range(5))
    assert_report_complete(report, document)


def test_a2_source_ids_containing_separator_decode_by_last_two():
    layout = [
        {'source_id': 'noaa#ncei', 'grid_sha256': _grid('x'), 'map_done': 6, 'eligible': 4},
        {'source_id': 'noaa', 'grid_sha256': _grid('x'), 'map_done': 6, 'eligible': 4},
        {'source_id': '#lead#', 'grid_sha256': _grid('y'), 'map_done': 3, 'eligible': 3},
    ]
    document = _layout_doc(layout)
    report = audit.audit_sample(document, PLAN, BRIDGE)
    pairs = {(row['source_id'], row['grid_sha256']) for row in report['groups']}
    assert pairs == {('noaa#ncei', _grid('x')), ('noaa', _grid('x')), ('#lead#', _grid('y'))}
    for row in report['groups']:
        assert row['map_done_count'] == {'noaa#ncei': 6, 'noaa': 6, '#lead#': 3}[row['source_id']]
    assert_report_complete(report, document)


def test_a2_reordered_input_populations_give_identical_report_bytes():
    layout = [
        {'source_id': 'a', 'grid_sha256': _grid('1'), 'map_done': 9, 'eligible': 6},
        {'source_id': 'b', 'grid_sha256': _grid('2'), 'map_done': 7, 'eligible': 3},
        {'source_id': 'c', 'grid_sha256': _grid('3'), 'map_done': 4, 'eligible': 0},
    ]
    orders = [None, lambda xs: list(reversed(xs)), lambda xs: xs[5:] + xs[:5],
              lambda xs: sorted(xs, key=lambda k: h(k))]
    outputs = set()
    for order in orders:
        document = _layout_doc(layout, order=order)
        report = audit.audit_sample(document, PLAN, BRIDGE)
        outputs.add(audit.serialize_report(report))
    assert len(outputs) == 1


def test_a2_producer_unchanged_and_used_for_recompute():
    # Audit recompute must be the producer's own function, not a re-implementation.
    assert audit.producer_sample_function().__code__ is producer.sample.__code__ or \
        audit.producer_sample_function().__code__.co_code == producer.sample.__code__.co_code
    assert audit.PRODUCER_PATH.resolve() == PRODUCER_PATH.resolve()


def test_a2_cli_round_trip_writes_deterministic_report():
    fixture, document = focused_document()
    with real_tmpdir() as tmp:
        sample_path = tmp / 'sample.json'
        sample_path.write_text(json.dumps(document), encoding='utf-8')
        outs = []
        for name in ('one.json', 'two.json'):
            out = Path(tmp) / name
            status = audit.main(['--sample', str(sample_path), '--plan-sha256', fixture['plan_sha256'],
                                 '--bridge-sha256', fixture['bridge_sha256'], '--out', str(out)])
            assert status == 0
            outs.append(out.read_bytes())
        assert outs[0] == outs[1]
        report = json.loads(outs[0])
        assert report['input_sha256'] == audit.audit_sample(document, fixture['plan_sha256'],
                                                            fixture['bridge_sha256'])['input_sha256']
        assert report['groups'] == audit.audit_sample(document, fixture['plan_sha256'],
                                                      fixture['bridge_sha256'])['groups']


# ---------------------------------------------------------------- A3 negative and preservation


def test_a3_duplicate_keys_invalid():
    fixture, document = focused_document()
    plan, bridge = fixture['plan_sha256'], fixture['bridge_sha256']
    for field in ('map_done', 'eligible', 'selected'):
        values = sorted(document[field] + [document[field][0]])
        raises_invalid('duplicate_key', audit.audit_sample, dict(document, **{field: values}), plan, bridge)


def test_a3_forged_selected_key_invalid():
    fixture, document = focused_document()
    plan, bridge = fixture['plan_sha256'], fixture['bridge_sha256']
    source, grid, index = document['selected'][0].rsplit('#', 2)
    forged_key = producer.window_key(source, grid, 999)
    forged = sorted(document['selected'][1:] + [forged_key])
    raises_invalid('selected_not_eligible', audit.audit_sample, dict(document, selected=forged), plan, bridge)
    raises_invalid('size_mismatch', audit.audit_sample, dict(document, selected=document['selected'][1:]), plan, bridge)
    unsorted = list(reversed(document['selected']))
    raises_invalid('not_canonical_order', audit.audit_sample, dict(document, selected=unsorted), plan, bridge)


def test_a3_wrong_method_seed_target_invalid():
    fixture, document = focused_document()
    plan, bridge = fixture['plan_sha256'], fixture['bridge_sha256']
    raises_invalid('method_mismatch', audit.audit_sample, dict(document, method_version='coast-sample-v2'), plan, bridge)
    raises_invalid('seed_mismatch', audit.audit_sample, dict(document, seed=h('x')), plan, bridge)
    raises_invalid('bad_type', audit.audit_sample, dict(document, seed=7), plan, bridge)
    raises_invalid('target_mismatch', audit.audit_sample, dict(document, target=9), plan, bridge)
    raises_invalid('bad_type', audit.audit_sample, dict(document, target=True), plan, bridge)
    raises_invalid('bad_type', audit.audit_sample, dict(document, size=8.0), plan, bridge)


def test_a3_malformed_grid_hash_or_index_invalid():
    grid = h('malformed')
    bad_keys = [
        'src#' + grid.upper() + '#0', 'src#' + grid[:-1] + '#0', 'src#' + grid + 'a#0',
        'src#' + grid + '#01', 'src#' + grid + '#-1', 'src#' + grid + '#+1', 'src#' + grid + '#',
        'src#' + grid + '#x', 'src#' + grid + '#\u0661', 'src#' + grid + '# 1', '#' + grid + '#0',
        grid + '#0', 'no-separators', '',
    ]
    for key in bad_keys:
        document = {'method_version': 'coast-sample-v1', 'seed': h(PLAN + ':' + BRIDGE),
                    'target': 8, 'size': 0, 'map_done': [key], 'eligible': [], 'selected': []}
        raises_invalid('malformed_key', audit.audit_sample, document, PLAN, BRIDGE)
    raises_invalid('bad_type', audit.audit_sample, {'method_version': 'coast-sample-v1', 'seed': '',
                   'target': 8, 'size': 0, 'map_done': [3], 'eligible': [], 'selected': []}, PLAN, BRIDGE)


def test_a3_missing_or_extra_population_invalid():
    fixture, document = focused_document()
    plan, bridge = fixture['plan_sha256'], fixture['bridge_sha256']
    for field in ('method_version', 'seed', 'target', 'size', 'map_done', 'eligible', 'selected'):
        broken = dict(document)
        del broken[field]
        raises_invalid('missing_field', audit.audit_sample, broken, plan, bridge)
    raises_invalid('unexpected_field', audit.audit_sample, dict(document, admission='granted'), plan, bridge)
    raises_invalid('bad_type', audit.audit_sample, dict(document, eligible=None), plan, bridge)
    raises_invalid('bad_type', audit.audit_sample, [document], plan, bridge)


def test_a3_source_mismatch_invalid():
    fixture, document = focused_document()
    plan, bridge = fixture['plan_sha256'], fixture['bridge_sha256']
    source, grid, index = document['selected'][0].rsplit('#', 2)
    moved = producer.window_key('gamma', grid, int(index))  # same grid/index, different source
    forged = sorted(document['selected'][1:] + [moved])
    raises_invalid('selected_not_eligible', audit.audit_sample, dict(document, selected=forged), plan, bridge)
    outsider = producer.window_key('zeta', grid, 0)
    raises_invalid('eligible_not_in_map_done', audit.audit_sample,
                   dict(document, eligible=sorted(document['eligible'] + [outsider])), plan, bridge)


def test_a3_excessive_input_size_invalid():
    grid = h('big')
    done = [producer.window_key('big', grid, i) for i in range(audit.MAX_ROWS + 1)]
    document = {'method_version': 'coast-sample-v1', 'seed': '', 'target': 0, 'size': 0,
                'map_done': sorted(done), 'eligible': [], 'selected': []}
    raises_invalid('row_cap_exceeded', audit.audit_sample, document, PLAN, BRIDGE)
    at_cap = producer.sample(done[:audit.MAX_ROWS], [], plan_sha256=PLAN, bridge_sha256=BRIDGE)
    assert audit.audit_sample(at_cap, PLAN, BRIDGE)['totals']['map_done'] == audit.MAX_ROWS
    huge = {'method_version': 'coast-sample-v1', 'seed': 'x' * (audit.MAX_FILE_BYTES + 1), 'target': 8,
            'size': 0, 'map_done': [], 'eligible': [], 'selected': []}
    raises_invalid('input_too_large', audit.audit_sample, huge, PLAN, BRIDGE)


def _cli(tmp, document_bytes, out_name='report.json', plan=PLAN, bridge=BRIDGE):
    sample_path = Path(tmp) / 'sample.json'
    if document_bytes is not None:
        sample_path.write_bytes(document_bytes)
    out = Path(tmp) / out_name
    status = audit.main(['--sample', str(sample_path), '--plan-sha256', plan,
                         '--bridge-sha256', bridge, '--out', str(out)])
    return status, sample_path, out


def test_a3_cli_refusals_preserve_inputs_and_outputs():
    fixture, document = focused_document()
    plan, bridge = fixture['plan_sha256'], fixture['bridge_sha256']
    good = json.dumps(document).encode()
    with real_tmpdir() as tmp:
        # INVALID content: exit 3, input unchanged, no output.
        bad = json.dumps(dict(document, seed=h('x'))).encode()
        status, sample_path, out = _cli(tmp, bad, plan=plan, bridge=bridge)
        assert status == audit.EXIT_INVALID == 3
        assert sample_path.read_bytes() == bad and not out.exists()
        # Oversized file refused before parsing: exit 4.
        status, sample_path, out = _cli(tmp, b' ' * (audit.MAX_FILE_BYTES + 1), plan=plan, bridge=bridge)
        assert status == audit.EXIT_REFUSED == 4 and not out.exists()
        # NaN and duplicate object keys refused.
        for raw in (b'{"seed": NaN}', b'{"seed": "a", "seed": "b"}', b'not json'):
            status, _, out = _cli(tmp, raw, plan=plan, bridge=bridge)
            assert status == audit.EXIT_INVALID and not out.exists()
        # Existing output is never overwritten.
        status, sample_path, out = _cli(tmp, good, out_name='keep.json', plan=plan, bridge=bridge)
        assert status == 0
        before = out.read_bytes()
        status, _, out = _cli(tmp, good, out_name='keep.json', plan=plan, bridge=bridge)
        assert status == audit.EXIT_REFUSED and out.read_bytes() == before
        # Symlinked input and symlinked output parent refused.
        link = Path(tmp) / 'link.json'
        os.symlink(sample_path, link)
        status = audit.main(['--sample', str(link), '--plan-sha256', plan, '--bridge-sha256', bridge,
                             '--out', str(Path(tmp) / 'via-link.json')])
        assert status == audit.EXIT_REFUSED and not (Path(tmp) / 'via-link.json').exists()
        real_dir = Path(tmp) / 'real'
        real_dir.mkdir()
        os.symlink(real_dir, Path(tmp) / 'dirlink')
        status = audit.main(['--sample', str(sample_path), '--plan-sha256', plan, '--bridge-sha256', bridge,
                             '--out', str(Path(tmp) / 'dirlink' / 'r.json')])
        assert status == audit.EXIT_REFUSED and list(real_dir.iterdir()) == []
        # Special file (directory as input) refused; missing input refused.
        status = audit.main(['--sample', str(real_dir), '--plan-sha256', plan, '--bridge-sha256', bridge,
                             '--out', str(Path(tmp) / 'dir-in.json')])
        assert status == audit.EXIT_REFUSED
        status = audit.main(['--sample', str(Path(tmp) / 'absent.json'), '--plan-sha256', plan,
                             '--bridge-sha256', bridge, '--out', str(Path(tmp) / 'absent-out.json')])
        assert status == audit.EXIT_REFUSED
        assert sample_path.read_bytes() == good


def test_a3_fixture_bytes_unchanged_by_runs():
    path = FIXTURES / 'focused_population.json'
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    fixture, document = focused_document()
    audit.audit_sample(document, fixture['plan_sha256'], fixture['bridge_sha256'])
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before


def test_a3_exact_reproducibility():
    fixture, document = focused_document()
    first = audit.serialize_report(audit.audit_sample(document, fixture['plan_sha256'], fixture['bridge_sha256']))
    second = audit.serialize_report(audit.audit_sample(copy.deepcopy(document), fixture['plan_sha256'],
                                                       fixture['bridge_sha256']))
    assert first == second
    assert first.endswith(b'\n') and b'NaN' not in first and b'Infinity' not in first


def test_a3_serializer_rejects_nonfinite_and_oversize():
    try:
        audit.serialize_report({'x': float('nan')})
    except audit.SampleAuditInvalid as error:
        assert error.reason == 'nonfinite_output'
    else:
        raise AssertionError('nonfinite output must be refused')
    try:
        audit.serialize_report({'x': 'y' * (audit.MAX_OUTPUT_BYTES + 1)})
    except audit.SampleAuditInvalid as error:
        assert error.reason == 'output_too_large'
    else:
        raise AssertionError('oversize output must be refused')


def _link_layout(tmp):
    """tmp/{sample.json, link -> far/target, far/sample.json, far/target/sample.json}."""
    _, document = focused_document()
    data = json.dumps(document).encode()
    far = tmp / 'far'
    target = far / 'target'
    target.mkdir(parents=True)
    for path in (tmp / 'sample.json', far / 'sample.json', target / 'sample.json'):
        path.write_bytes(data)
    os.symlink(target, tmp / 'link')
    return data, far, target


def test_a3_input_symlink_ancestry_refused_before_any_open():
    with real_tmpdir() as tmp:
        data, far, target = _link_layout(tmp)
        before = tree_snapshot(tmp)
        cases = [
            ('symlink_refused', tmp / 'link' / 'sample.json'),             # intermediate link
            ('dotdot_refused', str(tmp / 'link') + '/../sample.json'),     # link plus ..
            ('dotdot_refused', str(tmp / 'far') + '/../sample.json'),      # plain .. also refused
            ('symlink_refused', tmp / 'link'),                             # leaf link (directory)
        ]
        leaf = tmp / 'leaf.json'
        os.symlink(tmp / 'sample.json', leaf)
        cases.append(('symlink_refused', leaf))                           # leaf link (file)
        for reason, path in cases:
            with recording_os() as double:
                raises_refused(reason, audit.read_bounded, path)
            assert double.opened == [], (path, double.opened)
            assert not any(p.startswith(str(tmp / 'link') + os.sep) for p in double.lstated), double.lstated
            assert not any(p.startswith(str(target)) for p in double.lstated), double.lstated
        assert tree_snapshot(tmp) == sorted(before + ['leaf.json'])
        # Positive control: the same bytes read through an ordinary real path.
        assert audit.read_bounded(tmp / 'sample.json') == data
        assert audit.read_bounded(str(tmp) + '/./sample.json') == data


def test_a3_output_symlink_ancestry_refused_before_any_creation():
    with real_tmpdir() as tmp:
        _link_layout(tmp)
        before_target = tree_snapshot(tmp / 'far')
        cases = [
            ('symlink_refused', tmp / 'link' / 'r.json'),
            ('dotdot_refused', str(tmp / 'link') + '/../r.json'),
            ('dotdot_refused', str(tmp) + '/../r.json'),
            ('symlink_refused', tmp / 'link'),
        ]
        for reason, path in cases:
            with recording_os() as double:
                raises_refused(reason, audit.write_new, path, b'{}\n')
            assert double.opened == [], (path, double.opened)
        assert tree_snapshot(tmp / 'far') == before_target
        assert not (tmp / 'r.json').exists() and not (tmp.parent / 'r.json').exists()
        assert not (tmp / 'far' / 'r.json').exists()
        assert audit.write_new(tmp / 'ok.json', b'{}\n') == tmp / 'ok.json'


def test_a3_cli_symlink_plus_dotdot_paths_exit_refused():
    fixture, _ = focused_document()
    plan, bridge = fixture['plan_sha256'], fixture['bridge_sha256']
    with real_tmpdir() as tmp:
        data, far, target = _link_layout(tmp)
        before = tree_snapshot(tmp)
        argv_in = ['--sample', str(tmp / 'link') + '/../sample.json', '--plan-sha256', plan,
                   '--bridge-sha256', bridge, '--out', str(tmp / 'in.json')]
        argv_out = ['--sample', str(tmp / 'sample.json'), '--plan-sha256', plan,
                    '--bridge-sha256', bridge, '--out', str(tmp / 'link') + '/../out.json']
        for argv in (argv_in, argv_out):
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                status = audit.main(argv)
            assert status == audit.EXIT_REFUSED, (argv, err.getvalue())
            assert err.getvalue().startswith('REFUSED ') and 'Traceback' not in err.getvalue()
        assert tree_snapshot(tmp) == before
        for path in (tmp / 'sample.json', far / 'sample.json', target / 'sample.json'):
            assert path.read_bytes() == data


def test_a3_runner_run_dir_refuses_symlinked_or_dotdot_ancestry():
    with real_tmpdir() as tmp:
        far = tmp / 'far'
        target = far / 'target'
        target.mkdir(parents=True)
        os.symlink(target, tmp / 'link')
        before = tree_snapshot(tmp)
        for output in (tmp / 'link' / 'runner-root', tmp / 'link',
                       str(tmp / 'link') + '/../root2', str(tmp) + '/../root3',
                       tmp / 'link' / 'a' / 'b'):
            try:
                runner.make_run_dir(output)
            except SystemExit as error:
                assert str(error).startswith('REFUSED '), str(error)
            else:
                raise AssertionError('runner must refuse %s' % output)
        assert tree_snapshot(tmp) == before, 'nothing may be created behind a refused path'
        assert list(target.iterdir()) == [] and not (far / 'root2').exists()
        assert not (tmp.parent / 'root3').exists()
        # Ordinary real-directory first run and re-run give distinct write-once directories.
        first = runner.make_run_dir(tmp / 'out' / 'nested')
        second = runner.make_run_dir(tmp / 'out' / 'nested')
        assert first != second and first.parent == second.parent == tmp / 'out' / 'nested'
        assert (first / 'tmp').is_dir() and (second / 'tmp').is_dir()
        assert not first.is_symlink() and not second.is_symlink()


def _numeric_document(target_literal):
    _, document = focused_document()
    text = json.dumps(dict(document, target=123456789))
    assert text.count('123456789') == 1
    return text.replace('123456789', target_literal).encode()


def test_a3_cli_overlimit_or_nonfinite_numbers_invalid_without_traceback():
    fixture, document = focused_document()
    plan, bridge = fixture['plan_sha256'], fixture['bridge_sha256']
    digits_limit = sys.get_int_max_str_digits() if hasattr(sys, 'get_int_max_str_digits') else None
    with real_tmpdir() as tmp:
        existing = tmp / 'existing.json'
        existing.write_bytes(b'prior report\n')
        literals = ['9' * 5000, '-' + '9' * 5000, '1e999', '-1e999', '1' + '0' * 400 + '.5', '8.0', '8e0']
        for index, literal in enumerate(literals):
            raw = _numeric_document(literal)
            assert len(raw) < audit.MAX_FILE_BYTES
            sample = tmp / ('num-%d.json' % index)
            sample.write_bytes(raw)
            for out in (existing, tmp / ('fresh-%d.json' % index)):
                err = io.StringIO()
                with contextlib.redirect_stderr(err):
                    status = audit.main(['--sample', str(sample), '--plan-sha256', plan,
                                         '--bridge-sha256', bridge, '--out', str(out)])
                assert status == audit.EXIT_INVALID == 3, (literal[:20], status, err.getvalue()[:300])
                assert err.getvalue().startswith('INVALID ') and 'Traceback' not in err.getvalue()
            assert sample.read_bytes() == raw
            assert existing.read_bytes() == b'prior report\n'
            assert not (tmp / ('fresh-%d.json' % index)).exists()
        # Valid-number positive control through the same path.
        good = tmp / 'good.json'
        good.write_bytes(_numeric_document(str(document['target'])))
        assert audit.main(['--sample', str(good), '--plan-sha256', plan, '--bridge-sha256', bridge,
                           '--out', str(tmp / 'good-report.json')]) == audit.EXIT_OK
        assert json.loads((tmp / 'good-report.json').read_bytes())['sample']['target'] == document['target']
    if digits_limit is not None:
        assert sys.get_int_max_str_digits() == digits_limit, 'global int limit must not change'


def test_a3_api_overlimit_integer_invalid():
    fixture, document = focused_document()
    raises_invalid('bad_type', audit.audit_sample, dict(document, target=10 ** 5000),
                   fixture['plan_sha256'], fixture['bridge_sha256'])
    raises_invalid('bad_json', audit._parse_json, b'{"target": ' + b'7' * 5000 + b'}')
