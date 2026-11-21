"""Synthetic, whole-plan checks for the selective rebuild preview."""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path

import pytest

from skippercast.relief import rebuild_plan, receipts
from tests._support import ROOT


OLD = '1' * 64
NEW = '2' * 64
# Scoped keys and direct links from the runner and its stages. In particular,
# QA reads shots as an input file, not as an upstream receipt in this chain.
CHAIN = {
    'select': (),
    'mosaic.public': ('select',),
    'tiles.public': ('select', 'mosaic.public'),
    'zone.public': ('select', 'mosaic.public'),
    'digests': ('tiles.public',),
    'inventory': ('select', 'tiles.public', 'digests', 'zone.public'),
    'contours': ('select', 'mosaic.public'),
    'package': ('tiles.public', 'digests', 'zone.public', 'inventory', 'contours'),
    'shots': ('package',),
    'qa': ('package', 'mosaic.public', 'contours'),
    'envelope': ('package', 'qa'),
}


def _receipt(key, links=(), **params):
    stage, _, scope = key.partition('.')
    upstream = []
    for link in links:
        name, _, link_scope = link.partition('.')
        upstream.append({'stage': name, 'scope': link_scope or None, 'generation': OLD})
    return {'schema': 'sc-stage-receipt/1', 'region': 'test-bay', 'stage': stage,
            'scope': scope or None, 'status': 'ok', 'code': {'stage_digest': OLD},
            'generation': OLD, 'params': params, 'upstream': upstream}


def _current(keys, **style):
    return {'stage_digest': dict.fromkeys(keys, OLD),
            'style': {'baked': OLD, 'contours': OLD, 'habitat': None, **style}}


def _row(stage, *reasons):
    return {'stage': stage, 'action': 'rebuild' if reasons else 'reuse',
            'reasons': list(reasons)}


@pytest.fixture
def docs():
    # Reversed input order makes accidentally walking the mappings fail C1.
    result = {key: _receipt(key, CHAIN[key]) for key in reversed(CHAIN)}
    result['tiles.public']['params'] = {'engine': 'nearshore', 'baked': OLD}
    result['contours']['params'] = {'set': 'ft-v3', 'contours': OLD}
    return result


def test_c1_paint_only_keeps_every_stage_in_chain_order(docs):
    """C1: A paint-only id bump is not a build input."""
    before = _current(reversed(CHAIN), paint=OLD)
    after = _current(reversed(CHAIN), paint=NEW)
    expected = [_row(key) for key in CHAIN]
    assert rebuild_plan.plan(docs, before) == expected
    assert rebuild_plan.plan(docs, after) == expected


def test_c1_empty_stage_selection():
    """C1: Don't invent stages when nothing is selected or recorded."""
    assert rebuild_plan.plan({}, _current(())) == []


def test_c2_legacy_producers_without_style_params_reuse(docs):
    """C2: Stage names alone don't bind a digest; legacy stages remain reusable."""
    docs['tiles.public']['params'] = {'ramp': 'deep-fixed-v1'}
    docs['contours']['params'] = {'set': 'ft-v2'}
    current = _current(CHAIN, baked=NEW, contours=NEW, habitat=NEW)
    assert rebuild_plan.plan(docs, current) == [_row(key) for key in CHAIN]


def test_c2_baked_change_rebuilds_only_tile_consumers(docs):
    """C2: A baked change must not cascade by list position to zone or contours."""
    expected = [
        _row('select'), _row('mosaic.public'), _row('tiles.public', 'style:baked'),
        _row('zone.public'), _row('digests', 'upstream:tiles.public'),
        _row('inventory', 'upstream:digests', 'upstream:tiles.public'), _row('contours'),
        _row('package', 'upstream:digests', 'upstream:inventory', 'upstream:tiles.public'),
        _row('shots', 'upstream:package'), _row('qa', 'upstream:package'),
        _row('envelope', 'upstream:package', 'upstream:qa'),
    ]
    current = _current(CHAIN, baked=NEW)
    assert rebuild_plan.plan(docs, current) == expected
    # A different region already at that baked digest is unaffected.
    up_to_date = {**docs, 'tiles.public': _receipt('tiles.public', CHAIN['tiles.public'], baked=NEW)}
    assert rebuild_plan.plan(up_to_date, current) == [_row(key) for key in CHAIN]


@pytest.mark.parametrize('reason', [pytest.param('code', id='C2: contours code changes'),
                                    pytest.param('style:contours', id='C2: contours style changes')])
