"""U2 canonical adapter: real admission graph, genuine rasters, labelled fake inference.

The GIS marker covers the materialized producer admission (pyproj/shapely) and
GeoTIFF derivation. No endpoint or Store is opened; U5 owns driver integration.
Inherited factory/algorithms retain their baseline authorship; new tests are Astra.
"""
import copy
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import urllib.error

import pytest

from tests._support import ROOT
from tests.coast_contract_factory import materialize, load_helper, THRESHOLDS

pytestmark = pytest.mark.gis
refs = load_helper('coast_refs')
versions = load_helper('coast_receipt_versions')
validator = load_helper('validate_coast_receipt')
_spec = importlib.util.spec_from_file_location('canonical_screen_under_test', ROOT / 'skills/coast-local-screen/scripts/local_screen.py')
ls = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ls)
common = ls._shared_review()


class World:
    def __init__(self, destination, states=('map_done',), no_resolution=False, missing_products=False):
        import numpy as np
        from rasterio.io import MemoryFile
        from rasterio.transform import from_origin
        instances, bindings = materialize(destination, windows=len(states))
        self.queue = destination / 'queue'
        self.bindings = {k: v for k, v in bindings.items() if not k.startswith('archive:')}
        self.resolver = refs.Resolver(self.bindings, allowed_root_ids=self.bindings)
        self.roots = destination / 'roots.json'
        self.roots.write_bytes(refs.canonical(self.bindings))
        self.directory = self.queue / 'plans/plan01/review/r01/a01/tier1'
        self.context_path = self.directory.parent / 'context.json'
        self.instances = instances
        self.windows = instances['admission']['windows']
        run = copy.deepcopy(refs.loads(self.resolver.read(instances['run-summary']['legacy_run'])))
        jobs = refs.loads(self.resolver.read(run['enqueue']))['jobs']
        for i, (window, state) in enumerate(zip(run['windows'], states, strict=True)):
            window['state'] = state
            if state != 'map_done' or missing_products:
                continue
            width, height = self.windows[i]['pixel_window'][2:]
            data = np.full((height, width), 10.0, dtype='float32')
            products = {}
            for name, values in (('terrain', data), ('mask', np.ones_like(data, dtype='uint8'))):
                with MemoryFile() as mem:
                    with mem.open(driver='GTiff', width=width, height=height, count=1,
                                  dtype=str(values.dtype), crs='EPSG:4326' if no_resolution else 'EPSG:3310',
                                  transform=from_origin(100, 100, 1, 1)) as ds:
                        ds.write(values, 1)
                    products[name] = self.put(f'products/window-{i}/{name}.tif', mem.read())
            depth = dict(count=width*height, min=10.0, max=10.0, mean=10.0, p80='unknown')
            cells = dict(schema='coastal-terrain-summary-v1', native_valid_count=width*height, depth_m=depth)
            if not no_resolution:
                cells['native_resolution_m'] = [1.0, 1.0]
            products['cells'] = dict(self.put(f'products/window-{i}/cells.json', cells), contract=versions.CELLS_CONTRACT)
            window['stages'] = dict(map=dict(job_id=f'synthetic-map-{i}', state='done', holds=[],
                input_manifest=jobs[i]['input_manifest'], result_ref=None, missing_reason=None,
                products=products, native_valid_count=width*height, depth_m=depth))
        run['counts'] = dict({state: states.count(state) for state in versions.STATES}, windows=len(states), by_hold_reason={})
        run_ref = self.put('runs/canonical-native.json', run)
        v2 = versions.run_v2(run, run_ref, instances['review-context']['enqueue'])
        v2_ref = self.put('runs/canonical-v2.json', v2)
        context = copy.deepcopy(instances['review-context'])
        runtime = dict(actual_model=context['run_author_model'], family='synthetic', profile='fixture',
                       card_id=context['run_card_id'], code_commit=context['code_commit'], skill_commit=context['skill_commit'],
                       created_utc=context['created_utc'], session_id='synthetic-offline', provider='no-model-called')
        identity = {k: context[k] for k in (*common.IDENTITY, 'run_author_model', 'run_card_id')}
        context.update(root_ids=list(self.bindings), run=v2_ref, bridge=run['bridge'],
                       identity_provenance=self.put('provenance/canonical-identity.txt', identity),
                       run_author_provenance=self.put('provenance/canonical-author.txt', runtime),
                       thresholds=self.put('provenance/thresholds.json', THRESHOLDS),
                       prompts=[self.put(f'prompts/{kind}.md', (ROOT/f'skills/coast-local-screen/prompts/{kind}.md').read_bytes())
                                for kind in ('text', 'vision')])
        context['posted_hashes'] = self.put('provenance/canonical-posted.txt', {k: context[k] for k in common.PINS})
        self.context_ref = self.put('plans/plan01/review/r01/a01/context.json', context)
        validator.validate(context, self.resolver, root_id='queue:synthetic')
        self.round = ls.Round(self.roots, self.context_path)

    def put(self, path, value):
        raw = value if isinstance(value, bytes) else refs.canonical(value)
        target = self.queue / path
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open('xb') as stream:
            stream.write(raw)
        return dict(root_id='queue:synthetic', path=path, sha256=refs.sha256(raw), bytes=len(raw))

    def argv(self, kind, **overrides):
        args = dict(roots=self.roots, context=self.context_path, out=self.directory / (('flagged-windows' if kind == 'assemble' else kind) + '.json'))
        if kind == 'stats':
            args['thumbnail-dir'] = self.directory / 'windows'
        else:
            args['stats'] = self.directory / 'stats.json'
        if kind in ('text', 'vision'):
            args.update(endpoint='http://127.0.0.1:9/refused', model='synthetic-response-no-inference', slots=1)
        if kind == 'assemble':
            args.update(text=self.directory / 'text.json', vision=self.directory / 'vision.json')
        args.update(overrides)
        return [kind, *[v for key, value in args.items() for v in ('--' + key, str(value))]]

    def call(self, kind, **overrides):
        return ls.main(self.argv(kind, **overrides))

    def read(self, name):
        return refs.loads((self.directory/name).read_bytes())

    def stages(self):
        for mode in ('stats', 'text', 'vision'):
            assert self.call(mode) == 0
        return self


