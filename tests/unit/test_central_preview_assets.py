"""Preview transport scope is separate from the already tested C47 producer."""
import json

import pytest

from scripts.relief import central_preview_assets as preview
from skippercast.relief import receipts


def identity(tmp_path, regions, *, purpose='offline-preview-only'):
    path = tmp_path / 'identity.json'
    raw = receipts.canonical({'schema': preview.identities.SCHEMA, 'purpose': purpose,
                              'regions': {name: {} for name in regions}})
    path.write_bytes(raw)
    return path, receipts.sha256_bytes(raw)


def test_intake_refuses_stale_or_foreign_manifest_before_artifact_access(tmp_path):
    # A caller can point at a different plausible manifest or a Morro substitution.
    names = sorted(preview.identities.REGIONS)
    path, sha = identity(tmp_path, names)
    assert set(preview.read_identities(path, sha)) == set(names)
    with pytest.raises(ValueError, match='bytes differ from pin'):
        preview.read_identities(path, '0' * 64)
    path, sha = identity(tmp_path, ['morro-bay', *names[1:]])
    with pytest.raises(ValueError, match='exact six Central'):
        preview.read_identities(path, sha)
    path, sha = identity(tmp_path, names, purpose='release')
    with pytest.raises(ValueError, match='exact six Central'):
        preview.read_identities(path, sha)


def test_index_lists_only_the_preview_pair_and_keeps_terrain_only_clear(tmp_path):
    # Copying valid files alone previously produced an untouched index and zero browser requests.
    contour, terrain = 'cambria-san-simeon', 'monterey-point-sur'
    regions = {contour: {}, terrain: {}}
    overlay = {f'/regions/{contour}/{name}': b'x' for name in preview.tree.CONTOURS.values()}
    entries = [{'id': name, 'config': f'regions/{name}/region.json', 'manifest': 'stale'}
               for name in [contour, terrain, 'morro-bay']]
    preview.write(tmp_path, 'dist/regions/index.json', receipts.canonical({'regions': entries, 'default_region': 'morro-bay'}))
    for region in regions:
        listed = ['coastline.geojson'] + list(preview.tree.CONTOURS.values()) * (region == terrain)
        preview.write(tmp_path, f'dist/regions/{region}/region.json', receipts.canonical({'id': region, 'chart_files': listed}))
    preview.project_indexes(tmp_path, regions, overlay)
    index = json.loads((tmp_path / 'dist/regions/index.json').read_bytes())
    assert [row['id'] for row in index['regions']] == [contour, terrain]
    assert index['default_region'] == contour
    for row in index['regions']:
        raw = (tmp_path / 'dist' / row['config']).read_bytes()
        assert row['manifest'] == receipts.sha256_bytes(raw)
        assert set(json.loads(raw)['chart_files']) == ({'coastline.geojson'} |
            (set(preview.tree.CONTOURS.values()) if row['id'] == contour else set()))


def test_output_checkout_refused_before_opening_any_input(tmp_path):
    # An accidentally supplied release checkout must not gain preview artifacts, even temporarily.
    (tmp_path / '.git').write_text('gitdir: elsewhere')
    out = tmp_path / 'local-preview'
    with pytest.raises(ValueError, match='inside a git checkout'):
        preview.assemble(None, None, None, None, None, None, None, out)
    assert not out.exists()
