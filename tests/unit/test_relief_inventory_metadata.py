"""Inventory reads only file-backed PMTiles metadata and requires unambiguous JSON."""

import io
import struct
from types import SimpleNamespace

import pytest

from skippercast.relief.inventory import InventoryError, archive_metadata
from skippercast.relief.pmtiles_v3 import write_pmtiles


def _archive(path, payload, *, offset=127, length=None):
    header = bytearray(127)
    header[:8] = b'PMTiles\x03'
    struct.pack_into('<QQ', header, 24, offset, len(payload) if length is None else length)
    header[97] = 1  # uncompressed metadata
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