@pytest.fixture(autouse=True)
def synthetic_model(monkeypatch):
    for key, value in dict(AUTHOR_PROFILE='synthetic-test', AUTHOR_MODEL='synthetic-no-inference',
                           CARD_ID='t_de9b2254', CODE_COMMIT='1'*40, SKILL_COMMIT='1'*40).items():
        monkeypatch.setenv('COAST_' + key, value)
    def post(url, body, timeout):
        assert url == 'http://127.0.0.1:9/refused/chat/completions'
        assert timeout == 60
        return dict(choices=[dict(message=dict(content='pass'), finish_reason='stop')],
                    usage=dict(prompt_tokens=5, completion_tokens=1), system_fingerprint='synthetic-no-inference')
    monkeypatch.setattr(ls, '_post', post)
    monkeypatch.setattr(ls.Plan, '_latest', lambda *a: pytest.fail('canonical mode must never select latest'))


def test_canonical_exact_flags_schema_unknown_and_write_once(tmp_path):
    w = World(tmp_path).stages()
    assert w.call('assemble') == 0
    doc = w.read('flagged-windows.json')
    validator.validate(doc, w.resolver, root_id='queue:synthetic')
    entry = doc['windows'][0]
    assert entry['status'] == 'pass' and entry['flags'] == []
    assert entry['producer_fields'] == [dict(field_path='depth_m.' + key,
        source=w.round.cells[entry['window_key']]['producer'], value=value)
        for key, value in dict(count=w.windows[0]['pixel_window'][2]*w.windows[0]['pixel_window'][3],
                              min=10.0, max=10.0, mean=10.0, p80='unknown').items()]
    assert all(entry['measurements'][name]['status'] == 'measured' for name in ls.REQUIRED_MEASUREMENTS)
    assert entry['measurements']['neighbour_delta']['reason'] == 'no_geometric_neighbours'
    assert entry['measurements']['catalog_range']['reason'] == 'catalog_range_absent'
    for mode in ('stats', 'text', 'vision', 'assemble'):
        before = {p: p.read_bytes() for p in w.directory.rglob('*') if p.is_file()}
        assert w.call(mode) == 2
        assert before == {p: p.read_bytes() for p in before}
    for mode in ('text', 'vision'):
        response = w.round.doc(entry[mode + '_response'])
        assert response['window_key'] == entry['window_key']
        assert response['model'] == 'synthetic-response-no-inference'


