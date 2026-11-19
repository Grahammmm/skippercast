"""F27-10: resume requires the exact pinned source and screening identity."""
import copy
import json
import sqlite3

import pytest

pytest.importorskip('numpy')
pytest.importorskip('rasterio')

from research.scripts import audit_nbs_hard_footprint_tiles as batch
from research.scripts import audit_nbs_modeling_tile as producer
from skippercast.seafloor.io import sha256


@pytest.fixture
def setup_tile(tmp_path, monkeypatch):
    scheme = tmp_path / 'scheme.gpkg'
    with sqlite3.connect(scheme) as db:
        db.execute('CREATE TABLE gpkg_contents (table_name TEXT, data_type TEXT)')
        db.execute("INSERT INTO gpkg_contents VALUES ('Modeling_Tile_Scheme_test', 'features')")
        db.execute('CREATE TABLE Modeling_Tile_Scheme_test (tile TEXT, GeoTIFF_Link TEXT, RAT_Link TEXT, GeoTIFF_SHA256_Checksum TEXT, RAT_SHA256_Checksum TEXT)')
        db.execute('INSERT INTO Modeling_Tile_Scheme_test VALUES (?, ?, ?, ?, ?)',
                   ('synthetic', 'raster', 'rat', 'a' * 64, 'b' * 64))
    receipts = tmp_path / 'receipts'
    receipts.mkdir()
    lead = {'tile': 'synthetic', 'coasts': [], 'planning_sector_ids': [], 'resolution': '4'}
    receipt = {'tile': 'synthetic', 'scheme_sha256': sha256(scheme),
               'raster_sha256': 'a' * 64, 'rat_sha256': 'b' * 64,
               'screen_method': producer.SCREEN_METHOD, 'screen': producer.screen_parameters(),
               'counts': {'qualified_screen_pixels': 7}}
    calls = []

    def audit(scheme_arg, tile, cache, *, fetch):
        calls.append((scheme_arg, tile, cache, fetch))
        return copy.deepcopy(receipt)

    monkeypatch.setattr(batch, 'audit', audit)
    return scheme, receipts, lead, receipt, calls


def run(setup_tile, old):
    scheme, receipts, lead, receipt, calls = setup_tile
    (receipts / 'synthetic.json').write_text(json.dumps(old))
    result = batch.run_one(lead, scheme, scheme.parent / 'cache', receipts, False)
    return result, json.loads((receipts / 'synthetic.json').read_text()), calls


def test_matching_receipt_reused_offline(setup_tile):
    # A matching receipt must not re-run the expensive tile audit or fetch.
    receipt = setup_tile[3]
    result, saved, calls = run(setup_tile, receipt)
    assert calls == []
    assert saved == receipt
    assert result['counts'] == receipt['counts']


@pytest.mark.parametrize('field,value', [
    ('screen', producer.screen_parameters(limit_ft=300)),
    ('screen', producer.screen_parameters(max_uncertainty_m=2.0)),
    ('screen', producer.screen_parameters(min_survey_year=1980)),
    ('screen_method', 'nbs-modeling-source-screen-v0'),
    ('screen_method', None),
    ('raster_sha256', 'c' * 64),
    ('rat_sha256', 'd' * 64),
    ('scheme_sha256', 'e' * 64),
    ('tile', 'other'),
])
def test_stale_receipt_rebuilt_offline(setup_tile, field, value):
    # A tile/scheme match alone must not reuse a 300-ft or obsolete screen.
    old = copy.deepcopy(setup_tile[3])
    old[field] = value
    result, saved, calls = run(setup_tile, old)
    assert len(calls) == 1 and calls[0][-1] is False
    assert saved == setup_tile[3]
    assert result['screen'] == producer.screen_parameters()


def test_failed_offline_rebuild_preserves_receipt(setup_tile, monkeypatch):
    scheme, receipts, lead, receipt, _ = setup_tile
    old = copy.deepcopy(receipt)
    old['screen'] = producer.screen_parameters(limit_ft=300)
    path = receipts / 'synthetic.json'
    path.write_text(json.dumps(old))

    def fail(*args, **kwargs):
        raise FileNotFoundError('synthetic cached source unavailable')

    monkeypatch.setattr(batch, 'audit', fail)
    with pytest.raises(FileNotFoundError):
        batch.run_one(lead, scheme, scheme.parent / 'cache', receipts, False)
    assert json.loads(path.read_text()) == old
