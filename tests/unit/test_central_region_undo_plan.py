"""Central per-region undo plan: exact prior bytes, one region only, disposable trees only."""
import json
import os

import pytest

from scripts.relief import central_region_undo_plan as undo
from scripts.relief import central_stage_handoff

CONTOUR = 'cambria-san-simeon'
TERRAIN = 'monterey-point-sur'
NEIGHBOR = 'big-sur-coast'


def _write(tree, rel, data):
    path = tree / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def _make_tree(tmp_path, name='tree'):
    tree = tmp_path / name
    tree.mkdir()
    (tree / undo.MARKER).write_text(undo.MARKER_TEXT + '\n')
    for region in undo.REGIONS:  # every region has bytes of its own so a stray write shows
        for rel in undo.owned_paths(region):
            _write(tree, rel, f'old {rel}'.encode())
    _write(tree, f'dist/regions/{CONTOUR}/region.json', b'region file, never owned')
    return tree


def _snapshot(tree):
    return {p.relative_to(tree).as_posix(): p.read_bytes() for p in sorted(tree.rglob('*')) if p.is_file()}


def _apply_release(tree, region):
    """Stand-in for a data PR landing: overwrite or create every owned file."""
    for rel in undo.owned_paths(region):
        _write(tree, rel, b'NEW ' + rel.encode())


def test_regions_match_stage_handoff_and_kinds():
    assert undo.REGIONS == tuple(sorted(undo.REGIONS, key=undo.REGIONS.index))
    assert set(undo.REGIONS) == set(central_stage_handoff.CENTRAL_RELEASES)
    assert len(undo.owned_paths(CONTOUR)) == 4 and undo.kind(CONTOUR) == 'terrain+contours'
    assert undo.owned_paths(TERRAIN) == (f'catalog/relief/{TERRAIN}.json',) and undo.kind(TERRAIN) == 'terrain-only'
    with pytest.raises(ValueError):
        undo.owned_paths('morro-bay')


@pytest.mark.parametrize('region', [CONTOUR, TERRAIN])
def test_round_trip_is_byte_exact_and_leaves_neighbors(tmp_path, region):
    tree = _make_tree(tmp_path)
    before = _snapshot(tree)
    doc = undo.make_plan(tree, region, tmp_path / 'plan')
    assert [r['state'] for r in doc['paths']] == ['present'] * len(undo.owned_paths(region))
    assert _snapshot(tree) == before  # planning never writes the tree
    _apply_release(tree, region)
    _write(tree, f'dist/regions/{NEIGHBOR}/depth-contours.geojson', b'neighbor changed later by someone else')
    expect = dict(before)
    expect[f'dist/regions/{NEIGHBOR}/depth-contours.geojson'] = b'neighbor changed later by someone else'
    # a neighbor edit after the release is not this region's undo: restore must leave it alone
    out = undo.restore(tmp_path / 'plan' / 'undo-plan.json', tree)
    assert _snapshot(tree) == expect
    assert out['neighbors_unchanged'] is True and out['region'] == region


def test_first_release_prior_absence_removes_files_and_new_dirs(tmp_path):
    tree = tmp_path / 'tree'
    tree.mkdir()
    (tree / undo.MARKER).write_text(undo.MARKER_TEXT)
    _write(tree, 'dist/regions/point-arguello-conception/region.json', b'x')
    region = 'point-arguello-conception'
    doc = undo.make_plan(tree, region, tmp_path / 'plan')
    assert {r['state'] for r in doc['paths']} == {'absent'}
    assert 'catalog/relief' in doc['absent_parent_dirs'] and 'catalog/depth-contours' in doc['absent_parent_dirs']
    before = _snapshot(tree)
    _apply_release(tree, region)
    undo.restore(tmp_path / 'plan' / 'undo-plan.json', tree)
    assert _snapshot(tree) == before
    assert not (tree / 'catalog').exists() or not any((tree / 'catalog').iterdir())
    assert (tree / 'dist/regions' / region).is_dir()  # the region directory itself is never removed


def test_restore_is_idempotent_and_dry_run_writes_nothing(tmp_path):
    tree = _make_tree(tmp_path)
    undo.make_plan(tree, CONTOUR, tmp_path / 'plan')
    _apply_release(tree, CONTOUR)
    changed = _snapshot(tree)
    dry = undo.restore(tmp_path / 'plan' / 'undo-plan.json', tree, dry_run=True)
    assert _snapshot(tree) == changed and {a['action'] for a in dry['actions']} == {'rewrite'}
    undo.restore(tmp_path / 'plan' / 'undo-plan.json', tree)
    again = undo.restore(tmp_path / 'plan' / 'undo-plan.json', tree)
    assert {a['action'] for a in again['actions']} == {'unchanged'}


def test_modes_are_restored(tmp_path):
    tree = _make_tree(tmp_path)
    target = tree / f'catalog/relief/{TERRAIN}.json'
    os.chmod(target, 0o640)
    undo.make_plan(tree, TERRAIN, tmp_path / 'plan')
    target.write_bytes(b'new')
    os.chmod(target, 0o600)
    undo.restore(tmp_path / 'plan' / 'undo-plan.json', tree)
    assert target.stat().st_mode & 0o777 == 0o640


def _plan(tmp_path, region=CONTOUR):
    tree = _make_tree(tmp_path)
    undo.make_plan(tree, region, tmp_path / 'plan')
    return tree, tmp_path / 'plan' / 'undo-plan.json'


def _edit(plan_file, mutate, *, resign=True):
    doc = json.loads(plan_file.read_text())
    mutate(doc)
    if resign:
        doc['plan_sha256'] = undo._plan_digest(doc)
    plan_file.write_bytes(undo._canonical(doc))


