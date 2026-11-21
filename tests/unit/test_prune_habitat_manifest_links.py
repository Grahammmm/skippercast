"""Manifest leaf checks for the habitat tile pruner (GS4A-17)."""
import importlib.util
import json

import pytest

from tests._support import ROOT

spec = importlib.util.spec_from_file_location(
    'prune_habitat_tiles', ROOT / 'scripts/prune_habitat_tiles.py'
)
assert spec is not None and spec.loader is not None
pruner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pruner)

MANIFEST = 'habitat-dynamics.json'
TILES = tuple(f'sst-analysis--242-70-{n:016x}.json' for n in range(3))


def _region(published, incoming, ident):
    for root, name in ((published, TILES[1]), (incoming, TILES[2])):
        region = root / 'regions' / ident
        region.mkdir(parents=True)
        (region / MANIFEST).write_text(json.dumps({
            'schema_version': 1,
            'region_id': ident,
            'layers': {'sst-analysis': {'tiles': [{'path': f'habitat-tiles/{name}'}]}},
        }))
    tiles = published / 'regions' / ident / 'habitat-tiles'
    tiles.mkdir()
    for name in TILES:
        (tiles / name).write_text('{}')
    return tiles


@pytest.mark.parametrize('side', ['incoming', 'published'])
@pytest.mark.parametrize('dangling', [False, True], ids=['existing-target', 'dangling'])
def test_manifest_link_in_later_region_refuses_before_any_delete(tmp_path, side, dangling):
    published, incoming = tmp_path / 'published', tmp_path / 'incoming'
    alpha_tiles = _region(published, incoming, 'alpha-bay')
    beta_tiles = _region(published, incoming, 'beta-bay')
    manifest = tmp_path / side / 'regions' / 'beta-bay' / MANIFEST
    link_target = tmp_path / 'elsewhere.json'
    if dangling:
        manifest.unlink()
    else:
        manifest.rename(link_target)  # Valid JSON: parsing alone would accept it.
    manifest.symlink_to(link_target)

    # A dangling leaf must not look absent, and a later refusal must not
    # apply the stale-tile deletions already planned for alpha-bay.
    with pytest.raises(ValueError, match=r'Habitat manifest is a link: beta-bay/habitat-dynamics\.json'):
        pruner.prune(published, incoming)
    assert {path.name for path in alpha_tiles.iterdir()} == set(TILES)
    assert {path.name for path in beta_tiles.iterdir()} == set(TILES)


def test_absent_outgoing_manifest_allows_first_publication_prune(tmp_path):
    published, incoming = tmp_path / 'published', tmp_path / 'incoming'
    tiles = _region(published, incoming, 'alpha-bay')
    (tiles.parent / MANIFEST).unlink()

    # Refusing links must not turn a genuinely absent manifest into an error.
    assert pruner.prune(published, incoming) == 2
    assert {path.name for path in tiles.iterdir()} == {TILES[2]}
