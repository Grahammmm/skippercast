"""Inventory reads only file-backed PMTiles metadata and requires unambiguous JSON."""

import io
import json
import struct
from types import SimpleNamespace

import pytest

from skippercast.relief import inventory, package
from skippercast.relief.inventory import InventoryError, archive_metadata
from skippercast.relief.pmtiles_v3 import write_pmtiles


def _archive(path, payload, *, offset=127, length=None, compression=1, zooms=(0, 0)):
    header = bytearray(127)
    header[:8] = b'PMTiles\x03'
    struct.pack_into('<QQ', header, 24, offset, len(payload) if length is None else length)
    header[97] = compression
    header[100:102] = bytes(zooms)
    path.write_bytes(header + payload)
    return path


@pytest.mark.parametrize(('offset', 'length'), [(126, 2), (130, 1), (127, 3)],
                         ids=['header-overlap', 'start-past-eof', 'end-past-eof'])
def test_invalid_span_refused_before_payload_read(tmp_path, offset, length):
    path = _archive(tmp_path / 'relief.pmtiles', b'{}', offset=offset, length=length)

    class HeaderOnly(io.FileIO):
        def read(self, size: int | None = -1, /):
            # Reject a read-then-check implementation, even if it raises InventoryError later.
            assert self.tell() == 0 and size == 127, 'attempted to read the invalid payload'
            return super().read(size)

    with pytest.raises(InventoryError, match='metadata span'):
        archive_metadata(SimpleNamespace(open=lambda mode: HeaderOnly(path, mode)))


def test_duplicate_metadata_members_refused(tmp_path):
    # Ordinary json.loads silently takes the last value, including in nested support records.
    path = _archive(tmp_path / 'relief.pmtiles', b'{"support":{"tiles":1,"tiles":2}}')
    with pytest.raises(InventoryError, match='duplicate JSON member'):
        archive_metadata(path)


def test_writer_metadata_round_trips(tmp_path):
    # Preserve the writer's gzip path and nested, non-ASCII metadata without normalization.
    bounds = (-1.0, -1.0, 1.0, 1.0)
    metadata = {'bounds': list(bounds), 'minzoom': 0, 'maxzoom': 0,
                'native_support_by_zoom': {'0': {'tiles': 1}}, 'attribution': 'Café'}
    path = write_pmtiles(tmp_path / 'relief.pmtiles', [((0, 0, 0), b'opaque tile')],
                         metadata=metadata, bounds=bounds, minzoom=0, maxzoom=0,
                         center=(0, 0.0, 0.0))
    assert archive_metadata(path) == metadata


@pytest.mark.parametrize('compression', [0, 1])
def test_uncompressed_metadata_round_trips(tmp_path, compression):
    path = _archive(tmp_path / 'relief.pmtiles', b'{"minzoom":0,"maxzoom":0}',
                    compression=compression)
    assert archive_metadata(path) == {'minzoom': 0, 'maxzoom': 0}


@pytest.mark.parametrize(('payload', 'field'), [
    (b'{"minzoom":false,"maxzoom":0}', 'minzoom'),
    (b'{"minzoom":0,"maxzoom":0.0}', 'maxzoom'),
    (b'{"minzoom":"0","maxzoom":0}', 'minzoom'),
    (b'{"minzoom":0}', 'maxzoom'),
], ids=['bool', 'float', 'string', 'missing'])
def test_zoom_metadata_requires_json_integers(tmp_path, payload, field):
    # Equality alone accepts false and 0.0 as the header byte 0; coercion accepts "0".
    path = _archive(tmp_path / 'relief.pmtiles', payload)
    with pytest.raises(InventoryError, match=rf'{field} must be an integer'):
        archive_metadata(path)


def _inventory_ctx(tmp_path, monkeypatch):
    selection = tmp_path / 'select/sources.json'
    selection.parent.mkdir()
    selection.write_text(json.dumps({'scope': 'public', 'sources': [
        {'id': 'synthetic', 'rights_class': 'public', 'resolution_m': 10, 'attribution': 'Test'},
    ]}))
    monkeypatch.setattr(inventory, 'catalog_rows', lambda: {'synthetic': {}})
    # The archive must already exist: its layer record hashes the file.
    return SimpleNamespace(region=SimpleNamespace(dir=tmp_path, id='synthetic',
                                                  record=lambda path: path.relative_to(tmp_path).as_posix()),
                           upstream={
                               'tiles.public': {'outputs': [package.layer_record(tmp_path, package.ARCHIVE)]},
                               'digests': {'outputs': [{'path': package.DIGEST_ROOT}]},
                               'zone.public': {'outputs': []},
                               'select': {'outputs': [{'path': 'select/sources.json'}]},
                           })