def test_neighbor_path_in_plan_is_refused_even_when_resigned(tmp_path):
    tree, plan = _plan(tmp_path)
    _edit(plan, lambda d: d['paths'][0].update(path=f'catalog/relief/{NEIGHBOR}.json', prior=f'prior/catalog/relief/{NEIGHBOR}.json'))
    with pytest.raises(ValueError, match='owned set'):
        undo.restore(plan, tree)
    _edit(plan, lambda d: d['paths'].append(dict(path='dist/regions/x/region.json', state='absent')))
    with pytest.raises(ValueError, match='owned set'):
        undo.restore(plan, tree)


def test_traversal_and_edited_plan_refused(tmp_path):
    tree, plan = _plan(tmp_path)
    _edit(plan, lambda d: d['paths'][0].update(path='../x'), resign=True)
    with pytest.raises(ValueError):
        undo.restore(plan, tree)
    tree2 = _make_tree(tmp_path, 'tree2')
    undo.make_plan(tree2, TERRAIN, tmp_path / 'plan2')
    _edit(tmp_path / 'plan2' / 'undo-plan.json', lambda d: d.update(region=CONTOUR), resign=False)
    with pytest.raises(ValueError, match='digest|kind'):
        undo.restore(tmp_path / 'plan2' / 'undo-plan.json', tree2)


def test_tampered_prior_bytes_refused_before_any_write(tmp_path):
    tree, plan = _plan(tmp_path)
    _apply_release(tree, CONTOUR)
    changed = _snapshot(tree)
    (plan.parent / 'prior' / f'catalog/relief/{CONTOUR}.json').write_bytes(b'tampered')
    with pytest.raises(ValueError, match='prior bytes'):
        undo.restore(plan, tree)
    assert _snapshot(tree) == changed


def test_unknown_region_and_wrong_schema_refused(tmp_path):
    tree = _make_tree(tmp_path)
    with pytest.raises(ValueError):
        undo.make_plan(tree, 'morro-bay', tmp_path / 'plan')
    tree2 = _make_tree(tmp_path, 'tree2')
    undo.make_plan(tree2, TERRAIN, tmp_path / 'plan-t')
    plan = tmp_path / 'plan-t' / 'undo-plan.json'
    _edit(plan, lambda d: d.update(schema='other/1'))
    with pytest.raises(ValueError, match='undo-plan'):
        undo.load_plan(plan)


def test_checkout_unmarked_home_and_symlink_trees_refused(tmp_path):
    tree, plan = _plan(tmp_path)
    (tree / '.git').mkdir()
    with pytest.raises(ValueError, match='git checkout'):
        undo.restore(plan, tree)
    (tree / '.git').rmdir()
    (tree / undo.MARKER).unlink()
    with pytest.raises(ValueError, match='disposable'):
        undo.restore(plan, tree)
    (tree / undo.MARKER).write_text('something else')
    with pytest.raises(ValueError, match='disposable'):
        undo.restore(plan, tree)
    link = tmp_path / 'link'
    link.symlink_to(tree)
    with pytest.raises(ValueError, match='symlink'):
        undo.restore(plan, link)


def test_symlinked_owned_file_or_parent_refused_and_nothing_written(tmp_path):
    tree, plan = _plan(tmp_path)
    outside = tmp_path / 'outside.json'
    outside.write_bytes(b'precious')
    target = tree / f'catalog/relief/{CONTOUR}.json'
    target.unlink()
    target.symlink_to(outside)
    with pytest.raises(ValueError, match='symlink'):
        undo.restore(plan, tree)
    assert outside.read_bytes() == b'precious'
    with pytest.raises(ValueError, match='symlink'):
        undo.make_plan(tree, CONTOUR, tmp_path / 'plan-b')


def test_plan_dir_must_be_outside_tree_and_new(tmp_path):
    tree = _make_tree(tmp_path)
    with pytest.raises(ValueError, match='outside'):
        undo.make_plan(tree, CONTOUR, tree / 'plan')
    (tmp_path / 'full').mkdir()
    (tmp_path / 'full' / 'x').write_text('x')
    with pytest.raises(ValueError, match='new or empty'):
        undo.make_plan(tree, CONTOUR, tmp_path / 'full')
    tree3 = _make_tree(tmp_path, 'tree3')
    undo.make_plan(tree3, CONTOUR, tmp_path / 'plan-m')
    plan = tmp_path / 'plan-m' / 'undo-plan.json'
    inside = tree / 'moved-plan'
    inside.mkdir()
    for p in plan.parent.rglob('*'):
        if p.is_file():
            _write(inside, p.relative_to(plan.parent).as_posix(), p.read_bytes())
    with pytest.raises(ValueError, match='outside'):
        undo.restore(inside / 'undo-plan.json', tree)


def test_cli_plan_then_restore(tmp_path, capsys):
    tree = _make_tree(tmp_path)
    assert undo.main(['plan', '--tree', str(tree), '--region', TERRAIN, '--out', str(tmp_path / 'p')]) == 0
    _apply_release(tree, TERRAIN)
    assert undo.main(['restore', '--plan', str(tmp_path / 'p/undo-plan.json'), '--tree', str(tree)]) == 0
    assert (tree / f'catalog/relief/{TERRAIN}.json').read_bytes() == f'old catalog/relief/{TERRAIN}.json'.encode()
    assert undo.main(['restore', '--plan', str(tmp_path / 'p/undo-plan.json'), '--tree', str(tmp_path / 'nope')]) == 1
    assert 'error:' in capsys.readouterr().err