def test_c2_contours_change_reaches_release_chain(docs, reason):
    """C2: Both package and QA carry direct contour links."""
    current = _current(CHAIN)
    if reason == 'code':
        current['stage_digest']['contours'] = NEW
    else:
        current['style']['contours'] = NEW
    assert rebuild_plan.plan(docs, current) == [
        _row('select'), _row('mosaic.public'), _row('tiles.public'), _row('zone.public'),
        _row('digests'), _row('inventory'), _row('contours', reason),
        _row('package', 'upstream:contours'), _row('shots', 'upstream:package'),
        _row('qa', 'upstream:contours', 'upstream:package'),
        _row('envelope', 'upstream:package', 'upstream:qa'),
    ]


@pytest.mark.parametrize('status', [pytest.param('failed', id='C2: failed stage'),
                                    pytest.param('held', id='C2: held stage')])
def test_c2_status_rebuilds_with_no_digest_change(docs, status):
    """C2: Matching digests don't make a failed or held stage reusable."""
    docs['zone.public']['status'] = status
    assert rebuild_plan.plan(docs, _current(CHAIN)) == [
        _row('select'), _row('mosaic.public'), _row('tiles.public'),
        _row('zone.public', f'status:{status}'), _row('digests'),
        _row('inventory', 'upstream:zone.public'), _row('contours'),
        _row('package', 'upstream:inventory', 'upstream:zone.public'),
        _row('shots', 'upstream:package'), _row('qa', 'upstream:package'),
        _row('envelope', 'upstream:package', 'upstream:qa'),
    ]


@pytest.mark.parametrize('known_digest', [pytest.param(True, id='C2: missing current stage'),
                                          pytest.param(False, id='C2: missing linked stage')])
def test_c2_missing_receipt_keeps_its_downstream_links(docs, known_digest):
    """C2: A missing scoped mosaic still invalidates its recorded consumers."""
    del docs['mosaic.public']
    current = _current(CHAIN)
    if not known_digest:
        del current['stage_digest']['mosaic.public']
    assert rebuild_plan.plan(docs, current) == [
        _row('select'), _row('mosaic.public', 'missing'), _row('tiles.public', 'upstream:mosaic.public'),
        _row('zone.public', 'upstream:mosaic.public'), _row('digests', 'upstream:tiles.public'),
        _row('inventory', 'upstream:digests', 'upstream:tiles.public', 'upstream:zone.public'),
        _row('contours', 'upstream:mosaic.public'),
        _row('package', 'upstream:contours', 'upstream:digests', 'upstream:inventory',
             'upstream:tiles.public', 'upstream:zone.public'),
        _row('shots', 'upstream:package'),
        _row('qa', 'upstream:contours', 'upstream:mosaic.public', 'upstream:package'),
        _row('envelope', 'upstream:package', 'upstream:qa'),
    ]


def test_c2_combines_sorted_reasons_without_leaking_across_scopes():
    """C2: A scoped link targets only that scope; don't drop concurrent reasons."""
    docs = {
        'nearshore_vectors.public': _receipt('nearshore_vectors.public', ('tiles.public',),
                                             baked=OLD, habitat=OLD, paint=OLD),
        'tiles.private': _receipt('tiles.private'),
        'tiles.public': None,
    }
    docs['nearshore_vectors.public']['status'] = 'failed'
    current = _current(docs, baked=NEW, contours=NEW, paint=NEW)
    current['stage_digest']['nearshore_vectors.public'] = NEW
    assert rebuild_plan.plan(docs, current) == [
        _row('tiles.private'), _row('tiles.public', 'missing'),
        _row('nearshore_vectors.public', 'code', 'status:failed', 'style:baked', 'style:habitat',
             'upstream:tiles.public'),
    ]


def test_c2_private_scope_change_leaves_public_consumers_untouched():
    """C2: A private rebuild is not an upstream reason for a public link."""
    docs = {'digests': _receipt('digests', ('tiles.public',)),
            'tiles.public': _receipt('tiles.public'), 'tiles.private': _receipt('tiles.private')}
    current = _current(docs)
    current['stage_digest']['tiles.private'] = NEW
    assert rebuild_plan.plan(docs, current) == [
        _row('tiles.private', 'code'), _row('tiles.public'), _row('digests'),
    ]


