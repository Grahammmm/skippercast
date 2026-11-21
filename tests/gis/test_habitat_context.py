"""Offline producer proof with synthetic native sources and the real region CLI."""
import hashlib
import io
import json
import os
import subprocess
import sys
import tarfile
from zipfile import ZipFile

import numpy as np
from pyproj import CRS, Transformer
import pytest
import rasterio
import shapefile
from shapely import transform
from shapely.geometry import Point, box, mapping, shape
from shapely.geometry.polygon import orient

from tests._support import ROOT

REGION = 'fixture-coast'
WAVE = 'usgs-of2005-1170-nanphab'
DS3091 = 'cdfw-ds3091-predicted-substrate'
KELP = 'cdfw-kelp-2016'


def write_json(path, doc):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc), encoding='utf-8')
    return path


def feature(geom, **props):
    return {'type': 'Feature', 'geometry': mapping(geom), 'properties': props}


def collection(*features):
    return {'type': 'FeatureCollection', 'region_id': REGION, 'features': features}


@pytest.fixture
def case(tmp_path):
    cfg = tmp_path / 'repo'
    out = tmp_path / 'out'
    archive = tmp_path / 'usgs_of2005_1170' / WAVE / 'nanphab.tgz'
    archive.parent.mkdir(parents=True)
    wgs_to_utm = Transformer.from_crs(4326, 26910, always_xy=True).transform
    streams = {key: io.BytesIO() for key in ('shp', 'dbf', 'shx')}
    with shapefile.Writer(**streams, shapeType=shapefile.POLYGON) as writer:
        writer.field('BOTTOM_ID', 'C', size=4)
        writer.field('CODE', 'C', size=12)
        for i, (bottom, code) in enumerate([('h', 'Sh'), ('m', 'Sm'), ('s', 'Ss'), ('s', 'surprise')]):
            west = -121 + 0.05 * i
            polygon = orient(transform(box(west, 35.1, west + 0.02, 35.12), wgs_to_utm, interleaved=False), sign=-1)
            writer.shape(mapping(polygon))
            writer.record(bottom, code)
    with tarfile.open(archive, 'w:gz') as tf:
        members = {key: stream.getvalue() for key, stream in streams.items()}
        members['prj'] = CRS.from_epsg(26910).to_wkt().encode()
        for suffix, raw in members.items():
            member = tarfile.TarInfo(f'nanphab.{suffix}')
            member.size = len(raw)
            tf.addfile(member, io.BytesIO(raw))
    qualification = write_json(tmp_path / 'qualification.json', {'schema': 'habitat-2a-qualify/1', 'rows': [{
        'wave2a_id': WAVE, 'sha256': hashlib.sha256(archive.read_bytes()).hexdigest(), 'geometry': 'POLYGON',
        'epsg': 26910, 'usable_as': 'measured habitat classes (synthetic)', 'survey_dates': '20000612-20000718',
        'bottom_id_counts_by_code': {'Sh': ['h'], 'Sm': ['m'], 'Ss': ['s']},
    }]})

    tif = tmp_path / 'native.tif'
    # Region cuts through the first cell; extra classes and nodata must remain blank.
    with rasterio.open(tif, 'w', driver='GTiff', width=5, height=1, count=1, dtype='uint8', crs='EPSG:4326',
                       transform=rasterio.Affine(0.2, 0, -121.3, 0, -0.2, 35.0), nodata=0) as ds:
        ds.write(np.array([[1, 2, 0, 9, 1]], dtype='uint8'), 1)
        ds.write_mask(np.array([[255, 255, 255, 255, 0]], dtype='uint8'))
    raster = tmp_path / 'ds3091.zip'
    with ZipFile(raster, 'w') as zf:
        zf.write(tif, 'v1_final/tiff/ds3091.tif')

    kelp = dict(source_id=KELP, habitat_kind='kelp', evidence_kind='historical-habitat-context',
                source_date='2016-09-03 to 2016-09-25', native_source_codes=['Kelp Canopy'], fishing_target=False)
    write_json(cfg / 'dist/regions/southern-california/survey-habitat.geojson', collection(
        feature(box(-120.5, 34.9, -120.4, 35.0), **kelp),
        feature(box(-120.5, 35.2, -120.4, 35.3), **kelp, military_access='unverified'),
        feature(box(-119.5, 33.17, -119.4, 33.20), **kelp),  # no hold flag; geometry is inside San Nicolas
        feature(box(-118.6, 32.8, -118.5, 32.9), **kelp),   # inside San Clemente
    ))
    write_json(cfg / 'regions' / REGION / 'region.json', {'id': REGION, 'bounds': [-121.2, 32.55, -118.1, 35.5]})
    military = json.loads((ROOT / 'regions/outer-islands-borderland/region.json').read_bytes())
    write_json(cfg / 'regions/outer-islands-borderland/region.json', military)
    closure = box(-121.19, 34.85, -121.15, 34.95)
    exclusions = write_json(tmp_path / 'exclusions.geojson', collection(feature(closure)))
    rights = {'public_display': 'allowed', 'commercial_use': 'allowed', 'license': 'CC-BY-4.0',
              'attribution': 'Synthetic attribution', 'terms_url': 'https://example.test/terms'}
    catalog = {'sources': [{'id': sid, 'name': sid, 'review_status': 'approved', 'rights': dict(rights)}
                           for sid in (WAVE, DS3091, KELP)]}
    catalog_path = write_json(cfg / 'catalog/sources.json', catalog)

    def run(*extra):
        return subprocess.run([sys.executable, str(ROOT / 'scripts/relief/region.py'), 'habitat-context',
                               '--out', str(out), '--region', REGION, '--exclusions', str(exclusions),
                               '--wave-root', str(tmp_path), '--wave-layer', 'nanphab',
                               '--wave-qualification', str(qualification), '--ds3091', str(raster),
                               '--ds3091-sha256', hashlib.sha256(raster.read_bytes()).hexdigest(),
                               '--historical-kelp', *extra], cwd=ROOT, capture_output=True, text=True,
                              env={**os.environ, 'SKIPPERCAST_ROOT': str(cfg)}, check=False)

    region = out / REGION
    return (run, catalog, catalog_path, region / 'stages/habitat_context.json',
            region / 'layers/public/habitat/survey-habitat.geojson')


