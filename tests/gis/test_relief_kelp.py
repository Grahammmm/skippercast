"""Planet fixture coverage, with real Tippecanoe replay via python -m tests.gis.test_relief_kelp."""
from datetime import date
import gzip
import hashlib
from io import BytesIO
import json
from pathlib import Path
import tempfile
from unittest.mock import patch
from zipfile import ZipFile

from pyproj import CRS, Transformer
import pytest
import shapefile
from shapely import transform
from shapely.geometry import Polygon, box, mapping, shape
from shapely.geometry.polygon import orient
from shapely.ops import unary_union

from skippercast.relief import kelp
from skippercast.seafloor.rough_first import _fields, _varint, read_tiles


YEAR = 2024
VERSION = '20000001'  # Synthetic replacement Zenodo version.
BASE = 'https://zenodo.org'
PAGE = f'{BASE}/records/{VERSION}'
NAME = '2024_09_PlanetDove_KelpPolygon.zip'
FILE = f'{BASE}/api/records/{VERSION}/files/{NAME}/content'
RIGHTS = '''<div id="licenses"><dl><dt>License</dt><dd>
<div>Creative Commons Attribution 4.0 International</div>
<div>The Creative Commons Attribution license allows re-distribution and re-use of a licensed
work on the condition that the creator is appropriately credited.
<a href="https://creativecommons.org/licenses/by/4.0/legalcode">Read more</a></div>
</dd></dl></div>'''
PROPERTIES = {'season': 'september', 'year': 2024, 'sensor': 'Planet 3 m'}
WATERS = box(-122.01, 36.99, -121.99, 37.01)
ISLAND = box(-122.004, 36.999, -122.003, 37.001)
HOLE = box(-122.007, 36.997, -122.006, 36.998)
SOURCE = Polygon(box(-122.02, 36.995, -122, 37.003).exterior.coords, [HOLE.exterior.coords])


def classification_zip(root, extra=None):
    path = root / NAME
    crs = CRS.from_epsg(26910)
    project = Transformer.from_crs(4326, crs, always_xy=True)
    with ZipFile(path, 'w') as archive:
        groups = {'KelpPresence': [SOURCE, box(-122.02, 37.015, -122.019, 37.016)],
                  'AreaSurveyed': [WATERS]}
        for layer, polygons in groups.items():
            base = root / f'{YEAR}_09_California_KelpCanopy_{layer}'
            with shapefile.Writer(str(base), shapeType=shapefile.POLYGON) as writer:
                writer.field('id', 'N')
                for i, polygon in enumerate(polygons):
                    projected = transform(polygon, project.transform, interleaved=False)
                    writer.shape(mapping(orient(projected, sign=-1)))
                    writer.record(i)
            base.with_suffix('.prj').write_text(crs.to_wkt())
            for suffix in ('.shp', '.shx', '.dbf', '.prj'):
                part = base.with_suffix(suffix)
                archive.write(part, f'classification/{part.name}')
        if extra:
            archive.writestr(extra, b'not a classification member')
    mask = root / 'waters.geojson'
    mask.write_text(json.dumps(mapping(WATERS.difference(ISLAND))))
    return path, mask


class FixtureZenodo:
    def __init__(self, archive, *, rights=RIGHTS, checksum=None, size_adjust=0, concept=None):
        data = archive.read_bytes()
        self.digest = hashlib.md5(data, usedforsecurity=False).hexdigest()
        self.size = len(data)
        entry = {'key': NAME, 'checksum': 'md5:' + (checksum or self.digest),
                 'size': self.size + size_adjust, 'links': {'self': 'https://example.test/never'}}
        self.responses = {
            f'{BASE}/api/records/17644635/versions/latest': json.dumps({
                'id': int(VERSION), 'conceptdoi': concept or '10.5281/zenodo.17644634',
                'metadata': {'license': {'id': 'cc-by-4.0'}},
                'files': [entry, {**entry, 'key': NAME.replace('2024_09', '2025_08')},
                          {**entry, 'key': NAME.replace('2024', '2023')}],
            }).encode(),
            PAGE: rights.encode(),
            FILE: data,
        }
        self.requests = []

    def open(self, url):
        self.requests.append(url)
        return BytesIO(self.responses[url])


def refresh(root, mask, zenodo, day):
    with patch.object(kelp, '_open', zenodo.open):
        return kelp.refresh_planet(archive_root=root / 'archives', out=root / 'out', waters=mask,
                                  receipt_dir=root / 'receipts', date=date(2026, 11, day))


def test_canopy_clips_without_filling_holes_or_survey_area(tmp_path):
    # A geographic-CRS assumption, rectangle clip or treating AreaSurveyed as canopy would fail.
    archive, mask = classification_zip(tmp_path)
    features = list(kelp.canopy_features(archive, YEAR, mask.read_bytes()))
    assert features and all(row['properties'] == PROPERTIES for row in features)
    actual = unary_union([shape(row['geometry']) for row in features])
    expected = SOURCE.intersection(WATERS.difference(ISLAND))
    assert actual.symmetric_difference(expected).area < 1e-10
    assert not actual.intersects(ISLAND.representative_point())
    assert not actual.intersects(HOLE.representative_point())


