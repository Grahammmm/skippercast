"""C45 Central preview recovery rehearsal: one region upgraded, interrupted, restored; five regions untouched."""
import hashlib
import json

import pytest

from scripts.relief import central_preview_recovery as rec
from scripts.relief import central_region_undo_plan as undo

CONTOUR = 'cambria-san-simeon'
TERRAIN = 'monterey-point-sur'
DETAIL = f'dist/regions/{CONTOUR}/depth-contours.geojson'
OVERVIEW = f'dist/regions/{CONTOUR}/depth-contours-overview.geojson'


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _bundle(tmp_path):
    """A six-region bundle whose pins point at small real files (pointer for all, contour pair for contour regions)."""
    src = tmp_path / 'src'
    src.mkdir(parents=True)
    regions = {}
    for region in undo.REGIONS:
        served = {}
        urls = [f'/catalog/relief/{region}.json']
        if region in undo.CONTOUR_REGIONS:
            urls += [f'/regions/{region}/depth-contours.geojson', f'/regions/{region}/depth-contours-overview.geojson']
        for i, url in enumerate(urls):
            data = (json.dumps({'region': region, 'url': url, 'n': i}) + '\n').encode()
            path = src / f'{region}-{i}.json'
            path.write_bytes(data)
            served[url] = {'file': str(path), 'sha256': _sha(data), 'role': 'test'}
        page = src / 'sources.html'
        page.write_bytes(b'<p>sources</p>\n')
        served['/sources'] = {'file': str(page), 'sha256': _sha(page.read_bytes()), 'role': 'shared page, not owned'}
        regions[region] = {'region': region, 'served': served}
    bundle = tmp_path / 'BUNDLE.json'
    bundle.write_text(json.dumps({'schema': 'test', 'regions': regions}))
    return bundle


def _tree(tmp_path):
    tree = tmp_path / 'work' / 'tree'
    tree.parent.mkdir()
    info = rec.build_tree(_bundle(tmp_path), tree)
    return tree, info


def test_tree_lays_only_served_owned_files_and_keeps_honest_absence(tmp_path):
    tree, info = _tree(tmp_path)
    assert info['files_laid'] == 4 * 3 + 2 * 1
    snap = rec.snapshot(tree)
    assert snap[f'catalog/depth-contours/{CONTOUR}.geojson'] is None  # the bundle serves no such file
    assert snap[f'catalog/relief/{TERRAIN}.json'] is not None
    assert not (tree / 'sources').exists()


def test_tree_refuses_changed_bytes_wrong_regions_and_a_checkout(tmp_path):
    bundle = _bundle(tmp_path)
    doc = json.loads(bundle.read_text())
    pin = doc['regions'][CONTOUR]['served'][f'/regions/{CONTOUR}/depth-contours.geojson']
    open(pin['file'], 'ab').write(b' ')
    with pytest.raises(ValueError, match='bundle bytes changed'):
        rec.build_tree(bundle, tmp_path / 'a')
    del doc['regions'][TERRAIN]
    bundle.write_text(json.dumps(doc))
    with pytest.raises(ValueError, match='six Central regions'):
        rec.build_tree(bundle, tmp_path / 'b')
    (tmp_path / 'repo' / '.git').mkdir(parents=True)
    with pytest.raises(ValueError, match='git checkout'):
        rec.build_tree(_bundle(tmp_path / 'x'), tmp_path / 'repo' / 'tree')
    assert not (tmp_path / 'repo' / 'tree').exists()  # nothing (not even the marker) was written into the checkout


def test_cli_refuses_a_checkout_work_dir_or_receipt_before_creating_anything(tmp_path):
    # Contract: a refused destination leaves no trace. Bug caught: --work / the marker / --receipt created inside a
    # checkout before the disposable-tree guard ran.
    bundle = _bundle(tmp_path)
    checkout = tmp_path / 'checkout'
    (checkout / '.git').mkdir(parents=True)
    outside = tmp_path / 'outside'
    args = ['--bundle', str(bundle), '--region', CONTOUR]
    assert rec.main(args + ['--work', str(checkout / 'run')]) == 1
    assert sorted(p.name for p in checkout.iterdir()) == ['.git']  # no work dir, tree or marker
    for receipt in (checkout / 'receipt.json', checkout / 'new-dir' / 'receipt.json'):
        assert rec.main(args + ['--work', str(outside), '--receipt', str(receipt)]) == 1
        assert not outside.exists()  # the rejected receipt stopped the run before the work dir was made
        assert sorted(p.name for p in checkout.iterdir()) == ['.git']
    link = tmp_path / 'link'
    link.symlink_to(checkout)  # a symlink into a checkout is resolved, not trusted
    assert rec.main(args + ['--work', str(link / 'run2')]) == 1
    assert sorted(p.name for p in checkout.iterdir()) == ['.git']
    existing = tmp_path / 'receipt.json'
    existing.write_text('keep')
    assert rec.main(args + ['--work', str(outside), '--receipt', str(existing)]) == 1
    assert not outside.exists() and existing.read_text() == 'keep'


