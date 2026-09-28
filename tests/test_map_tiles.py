"""Checks the committed PMTiles used by the MapLibre map test (offline, stdlib only)."""

import gzip
import json
import struct
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TILES = ROOT / "dist" / "tiles"
# name -> rough bounds (west, south, east, north) the tiles must sit inside
EXPECTED = {
    "morro-bay-reef-outlines": (-121.2, 35.1, -120.7, 35.6),
    "socal-survey-habitat": (-121.5, 32.3, -116.9, 34.8),
}


def read_header(data):
    if data[:7] != b"PMTiles" or data[7] != 3:
        raise ValueError("not a PMTiles v3 archive")
    metadata_offset, metadata_length = struct.unpack_from("<QQ", data, 24)
    internal_compression = data[97]
    min_zoom, max_zoom = data[100], data[101]
    bounds = [value / 1e7 for value in struct.unpack_from("<iiii", data, 102)]
    raw = data[metadata_offset:metadata_offset + metadata_length]
    metadata = json.loads(gzip.decompress(raw) if internal_compression == 2 else raw)
    return {"min_zoom": min_zoom, "max_zoom": max_zoom, "bounds": bounds, "metadata": metadata}


class MapTilesTest(unittest.TestCase):
    def test_archives_are_pmtiles_with_reef_layer(self):
        for name, (west, south, east, north) in EXPECTED.items():
            with self.subTest(name=name):
                header = read_header((TILES / f"{name}.pmtiles").read_bytes())
                self.assertEqual((header["min_zoom"], header["max_zoom"]), (8, 15))
                w, s, e, n = header["bounds"]
                self.assertTrue(west <= w < e <= east and south <= s < n <= north, header["bounds"])
                layers = [layer["id"] for layer in header["metadata"]["vector_layers"]]
                self.assertEqual(layers, ["reefs"])
                # Temp paths would make rebuilds differ; the build runs with relative names.
                self.assertNotIn("/tmp", json.dumps(header["metadata"]))

    def test_every_archive_is_registered_in_the_build(self):
        source = (ROOT / "scripts" / "build_map_tiles.py").read_text()
        for path in TILES.glob("*.pmtiles"):
            self.assertIn(f"'{path.stem}'", source)


if __name__ == "__main__":
    unittest.main()