def test_all_windows_and_held_unmapped_not_pass(tmp_path):
    w = World(tmp_path, ('map_done', 'held', 'unfinished', 'map_done')).stages()
    assert w.call('assemble') == 0
    doc = w.read('flagged-windows.json')
    assert [e['window_key'] for e in doc['windows']] == [e['window_key'] for e in w.windows]
    assert doc['windows'][1]['status'] == 'held'
    assert doc['windows'][2]['status'] == 'unavailable'
    assert all(m['reason'] == 'pipeline_not_mapped' for m in doc['windows'][1]['measurements'].values())
    assert any(f['code'] == 'DERIVED_UNAVAILABLE' for f in doc['windows'][0]['flags'])
    validator.validate(doc, w.resolver, root_id='queue:synthetic')


def test_endpoint_unavailable_two_attempts_flags_every_mapped(tmp_path, monkeypatch):
    calls = []
    def fail(url, body, timeout):
        calls.append(timeout)
        raise urllib.error.URLError('synthetic endpoint unavailable; no socket attempted')
    monkeypatch.setattr(ls, '_post', fail)
    w = World(tmp_path, ('map_done',) * 4).stages()
    assert calls == [60, 60, 60, 60]  # two per mode, not per window; no sleep
    assert w.call('assemble') == 0
    for row in w.read('flagged-windows.json')['windows']:
        assert row['status'] == 'flag'
        assert row['text_verdict'] == row['vision_verdict'] == 'unavailable'
        assert {f['code'] for f in row['flags']} == {'ENDPOINT_UNAVAILABLE'}


def test_required_null_not_optional_na(tmp_path):
    w = World(tmp_path, no_resolution=True).stages()
    assert w.call('assemble') == 0
    row = w.read('flagged-windows.json')['windows'][0]
    assert row['measurements']['slope_p99_deg']['status'] == 'unavailable'
    assert row['status'] == 'flag'
    assert {f['code'] for f in row['flags']} == {'DERIVED_UNAVAILABLE'}
    assert row['measurements']['neighbour_delta']['status'] == 'not_applicable'


