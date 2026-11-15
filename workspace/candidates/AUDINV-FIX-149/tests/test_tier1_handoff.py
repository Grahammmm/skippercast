"""Offline synthetic leaves only. Temporary fixtures stay inside candidate root."""
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import pytest

PACKAGE = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('candidate_handoff', PACKAGE / 'tier1_handoff.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


@pytest.fixture
def setup():
    with tempfile.TemporaryDirectory(prefix='synthetic-', dir=PACKAGE / 'fixtures') as directory:
        root = Path(directory)
        receipt = json.loads((PACKAGE / 'fixtures/held-handoff.json').read_text())
        def run(doc=None, edit=None, samples=None):
            doc = deepcopy(receipt if doc is None else doc)
            raw = module.refs.canonical(doc)
            for name in ('first.json', 'second.json'):
                (root / name).write_bytes(raw)
            refs = [dict(root_id='queue:synthetic', path=name, sha256=hashlib.sha256(raw).hexdigest(), bytes=len(raw))
                    for name in ('first.json', 'second.json')]
            posted = deepcopy(refs)
            if edit:
                edit(posted, root)
            before = (root / 'first.json').read_bytes()
            result = module.handoff(doc, posted, admitted_refs=refs,
                bindings={'queue:synthetic': str(root)}, admitted_samples=samples)
            assert (root / 'first.json').read_bytes() == before
            assert result['input_receipt'] == doc and result['attempt_history'] == doc['attempt_history']
            return result
        yield receipt, run


def test_held_nulls_explicit_paths_and_no_native_dispatch(setup, monkeypatch):
    receipt, run = setup
    seen = []
    original = module.refs.Resolver.read
    def read(self, ref, **kwargs):
        seen.append(ref['path'])
        return original(self, ref, **kwargs)
    monkeypatch.setattr(module.refs.Resolver, 'read', read)
    monkeypatch.setattr(module.bands, 'depth_bands', lambda **kw: pytest.fail('held sample dispatch'))
    result = run(samples={'unadmitted': 'must not invoke'})
    assert seen == ['first.json', 'second.json']  # identical hashes, distinct paths
    assert result['state'] == 'HELD' and result['review'] == 'REVIEW_REQUIRED'
    assert result['acquire_count'] == 0 and not result['integrity_holds']
    assert all(result[k] is None for k in ('qualification_count', 'map_count', 'mask',
        'valid_cells_by_band', 'deepest_mapped_cell_m'))
    assert result['quality'] == 'unavailable' and not result['visual_certified']
    assert result['native_sources']['status'] == 'AS_RECORDED'


@pytest.mark.parametrize('kind', ['missing', 'duplicate', 'conflict', 'absolute', 'escape',
    'symlink', 'directory-symlink', 'bytes', 'hash', 'uppercase', 'malformed', 'stale', 'same-length-drift'])
def test_bad_refs_refuse_without_fallback(setup, kind):
    _, run = setup
    def edit(posted, root):
        if kind == 'missing':
            (root / 'second.json').unlink()
        elif kind in ('duplicate', 'conflict'):
            posted.append(dict(posted[0], **({'bytes': 1} if kind == 'conflict' else {})))
        elif kind in ('absolute', 'escape'):
            posted[0]['path'] = '/first.json' if kind == 'absolute' else '../first.json'
        elif kind in ('symlink', 'directory-symlink'):
            (root / 'second.json').unlink()
            (root / 'second.json').symlink_to(root / ('first.json' if kind == 'symlink' else '.'))
        elif kind == 'bytes':
            posted[0]['bytes'] += 1
        elif kind == 'hash':
            posted[0]['sha256'] = 'c' * 64
        elif kind == 'uppercase':
            posted[0]['sha256'] = posted[0]['sha256'].upper()
        elif kind == 'malformed':
            posted[0]['sha256'] += ' '
        elif kind == 'same-length-drift':
            (root / 'second.json').write_bytes((root / 'second.json').read_bytes()[:-1] + b' ')
        else:
            (root / 'second.json').write_text('{}')
    result = run(edit=edit)
    assert result['state'] == 'HELD' and result['integrity_holds']
    assert result['map_count'] is None


@pytest.mark.parametrize('status', ['HOLD', 'CANCELLED', 'EXPIRED', 'FAILED'])
def test_terminal_status_preserved_and_mapping_conflict_held(setup, status):
    receipt, run = setup
    receipt['status'] = status
    assert run(receipt)['status'] == status
    receipt['stages']['map'] = {'status': 'PASS', 'count': 0}
    result = run(receipt)
    assert result['integrity_holds'] and result['map_count'] is None


def test_mapping_requires_independently_admitted_samples_and_matching_identity(setup):
    receipt, run = setup
    receipt['status'] = 'COMPLETED'
    receipt['stages'] = {s: {'status': 'PASS', 'count': 1, 'producer': 'synthetic-map'}
                         for s in ('acquire', 'qualify', 'map')}
    assert run(receipt)['valid_cells_by_band'] is None
    sample = dict(attempt=receipt['attempt'], window_key=receipt['window_key'], depths=[300], support=[True],
        producer='synthetic-map', qualified=True, units='m', sign='positive_down', storage='normalized_depth')
    assert run(receipt, samples=sample)['valid_cells_by_band']['>600ft'] == 1
    for field, value in [('attempt', 'old'), ('window_key', 'other'), ('producer', 'unbound'), ('support', [False])]:
        result = run(receipt, samples=dict(sample, **{field: value}))
        assert result['integrity_holds'] and result['valid_cells_by_band'] is None


def test_package_and_source_pins():
    bases = json.loads((PACKAGE / 'BASES.json').read_text())
    for paths, root in ((bases['sources'], module.ROOT), (bases['candidate_files'], PACKAGE)):
        for path, sha in paths.items():
            assert hashlib.sha256((root / path).read_bytes()).hexdigest() == sha, path
    receipt = module.refs.loads((PACKAGE / 'fixtures/held-handoff.json').read_bytes())
    posted = module.refs.loads((PACKAGE / 'fixtures/posted-manifest.json').read_bytes())
    result = module.handoff(receipt, posted, admitted_refs=posted,
        bindings={'queue:synthetic': str(PACKAGE / 'fixtures')})
    assert not result['integrity_holds'] and result['state'] == 'HELD'
    receipt['attempt'] = 'not-the-pinned-receipt'
    result = module.handoff(receipt, posted, admitted_refs=posted,
        bindings={'queue:synthetic': str(PACKAGE / 'fixtures')})
    assert result['integrity_holds'] and result['map_count'] is None