def test_a_mixed_pair_or_unknown_bytes_never_pass(tmp_path):
    tree, _ = _tree(tmp_path)
    start = rec.snapshot(tree)
    prior = {rel: start[rel] for rel in undo.owned_paths(CONTOUR)}
    upgrade = rec.synthetic_upgrade(tree, CONTOUR)
    assert rec.region_state(tree, CONTOUR, prior, upgrade) == 'prior'
    rec._write(tree, DETAIL, upgrade[DETAIL])  # new detail, old overview
    assert rec.region_state(tree, CONTOUR, prior, upgrade) == 'mixed'
    assert not rec.passes('mixed')
    for rel in undo.owned_paths(CONTOUR):
        rec._write(tree, rel, upgrade[rel])
    assert rec.region_state(tree, CONTOUR, prior, upgrade) == 'upgrade' and rec.passes('upgrade')
    rec._write(tree, OVERVIEW, b'{"something": "else"}\n')
    assert rec.region_state(tree, CONTOUR, prior, upgrade) == 'unknown' and not rec.passes('unknown')


def test_contour_region_every_interruption_is_refused_and_restored_exactly(tmp_path):
    tree, _ = _tree(tmp_path)
    before = rec.snapshot(tree)
    upgrade = rec.synthetic_upgrade(tree, CONTOUR)
    got = rec.rehearse(tree, CONTOUR, tmp_path / 'work' / 'plan', upgrade)
    assert got['ok'] and got['final_exact'] and rec.snapshot(tree) == before
    assert got['untouched_files'] == 3 * 4 + 2 * 1
    states = [(s['step'], s['state'], s['passes']) for s in got['steps']]
    assert states == [('interrupted after 1/4', 'mixed', False), ('interrupted after 2/4', 'mixed', False),
                      ('interrupted after 3/4', 'mixed', False), ('complete upgrade', 'upgrade', True)]
    assert all(s['restored_exact'] and s['untouched_ok'] and s['restored_state'] == 'prior' for s in got['steps'])
    # The absent catalog contour stays absent through upgrade and restore (synthetic upgrade does not invent it).
    assert got['prior'][f'catalog/depth-contours/{CONTOUR}.geojson'] is None
    assert got['upgrade'][f'catalog/depth-contours/{CONTOUR}.geojson'] is None


def test_terrain_only_region_has_no_partial_state_and_restores(tmp_path):
    tree, _ = _tree(tmp_path)
    got = rec.rehearse(tree, TERRAIN, tmp_path / 'work' / 'plan', rec.synthetic_upgrade(tree, TERRAIN))
    assert got['ok'] and [s['step'] for s in got['steps']] == ['complete upgrade']


def test_upgrade_that_adds_a_file_restores_its_absence(tmp_path):
    tree, _ = _tree(tmp_path)
    upgrade = rec.synthetic_upgrade(tree, CONTOUR)
    added = f'catalog/depth-contours/{CONTOUR}.geojson'
    upgrade[added] = b'{"type": "FeatureCollection", "features": []}\n'
    got = rec.rehearse(tree, CONTOUR, tmp_path / 'work' / 'plan', upgrade)
    assert got['ok'] and not (tree / added).exists()
    assert got['steps'][-1]['restore_actions'][1] == 'remove'


def test_a_restore_that_does_not_restore_fails_the_rehearsal(tmp_path, monkeypatch):
    tree, _ = _tree(tmp_path)
    upgrade = rec.synthetic_upgrade(tree, CONTOUR)
    monkeypatch.setattr(rec.undo, 'restore', lambda plan, tree: {'actions': []})
    got = rec.rehearse(tree, CONTOUR, tmp_path / 'work' / 'plan', upgrade)
    assert not got['ok'] and not got['steps'][0]['restored_exact']


def test_identical_or_neighbor_upgrades_are_refused(tmp_path):
    tree, _ = _tree(tmp_path)
    same = {rel: (tree / rel).read_bytes() if (tree / rel).exists() else None for rel in undo.owned_paths(CONTOUR)}
    with pytest.raises(ValueError, match='identical'):
        rec.rehearse(tree, CONTOUR, tmp_path / 'work' / 'plan', same)
    up = tmp_path / 'up'
    (up / 'catalog' / 'relief').mkdir(parents=True)
    (up / 'catalog' / 'relief' / 'big-sur-coast.json').write_text('{}')
    with pytest.raises(ValueError, match='cannot own'):
        rec.upgrade_from_dir(up, CONTOUR)


def test_cli_writes_a_passing_receipt_once(tmp_path, capsys):
    bundle = _bundle(tmp_path)
    receipt = tmp_path / 'receipt.json'
    args = ['--bundle', str(bundle), '--region', CONTOUR, '--work', str(tmp_path / 'run'), '--receipt', str(receipt)]
    assert rec.main(args) == 0
    doc = json.loads(receipt.read_text())
    assert doc['ok'] and doc['synthetic_upgrade'] and doc['schema'] == rec.SCHEMA
    assert 'PASS cambria-san-simeon 4 steps' in capsys.readouterr().out
    assert rec.main(args) == 1  # work directory must be new
