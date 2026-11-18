"""F26-12: the BAG checksum is streamed in fixed-size chunks, with unchanged failure semantics."""
import hashlib
import importlib.util
from pathlib import Path

import pytest

pytest.importorskip("rasterio")
pytest.importorskip("pyproj")
pytest.importorskip("shapely")

SCRIPT = Path(__file__).resolve().parents[2] / "research/scripts/assess_native_depth_overlap.py"
spec = importlib.util.spec_from_file_location("assess_native_depth_overlap", SCRIPT)
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

URL = "https://example.invalid/synthetic.bag"
PAYLOAD = bytes(range(256)) * 41  # 10 496 bytes, several chunks


class BoundedStream:
    """Wraps a file and rejects unbounded or oversized reads."""

    def __init__(self, handle, limit):
        self.handle, self.limit, self.reads = handle, limit, []

    def read(self, size=-1):
        assert size is not None and 0 < size <= self.limit, f"unbounded read: {size}"
        self.reads.append(size)
        return self.handle.read(size)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.handle.close()


def row(digest):
    return {"status": "ok", "metadata_status": "mllw-product-uncertainty-reviewed-by-adapter",
            "overview_resolution_m": [4], "variable_refinement_records": 0, "url": URL,
            "survey_id": "SYN", "file_sha256": digest, "raster_bounds_wgs84": [0, 0, 1, 1]}


def cached(tmp_path, payload=PAYLOAD):
    path = tmp_path / ("SYN-" + hashlib.sha256(URL.encode()).hexdigest()[:16] + ".bag")
    path.write_bytes(payload)
    return path


def test_digest_parity(tmp_path):
    path = cached(tmp_path)
    assert module.file_sha256(path) == hashlib.sha256(PAYLOAD).hexdigest()
    assert module.file_sha256(path, chunk_size=7) == hashlib.sha256(PAYLOAD).hexdigest()


def test_stream_never_reads_unbounded(tmp_path, monkeypatch):
    path = cached(tmp_path)
    streams = []

    def fake_open(target, mode="r"):
        stream = BoundedStream(open(target, mode), 4096)
        streams.append(stream)
        return stream

    monkeypatch.setattr(module, "open", fake_open, raising=False)
    assert module.file_sha256(path, chunk_size=4096) == hashlib.sha256(PAYLOAD).hexdigest()
    assert len(streams[0].reads) >= 3


def test_screen_one_hashes_off_region_without_read_bytes(tmp_path, monkeypatch):
    cached(tmp_path)
    monkeypatch.setattr(Path, "read_bytes", lambda self: pytest.fail("whole-file read"))
    # Matching digest, no context nearby: screened out, no error.
    assert module.screen_one(row(hashlib.sha256(PAYLOAD).hexdigest()), tmp_path, {}) is None


def test_corrupt_file_fails_even_off_region(tmp_path):
    cached(tmp_path, PAYLOAD[:-1] + b"X")
    with pytest.raises(ValueError, match="missing or its pinned digest changed"):
        module.screen_one(row(hashlib.sha256(PAYLOAD).hexdigest()), tmp_path, {})


def test_absent_file_fails_even_off_region(tmp_path):
    with pytest.raises(ValueError, match="missing or its pinned digest changed"):
        module.screen_one(row(hashlib.sha256(PAYLOAD).hexdigest()), tmp_path, {})