@pytest.mark.parametrize('mode', ['stats', 'text'])
def test_wrong_window_deciding_gate_off_on_restored(tmp_path, monkeypatch, capsys, mode):
    w = World(tmp_path, ('map_done', 'map_done'))
    assert w.call('stats') == 0
    original = w.read('stats.json')
    original_ref = common.pin(w.resolver, w.directory/'stats.json')
    if mode == 'stats':
        bad = copy.deepcopy(original)
        bad['windows'][0]['producer'], bad['windows'][1]['producer'] = bad['windows'][1]['producer'], bad['windows'][0]['producer']
        ls._validate_intermediate(bad, 'stats')
        bad_ref = w.put('mutants/stats.json', bad)
        bad_path = w.queue/bad_ref['path']
        # Generate the downstream envelopes from this explicit mutant with ONLY
        # the deciding gate disabled; every downstream stats Ref is genuine.
        with monkeypatch.context() as control:
            control.setattr(ls, '_bind_stats_window', lambda *args: [])
            for kind in ('text', 'vision'):
                assert w.call(kind, stats=bad_path) == 0
        kwargs = dict(stats=bad_path)
    else:
        for kind in ('text', 'vision'):
            assert w.call(kind) == 0
        bad = w.read('text.json')
        bad['windows'][0]['window_key'] = bad['windows'][1]['window_key']
        ls._validate_intermediate(bad, 'text')
        bad_ref = w.put('mutants/text.json', bad)
        kwargs = dict(text=w.queue/bad_ref['path'])
    assert w.call('assemble', **kwargs) == 2
    error = capsys.readouterr().err
    assert 'WINDOW_BINDING' in error and w.windows[0]['window_key'] in error
    if mode == 'stats':
        assert w.windows[1]['window_key'] in error
    assert not (w.directory/'flagged-windows.json').exists()
    args = SimpleNamespace(out=w.directory/'flagged-windows.json', stats=kwargs.get('stats', w.directory/'stats.json'),
                           text=kwargs.get('text', w.directory/'text.json'), vision=w.directory/'vision.json')
    with monkeypatch.context() as control:
        control.setattr(ls, '_bind_stats_window', lambda *args: [])
        accepted_off = ls._canonical_assemble(w.round, args)
        assert all(row['status'] == 'pass' and row['flags'] == [] for row in accepted_off['windows'])
    assert w.call('assemble', **kwargs) == 2
    assert not (w.directory/'flagged-windows.json').exists()
    assert common.pin(w.resolver, w.directory/'stats.json') == original_ref
    positive = World(tmp_path/'positive', ('map_done', 'map_done')).stages()
    assert positive.call('assemble') == 0
    assert all(row['status'] == 'pass' for row in positive.read('flagged-windows.json')['windows'])


@pytest.mark.parametrize('where', ['root', 'ancestor', 'leaf'])
def test_symlink_reads_refuse_before_outputs(tmp_path, where):
    w = World(tmp_path/'fixture')
    alias = tmp_path/'alias'
    alias.symlink_to(w.queue, target_is_directory=True)
    if where == 'root':
        bindings = dict(w.bindings, **{'queue:synthetic': str(alias)})
        w.roots = tmp_path/'alias-roots.json'
        w.roots.write_bytes(refs.canonical(bindings))
    elif where == 'ancestor':
        w.context_path = alias/w.context_path.relative_to(w.queue)
    else:
        leaf = w.context_path.parent/'alias.json'
        leaf.symlink_to(w.context_path)
        w.context_path = leaf
    assert w.call('stats') == 2
    assert not w.directory.exists()


def test_symlink_output_ancestor_and_partial_thumbnail_refused(tmp_path):
    w = World(tmp_path/'fixture')
    elsewhere = tmp_path/'elsewhere'
    elsewhere.mkdir()
    w.directory.symlink_to(elsewhere, target_is_directory=True)
    assert w.call('stats') == 2
    assert list(elsewhere.iterdir()) == []
    other = World(tmp_path/'other')
    thumb = other.directory/'windows'/other.windows[0]['window_dir']/'hillshade.png'
    thumb.parent.mkdir(parents=True)
    thumb.write_bytes(b'synthetic partial attempt evidence')
    assert other.call('stats') == 2
    assert thumb.read_bytes() == b'synthetic partial attempt evidence'
    assert not (other.directory/'stats.json').exists()


def test_hash_changed_input_never_calls_model(tmp_path, monkeypatch):
    w = World(tmp_path)
    ref = w.round.cells[w.windows[0]['window_key']]['producer']
    path = w.queue/ref['path']
    raw = path.read_bytes()
    path.write_bytes(raw[:-1] + b' ')
    monkeypatch.setattr(ls, '_post', lambda *a: pytest.fail('bad pin must not reach model'))
    assert w.call('stats') == 2
    assert not w.directory.exists()