@pytest.mark.parametrize('change', ['text', 'extra term', 'license URL'])
def test_unapproved_rights_stop_before_any_archive(tmp_path, change):
    # A license badge/ID match alone would wrongly admit a changed Rights page.
    archive, mask = classification_zip(tmp_path)
    altered = {
        'text': RIGHTS.replace('Attribution 4.0', 'Attribution-NonCommercial 4.0'),
        'extra term': RIGHTS.replace('</dd>', 'No commercial use.</dd>'),
        'license URL': RIGHTS.replace('/by/4.0/', '/by-nc/4.0/'),
    }[change]
    zenodo = FixtureZenodo(archive, rights=altered)
    result = refresh(tmp_path, mask, zenodo, 18)
    assert result['status'] == 'rights_changed'
    assert result['rights_text']
    assert result['rights_text_sha256'] == hashlib.sha256(result['rights_text'].encode()).hexdigest()
    assert result['output_sha256'] is None and FILE not in zenodo.requests
    assert not (tmp_path / 'out').exists() and not (tmp_path / 'archives').exists()
    assert json.loads((tmp_path / 'receipts/2026-11-18-planet.json').read_text()) == result


@pytest.mark.parametrize('defect', ['md5', 'size', 'imagery', 'wrong concept'])
def test_bad_source_never_enters_archive_cache(tmp_path, defect):
    # Valid ZIP bytes with the wrong checksum/size must still fail, as must an unadmitted record/member.
    archive, mask = classification_zip(tmp_path, extra='imagery.tif' if defect == 'imagery' else None)
    zenodo = FixtureZenodo(archive, checksum='0' * 32 if defect == 'md5' else None,
                           size_adjust=-1 if defect == 'size' else 0,
                           concept='10.5281/zenodo.17717964' if defect == 'wrong concept' else None)
    receipt = refresh(tmp_path, mask, zenodo, 18)
    expected = {'md5': 'MD5 mismatch', 'size': 'size mismatch',
                'imagery': 'unexpected member', 'wrong concept': 'not a version'}
    assert receipt['status'] == 'access_failed' and expected[defect] in receipt['error']
    assert zenodo.requests.count(FILE) == (0 if defect == 'wrong concept' else 1)
    assert not (tmp_path / 'archives').exists()
    assert not (tmp_path / 'out').exists()


def _assert_mvt(archive):
    tiles = read_tiles(archive.read_bytes())
    assert tiles and set(z for z, _, _ in tiles) == {13, 14, 15, 16}
    count = 0
    for tile in tiles.values():
        for tag, payload in _fields(gzip.decompress(tile)):
            assert tag == 3
            layer = _fields(payload)
            assert (1, b'kelp') in layer
            keys = [v.decode() for k, v in layer if k == 3]
            values = [dict(_fields(v)) for k, v in layer if k == 4]
            for k, feature in layer:
                if k != 2:
                    continue
                row = dict(_fields(feature))
                assert row[3] == 3  # Polygon, not a positive point or absence polygon.
                tags, pos = [], 0
                while pos < len(row[2]):
                    value, pos = _varint(row[2], pos)
                    tags.append(value)
                props = {}
                for i, j in zip(tags[::2], tags[1::2], strict=True):
                    value = next(iter(values[j].values()))
                    props[keys[i]] = value.decode() if isinstance(value, bytes) else value
                assert props == PROPERTIES
                count += 1
    assert count
    return count


def fixture_pmtiles_acceptance(root):
    """Full offline integration (including the external tiler absent from survey CI)."""
    archive, mask = classification_zip(root)
    zenodo = FixtureZenodo(archive)
    first = refresh(root, mask, zenodo, 18)
    assert first['status'] == 'updated', first
    assert (first['version'], first['newest_september'], first['md5'], first['size']) == (
        VERSION, '2024-09', zenodo.digest, zenodo.size)
    output = root / 'out/_kelp/planet-2024/kelp.pmtiles'
    mirror = root / 'repeat' / 'kelp.pmtiles'
    digest = kelp.build_planet_pmtiles(archive, YEAR, mask.read_bytes(), mirror, VERSION)
    assert output.read_bytes() == mirror.read_bytes() and digest == first['output_sha256']
    count = _assert_mvt(output)
    zenodo.requests.clear()
    (root / 'receipts/2026-11-19-landsat.json').write_text('{"status":"access_failed"}')
    second = refresh(root, mask, zenodo, 19)
    assert second['status'] == 'no_change' and second['output_sha256'] == digest
    assert zenodo.requests == [kelp.LATEST, PAGE]
    assert json.loads((root / 'receipts/2026-11-19-planet.json').read_text()) == second
    zenodo.responses[PAGE] = RIGHTS.replace('Attribution 4.0', 'Attribution-NonCommercial 4.0').encode()
    stopped = refresh(root, mask, zenodo, 20)
    assert stopped['status'] == 'rights_changed' and stopped['output_sha256'] is None
    assert output.read_bytes() == mirror.read_bytes()  # Even an unchanged output cannot bypass rights.
    print(f'PASS fixture PMTiles byte-identical, MVT properties on {count} features; sha256={digest}')
    print('PASS updated -> no_change (independent of Landsat) -> rights_changed (last build untouched)')


if __name__ == '__main__':
    with tempfile.TemporaryDirectory(prefix='kelp-acceptance-') as tmp:
        fixture_pmtiles_acceptance(Path(tmp))