def test_c2_links_override_runner_order():
    """C2: A custom prerequisite must precede its consumer regardless of display rank."""
    docs = {'tiles.public': _receipt('tiles.public', ('custom',)), 'custom': _receipt('custom')}
    current = _current(docs)
    current['stage_digest']['custom'] = NEW
    assert rebuild_plan.plan(docs, current) == [
        _row('custom', 'code'), _row('tiles.public', 'upstream:custom'),
    ]


def test_c2_refuses_cyclic_links():
    """C2: A dependency cycle can't have an upstream-first rebuild plan."""
    docs = {'select': _receipt('select', ('mosaic.public',)),
            'mosaic.public': _receipt('mosaic.public', ('select',))}
    with pytest.raises(receipts.ReceiptError) as error:
        rebuild_plan.plan(docs, _current(docs))
    assert type(error.value) is receipts.ReceiptError


def test_c3_plan_has_no_io_or_input_mutation(monkeypatch):
    """C3: Preview must not read output files or alter the supplied snapshots."""
    docs = {'contours': _receipt('contours', contours=OLD)}
    current = _current(docs, contours=None)
    original = deepcopy((docs, current))

    def refused(*args, **kwargs):
        pytest.fail('plan attempted filesystem I/O')

    with monkeypatch.context() as patch:
        patch.setattr(Path, 'open', refused)
        patch.setattr('builtins.open', refused)
        patch.setattr('os.open', refused)
        actual = rebuild_plan.plan(docs, current)
    assert (docs, current) == original
    assert actual == [_row('contours', 'style:contours')]


def test_c3_loads_one_region_without_changing_files(tmp_path):
    """C3: Loading preserves scoped keys and doesn't rewrite or mix receipt directories."""
    stages = tmp_path / 'test-bay' / 'stages'
    stages.mkdir(parents=True)
    other = tmp_path / 'other-bay' / 'stages'
    other.mkdir(parents=True)
    wanted = {'select': _receipt('select'), 'mosaic.public': _receipt('mosaic.public', ('select',)),
              'mosaic.private': _receipt('mosaic.private', ('select',))}
    for key, doc in wanted.items():
        (stages / f'{key}.json').write_text(json.dumps(doc), encoding='utf-8')
    (other / 'select.json').write_text('{}', encoding='utf-8')
    (stages / 'select.lock').touch()

    def snapshot():
        return {path: (path.stat().st_mtime_ns, path.read_bytes() if path.is_file() else None)
                for path in tmp_path.rglob('*')}

    before = snapshot()
    assert rebuild_plan.load_receipts(tmp_path, 'test-bay') == wanted
    assert rebuild_plan.load_receipts(tmp_path, 'unknown-bay') == {}
    assert snapshot() == before


def test_c3_file_disappears_between_listing_and_loading(tmp_path, monkeypatch):
    """C3: An absent receipt isn't returned as a document if it vanishes after listing."""
    monkeypatch.setattr(receipts.Region, 'keys', lambda self: [('select', None)])
    assert rebuild_plan.load_receipts(tmp_path, 'test-bay') == {}


@pytest.mark.parametrize('region', [pytest.param('../test-bay', id='C3: invalid region'),
                                    pytest.param('test-bay', id='C3: malformed receipt')])
def test_c3_preserves_receipt_reader_refusals(tmp_path, region):
    """C3: Do not accept an invalid region or silently drop malformed JSON."""
    stages = tmp_path / 'test-bay' / 'stages'
    stages.mkdir(parents=True)
    (stages / 'mosaic.public.json').write_text('{', encoding='utf-8')
    with pytest.raises(receipts.ReceiptError) as error:
        rebuild_plan.load_receipts(tmp_path, region)
    assert type(error.value) is receipts.ReceiptError


def write_style_tree(repo):
    """Small independent token/index pairs for the real style loader."""
    directory = repo / 'style'
    directory.mkdir()

    def encoded(data):
        return json.dumps(data, sort_keys=True, separators=(',', ':')).encode()

    groups = dict.fromkeys(('baked', 'contours', 'habitat', 'paint'), 1)
    (directory / 'groups.json').write_bytes(encoded({key: key for key in groups}))
    versions = {'deep-fixed-v1': {'legacy': True, 'status': 'active'}}
    for name, changed in [('base', ()), ('paint-v2', ('paint',)), ('baked-v2', ('baked',)),
                          ('vectors-v2', ('contours', 'habitat')), ('retired', ('baked',))]:
        tokens = groups | dict.fromkeys(changed, 2)
        raw = encoded(tokens)
        file = f'{name}.json'
        (directory / file).write_bytes(raw)
        versions[name] = {
            'file': file, 'sha256': sha256(raw).hexdigest(),
            'status': {'baked-v2': 'rolling', 'retired': 'retired'}.get(name, 'active'),
            'digests': {group: sha256(encoded({group: value})).hexdigest()
                        for group, value in tokens.items()},
        }
    (directory / 'index.json').write_bytes(encoded({'default': 'base', 'versions': versions}))
    return directory, versions['base']['digests']


