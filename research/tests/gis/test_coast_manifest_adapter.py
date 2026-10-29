"""Exercise the adapter against actual C2 synthetic hole/boundary/bowl output."""
import hashlib
import json

import pytest

from research.scripts.coast_mvp import coast_manifest
from research.tests.test_coast_mvp_contours import make_rasters, stack  # shared synthetic GIS fixtures


@pytest.mark.parametrize('kind,hole,boundary,buffer_case', [
    ('gradient', True, True, False), ('bowl', False, False, False),
    ('bowl', True, True, False), ('gradient', True, True, True)])
def test_actual_c2_topology_and_assets_unchanged(make_rasters, stack, kind, hole, boundary, buffer_case):
    np, rio, from_origin, *_, c2 = stack
    directory = make_rasters(kind, hole=hole, boundary=boundary)
    if buffer_case:
        for name in ('elevation', 'contributor'):
            with rio.open(directory / f'{name}.tif', 'r+') as grid:
                grid.transform = from_origin(-150000, -98960, 40, 40)
    c1 = json.loads((directory / 'sources.json').read_text())
    with rio.open(directory / 'contributor.tif') as grid:
        codes = grid.read(1)
    counts = {str(row['code']): int(np.count_nonzero(codes == row['code'])) for row in c1['sources']}
    c1.update(schema_version=1, units='m', value_convention='elevation_positive_up',
              fixture_only=True, contributor_cells=counts, stats={'valid_cells': sum(counts.values())})
    rights = dict(schema_version=1, fixture_only=True, sources=[])
    for row in c1['sources']:
        row.update(sha256='a' * 64, vertical_datum='unstated', offset_note='Synthetic zero only',
                   citation='https://example.org/synthetic', rights='Synthetic fixture; not a survey',
                   attribution='Synthetic test author')
        rights['sources'].append(dict(
            source_id=row['id'], name=row['id'], source_url=row['citation'], sha256=row['sha256'],
            contributed_cells=counts[str(row['code'])], rights=dict(
                license=row['rights'], terms_url='https://example.org/terms',
                attribution=row['attribution'], csumb_involved=False)))
    native = directory / 'native.json'
    inventory = directory / 'rights.json'
    native.write_text(json.dumps(c1))
    inventory.write_text(json.dumps(rights))
    output = directory / 'output'
    c2.build(directory / 'elevation.tif', directory / 'contributor.tif', native, output,
             zoom=12 if buffer_case else 14)
    if buffer_case:
        assert {p.relative_to(output).as_posix() for p in output.rglob('*.png')} == {
            'terrain/12/663/1592.png'}
        assert {p.relative_to(output).as_posix() for p in output.rglob('*.pbf')} == {
            'vector/12/663/1592.pbf', 'vector/12/663/1593.pbf'}
    before = {p.relative_to(output).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
              for p in output.rglob('*') if p.is_file()}
    manifest = coast_manifest.build(output, native, inventory, region='Synthetic GIS fixture', synthetic=True)
    for relative, sha in before.items():
        assert hashlib.sha256((output / relative).read_bytes()).hexdigest() == sha
    assert len(manifest['sources']) == sum(count > 0 for count in counts.values())
    assert manifest['synthetic'] is True and manifest['publicationHeld']
    assert manifest['provenance']['contoursSha256'] == before['contours.geojson']
    assert all(relative in before for relative in manifest['provenance']['assets'])
    if buffer_case:
        assert 'vector/12/663/1592.pbf' in manifest['provenance']['assets']
        assert 'vector/12/663/1593.pbf' not in manifest['provenance']['assets']


def test_actual_c2_at_64_tile_cap_with_buffer_ring(tmp_path, stack):
    """C2's own 64-terrain-tile cap plus GDAL's MVT ring must still be admitted."""
    np, rio, from_origin, *_, c2 = stack
    world, zoom, size, cell = 20037508.342789244, 14, 488, 40
    span = 2 * world / 2**zoom
    # Origin just inside tile (2700, 6300): 488 x 40 m cells cover exactly 8 x 8 tiles.
    west, north = -world + 2700 * span + 20, world - 6300 * span - 20
    _, xx = np.indices((size, size))
    elevation = (-(xx * 1000 / (size - 1)) * 0.3048).astype('float32')
    codes = np.ones((size, size), dtype='uint16')
    profile = dict(driver='GTiff', width=size, height=size, count=1, crs='EPSG:3857',
                   transform=from_origin(west, north, cell, cell))
    for name, data, nodata in [('elevation', elevation, -999999), ('contributor', codes, 0)]:
        with rio.open(tmp_path / f'{name}.tif', 'w', dtype=data.dtype, nodata=nodata, **profile) as grid:
            grid.write(data, 1)
    source = dict(code=1, id='synthetic-a', resolution_m=40.0, sha256='a' * 64,
                  vertical_datum='unstated', offset_note='Synthetic zero only',
                  citation='https://example.org/synthetic', rights='Synthetic fixture; not a survey',
                  attribution='Synthetic test author')
    native, inventory, output = tmp_path / 'native.json', tmp_path / 'rights.json', tmp_path / 'output'
    native.write_text(json.dumps(dict(
        schema_version=1, units='m', value_convention='elevation_positive_up', fixture_only=True,
        sources=[source], contributor_cells={'1': size * size}, stats={'valid_cells': size * size})))
    inventory.write_text(json.dumps(dict(schema_version=1, fixture_only=True, sources=[dict(
        source_id=source['id'], name=source['id'], source_url=source['citation'], sha256=source['sha256'],
        contributed_cells=size * size, rights=dict(
            license=source['rights'], terms_url='https://example.org/terms',
            attribution=source['attribution'], csumb_involved=False))])))
    c2.build(tmp_path / 'elevation.tif', tmp_path / 'contributor.tif', native, output, zoom=zoom)
    xyz = lambda p: tuple(map(int, p.relative_to(output).as_posix()[:-4].split('/')[2:]))
    terrain = {xyz(p) for p in output.rglob('*.png')}
    vector = {p.relative_to(output).as_posix(): xyz(p) for p in output.rglob('*.pbf')}
    assert terrain == {(x, y) for x in range(2700, 2708) for y in range(6300, 6308)}
    ring = {path for path, tile in vector.items() if tile not in terrain}
    assert ring and len(vector) > 64  # the case the shared 64 cap used to refuse
    before = {p.relative_to(output).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
              for p in output.rglob('*') if p.is_file()}
    manifest = coast_manifest.build(output, native, inventory, region='Synthetic 64-tile cap', synthetic=True)
    assets = manifest['provenance']['assets']
    assert {path for path in assets if path.startswith('vector/')} == set(vector) - ring
    assert len([path for path in assets if path.startswith('vector/')]) == 64
    assert not ring & set(assets)
    for relative, sha in before.items():
        assert hashlib.sha256((output / relative).read_bytes()).hexdigest() == sha