@pytest.mark.parametrize(('low', 'high', 'error'), [
    (10, 12, None),
    (9, 12, 'minzoom .*does not match.*header'),
    (10, 13, 'maxzoom .*does not match.*header'),
    (1, 0, 'zoom interval'),
], ids=['writer-control', 'lower-mismatch', 'upper-mismatch', 'matching-but-inverted'])
def test_inventory_requires_valid_archive_zooms(tmp_path, monkeypatch, low, high, error):
    # A rebuild can retain stale JSON zooms while the new header and receipt describe its bytes.
    bounds = (-1.0, -1.0, 1.0, 1.0)
    archive = tmp_path / package.ARCHIVE
    archive.parent.mkdir(parents=True)
    metadata = {'bounds': list(bounds), 'minzoom': low, 'maxzoom': high}
    if low > high:
        # Checking only per-field agreement accepts this empty range and writes a manifest.
        _archive(archive, json.dumps(metadata).encode(), zooms=(low, high))
    else:
        write_pmtiles(archive, [((10, 512, 512), b'low'), ((12, 2048, 2048), b'high')],
                      metadata=metadata, bounds=bounds, minzoom=10, maxzoom=12, center=(10, 0.0, 0.0))
    ctx = _inventory_ctx(tmp_path, monkeypatch)
    out = tmp_path / 'inventory'
    out.mkdir()
    manifest = out / inventory.MANIFEST
    if error is None:
        inventory.build(ctx, out)
        doc = json.loads(manifest.read_bytes())
        assert (doc['minzoom'], doc['maxzoom']) == (10, 12)
    else:
        with pytest.raises(InventoryError, match=error):
            inventory.build(ctx, out)
        assert not manifest.exists()


def _bounds_archive(path, declared, header=(-1.1234567, -1.0, 1.0, 1.0)):
    write_pmtiles(path, [((0, 0, 0), b'opaque tile')], metadata={'bounds': declared, 'minzoom': 0, 'maxzoom': 0},
                  bounds=header, minzoom=0, maxzoom=0, center=(0, 0.0, 0.0))


@pytest.mark.parametrize('index', range(4), ids=['west', 'south', 'east', 'north'])
def test_inventory_refuses_declared_bound_that_contradicts_header(tmp_path, monkeypatch, index):
    # A stale JSON bound beside a corrected binary header must stop here, not after the QA stage.
    # Each bound is checked on its own, so a check that covers only west (or compares the wrong
    # header field, e.g. south against north) still ships a bad footprint through the other three.
    declared = [-1.1234567, -1.0, 1.0, 1.0]
    declared[index] -= 0.9 if index < 2 else -0.9
    _bounds_archive(tmp_path / package.ARCHIVE, declared)
    ctx = _inventory_ctx(tmp_path, monkeypatch)
    out = tmp_path / 'inventory'
    out.mkdir()
    with pytest.raises(InventoryError, match='bound .* does not match header'):
        inventory.build(ctx, out)
    assert not (out / inventory.MANIFEST).exists()


def test_inventory_refuses_stale_west_minus_two(tmp_path, monkeypatch):
    # The observed incident: declared west -2.0 against header west -1.1234567 reached the manifest.
    _bounds_archive(tmp_path / package.ARCHIVE, [-2.0, -1.0, 1.0, 1.0])
    ctx = _inventory_ctx(tmp_path, monkeypatch)
    out = tmp_path / 'inventory'
    out.mkdir()
    with pytest.raises(InventoryError, match='west bound -2.0 does not match header -1.1234567'):
        inventory.build(ctx, out)
    assert not (out / inventory.MANIFEST).exists()


def test_inventory_keeps_declared_bounds_within_header_rounding(tmp_path, monkeypatch):
    # The header stores e7 integers, so -1.123456743 legitimately reads back as -1.1234567 (4.3e-8 away).
    # A zero-tolerance equality check would refuse every healthy archive; the manifest must keep the
    # declared value, not the header's rounded one.
    declared = [-1.123456743, -1.0, 1.0, 1.0]
    _bounds_archive(tmp_path / package.ARCHIVE, declared)
    ctx = _inventory_ctx(tmp_path, monkeypatch)
    out = tmp_path / 'inventory'
    out.mkdir()
    inventory.build(ctx, out)
    assert json.loads((out / inventory.MANIFEST).read_bytes())['bounds'] == declared


def test_inventory_bounds_tolerance_edge_matches_qa(tmp_path, monkeypatch):
    # QA's bounds_ok (relief/qa.py) allows 5.1e-8 degrees; 6e-8 would fail QA later, so refuse it here.
    _bounds_archive(tmp_path / package.ARCHIVE, [-1.1234567 - 6e-8, -1.0, 1.0, 1.0])
    ctx = _inventory_ctx(tmp_path, monkeypatch)
    out = tmp_path / 'inventory'
    out.mkdir()
    with pytest.raises(InventoryError, match='west bound'):
        inventory.build(ctx, out)
    assert not (out / inventory.MANIFEST).exists()