@pytest.fixture
def simulation(tmp_path, monkeypatch):
    directory, base = write_style_tree(tmp_path)
    monkeypatch.setenv('SKIPPERCAST_ROOT', str(tmp_path))
    docs = {
        'tiles.public': _receipt('tiles.public', baked=base['baked'], paint=base['paint']),
        'contours': _receipt('contours', contours=base['contours']),
        'digests': _receipt('digests', ('tiles.public',)),
        'vectors.public': _receipt('vectors.public', ('tiles.public',), habitat=base['habitat']),
    }
    return directory, docs


@pytest.mark.parametrize(('options', 'reasons'), [
    pytest.param({}, ((), (), (), ()), id='C1: indexed default'),
    pytest.param({'default': 'paint-v2'}, ((), (), (), ()), id='C1: paint-only change'),
    pytest.param({'default': 'baked-v2'}, (('style:baked',), ('upstream:tiles.public',), (),
                                          ('upstream:tiles.public',)), id='C1: baked change'),
    pytest.param({'pin': 'vectors-v2'}, ((), (), ('style:contours',), ('style:habitat',)),
                 id='C1: independent contours and habitat digests'),
    pytest.param({'pin': 'deep-fixed-v1'}, (('style:baked',), ('upstream:tiles.public',),
                                           ('style:contours',), ('style:habitat', 'upstream:tiles.public')),
                 id='C1: legacy has no build digests'),
])
def test_simulated_style_digests(simulation, options, reasons):
    """C1: Version identity or mismatched group selection must not trigger unrelated stages."""
    root, docs = simulation
    keys = ('tiles.public', 'digests', 'contours', 'vectors.public')
    assert rebuild_plan.simulate_style('test-bay', docs, root=root, **options) == [
        _row(key, *why) for key, why in zip(keys, reasons)
    ]


def test_simulated_pin_precedence(simulation):
    """C1: A default cannot unpin a region, but a proposed pin can replace its saved pin."""
    root, docs = simulation
    schema = root.parent / 'schemas/sc-render-v1.schema.json'
    schema.parent.mkdir()
    schema.write_bytes((ROOT / 'schemas' / schema.name).read_bytes())
    config = root.parent / 'regions/test-bay/render.json'
    config.parent.mkdir(parents=True)
    saved = b'{"schema":"sc-render/1","region":"test-bay","style":"base","previews":[],"piers":[]}'
    config.write_bytes(saved)
    assert rebuild_plan.simulate_style('test-bay', docs, default='baked-v2') == [
        _row(key) for key in ('tiles.public', 'digests', 'contours', 'vectors.public')
    ]
    assert rebuild_plan.simulate_style('test-bay', docs, default='paint-v2', pin='baked-v2') == [
        _row('tiles.public', 'style:baked'), _row('digests', 'upstream:tiles.public'),
        _row('contours'), _row('vectors.public', 'upstream:tiles.public'),
    ]
    assert config.read_bytes() == saved


@pytest.mark.parametrize(('options', 'message'), [
    pytest.param({'default': 'unknown'}, 'unavailable render style: unknown', id='C3: unknown default'),
    pytest.param({'pin': 'retired'}, 'unavailable render style: retired', id='C3: retired pin'),
    pytest.param({'default': 'retired', 'pin': 'base'}, 'unavailable render style: retired',
                 id='C3: retired default even when shadowed'),
    pytest.param({'pin': 'paint-v2'}, 'paint-v2: sha256 mismatch', id='C1: reject tampered version bytes'),
])
def test_simulated_style_refusals(simulation, options, message):
    """C3: Refuse unavailable selections; C1: selected bytes must verify, not just parse."""
    root, docs = simulation
    tokens = root / 'paint-v2.json'
    tokens.write_bytes(tokens.read_bytes() + b'\n')
    with pytest.raises(ValueError, match=message) as error:
        rebuild_plan.simulate_style('test-bay', docs, root=root, **options)
    assert type(error.value) is ValueError