def test_builds_all_three_evidence_classes_with_region_and_policy_masks(case):
    run, _, _, receipt_path, asset = case
    first = run()
    assert first.returncode == 0, first.stdout + first.stderr
    raw = asset.read_bytes()
    doc = json.loads(raw)
    assert doc['layer'] == 'habitat' and doc['region_id'] == REGION
    props = [f['properties'] for f in doc['features']]
    assert sorted((p['evidence_class'], p['habitat_kind']) for p in props) == [
        ('historical', 'kelp'), ('measured', 'mixed'), ('measured', 'rock'), ('measured', 'sediment'),
        ('predicted', 'rock'), ('predicted', 'sediment'),
    ]
    assert {p['source_class'] for p in props if p['evidence_class'] == 'predicted'} == {'hard', 'soft'}
    assert all(p['fishing_target'] is p['fishing_export'] is p['depth_qualified'] is False for p in props)
    assert {row['id'] for row in doc['sources']} == {WAVE, DS3091, KELP}
    assert all(row['rights']['attribution'] == 'Synthetic attribution' for row in doc['sources'])
    polygons = [shape(f['geometry']) for f in doc['features']]
    assert all(g.is_valid and g.bounds[0] >= -121.2 for g in polygons)
    assert any(g.contains(Point(-121.18, 34.97)) for g in polygons)  # real remainder of first raster cell
    for excluded in [(-121.18, 34.9), (-120.45, 35.25), (-119.45, 33.18), (-118.55, 32.85)]:
        assert not any(g.covers(Point(*excluded)) for g in polygons)
    receipt = json.loads(receipt_path.read_bytes())
    assert receipt['status'] == 'ok'
    assert receipt['outputs'] == [{
        'path': 'layers/public/habitat/survey-habitat.geojson',
        'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
    }]
    second = run()
    assert second.returncode == 0 and 'DONE' in second.stdout, second.stdout + second.stderr
    asset.write_bytes(b'tampered')
    rebuilt = run()
    assert rebuilt.returncode == 0 and 'OK' in rebuilt.stdout, rebuilt.stdout + rebuilt.stderr
    assert asset.read_bytes() == raw
    assert json.loads(receipt_path.read_bytes())['generation'] == receipt['generation']


@pytest.mark.parametrize('display', [None, 'private'])
def test_missing_and_private_rights_hold_generation(case, display):
    run, catalog, catalog_path, receipt_path, asset = case
    rights = catalog['sources'][1]['rights']
    if display is None:
        rights.pop('public_display')
    else:
        rights['public_display'] = display
    write_json(catalog_path, catalog)
    result = run()
    assert result.returncode == 4, result.stdout + result.stderr
    receipt = json.loads(receipt_path.read_bytes())
    assert receipt['status'] == 'held' and DS3091 in receipt['held_reason']
    assert not asset.exists() and not receipt['outputs']


def test_ds3091_pin_is_not_an_advisory_label(case):
    run, _, _, receipt_path, asset = case
    result = run('--ds3091-sha256', 'a' * 64)
    assert result.returncode == 4 and 'does not match the reviewed hash' in result.stdout
    assert not asset.exists() and not json.loads(receipt_path.read_bytes())['outputs']
