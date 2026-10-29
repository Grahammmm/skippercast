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