def test_two_sources_two_grids_do_not_alias_or_become_neighbours():
    # Identity/adjacency helper control; full graph factory supplies the runtime
    # two-window producer binding above. Global idx is explicitly out of scope.
    windows = [dict(source_id=source, grid_sha256=refs.sha256(grid.encode()), idx=0,
                    pixel_window=[x, 0, 4, 4]) for source, grid, x in
               [('one', 'a', 0), ('one', 'b', 4), ('two', 'a', 0), ('two', 'b', 4)]]
    keys = [f"{w['source_id']}#{w['grid_sha256']}#{w['idx']}" for w in windows]
    assert len(set(keys)) == 4
    assert len({ls.sha256(k.encode()) for k in keys}) == 4
    assert not any(ls._adjacent(a, b) for a in windows for b in windows if a != b)


@pytest.mark.parametrize('reply', [[], {'choices': [None]}, {'choices': [{'message': {'content': 'pass\nflag'}}]}])
def test_malformed_response_never_passes(tmp_path, monkeypatch, reply):
    monkeypatch.setattr(ls, '_post', lambda *args: reply)
    w = World(tmp_path).stages()
    assert w.call('assemble') == 0
    row = w.read('flagged-windows.json')['windows'][0]
    assert row['status'] == 'flag'
    assert row['text_verdict'] != 'pass' and row['vision_verdict'] != 'pass'


@pytest.mark.parametrize('mode', ['stats', 'text', 'vision'])
def test_partial_child_symlink_refuses_before_any_model_or_write(tmp_path, monkeypatch, mode):
    w = World(tmp_path/'fixture')
    if mode != 'stats':
        assert w.call('stats') == 0
    outside = tmp_path/'outside'
    outside.mkdir()
    parent = w.directory/'windows'/w.windows[0]['window_dir']
    if mode == 'stats':
        parent.parent.mkdir(parents=True)
        parent.symlink_to(outside, target_is_directory=True)
    else:
        (parent/(mode + '-response.txt')).symlink_to(outside/'target.txt')
    before = {p: p.read_bytes() for p in w.directory.rglob('*') if p.is_file() and not p.is_symlink()}
    monkeypatch.setattr(ls, '_post', lambda *a: pytest.fail('symlink must refuse before model'))
    assert w.call(mode) == 2
    assert list(outside.iterdir()) == []
    assert before == {p: p.read_bytes() for p in before}


def test_missing_response_cannot_claim_pass(tmp_path, capsys):
    w = World(tmp_path).stages()
    doc = w.read('text.json')
    doc['windows'][0]['response'] = None
    ls._validate_intermediate(doc, 'text')
    ref = w.put('mutants/no-response.json', doc)
    assert w.call('assemble', text=w.queue/ref['path']) == 2
    assert 'WINDOW_BINDING' in capsys.readouterr().err
    assert not (w.directory/'flagged-windows.json').exists()


def test_actual_screener_provenance_required(tmp_path, monkeypatch):
    w = World(tmp_path).stages()
    monkeypatch.delenv('COAST_AUTHOR_MODEL')
    assert w.call('assemble') == 2
    assert not (w.directory/'flagged-windows.json').exists()


def test_mapped_without_bound_cells_is_unavailable_not_pass(tmp_path):
    w = World(tmp_path, missing_products=True).stages()
    assert w.call('assemble') == 0
    doc = w.read('flagged-windows.json')
    row = doc['windows'][0]
    assert row['status'] == 'unavailable' and row['producer_fields'] == []
    assert row['measurements']['catalog_range']['reason'] == 'catalog_range_absent'
    assert 'DERIVED_UNAVAILABLE' in {f['code'] for f in row['flags']}
    validator.validate(doc, w.resolver, root_id='queue:synthetic')
