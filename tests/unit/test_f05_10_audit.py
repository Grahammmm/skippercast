"""SCA-360: binary lineage rechecks bound I/O without trusting previous ticks."""
import hashlib
import os

import pytest

from skippercast.coastal.coordinator import bridge_run as driver
from tests.unit.test_coastal_bridge_read_bounds import Hooks
from tests.unit.test_coastal_bridge_run import (  # noqa: F401 (shared pytest fixtures)
    enqueue, offline_and_provenance, run, snapshot, synthetic_dispatch, world,
)


@pytest.mark.parametrize("change", ["none", "size", "append", "truncate", "digest", "over-cap", "negative"])
def test_binary_verification_bounds_reads_and_refuses_changes(tmp_path, monkeypatch, change):
    # A declared length is not permission to read to EOF, even if fstat matched.
    # Simulate a size change after that observation without relying on thread timing.
    data = b"synthetic payload!"
    path = tmp_path / "artifact.bin"
    path.write_bytes(data)
    size = len(data)
    cap = size - 1 if change == "over-cap" else size
    monkeypatch.setattr(driver, "MAX_SOURCE_BYTES", cap, raising=False)
    monkeypatch.setattr(driver, "_VERIFY_CHUNK_BYTES", 8, raising=False)
    ref = dict(path=path.name, sha256=hashlib.sha256(data).hexdigest(),
               bytes={"size": size - 1, "negative": -1}.get(change, size))
    hooks = Hooks(monkeypatch)
    fstat = os.fstat

    def observe(fd):
        info = fstat(fd)
        if change == "append":
            with path.open("ab") as stream:
                stream.write(b"extra bytes")
        elif change == "truncate":
            path.write_bytes(data[:-1])
        return info

    monkeypatch.setattr(driver.os, "fstat", observe)
    if change == "digest":
        path.write_bytes(b"X" + data[1:])
    if change == "none":
        driver._verify(tmp_path, ref, "queue:synthetic", metadata=False)
    else:
        with pytest.raises(ValueError, match="reference hash/bytes mismatch|invalid byte reference"):
            driver._verify(tmp_path, ref, "queue:synthetic", metadata=False)

    if change in {"size", "over-cap", "negative"}:
        assert hooks.reads == []
    else:
        assert hooks.reads and all(0 < n <= 8 for n in hooks.reads)
        if change in {"none", "append", "digest"}:
            assert hooks.reads[-1] == 1 and sum(hooks.reads[:-1]) == size
    assert all(stream.closed for stream in hooks.streams)


def test_multi_window_ticks_and_continuation_reverify_binary_artifacts(world, synthetic_dispatch, monkeypatch, caplog):
    # Same-length bytes changed between runs must not inherit trust from a
    # previous verification. A clean continuation must still rehash both windows.
    w = world
    enqueue(w)
    monkeypatch.setattr(driver, "_VERIFY_CHUNK_BYTES", 8)
    hooks = Hooks(monkeypatch)
    with caplog.at_level("DEBUG", logger=driver.__name__):
        first = run(w, ticks=3)
        assert first["stop_reason"] == "max_ticks", first["problems"]
        assert first["counts"]["map_done"] == 1 and first["counts"]["windows"] == 2
        artifact = first["windows"][0]["stages"]["map"]["products"]["terrain"]
        path = w.root / artifact["path"]
        original = path.read_bytes()
        before = snapshot(w)
        path.write_bytes(bytes([original[0] ^ 1]) + original[1:])
        with pytest.raises(ValueError, match="reference hash/bytes mismatch"):
            run(w, sequence=1, continuation=True)
        assert snapshot(w) == before
        assert not (w.p / "runs/run-01.json").exists()
        path.write_bytes(original)
        final = run(w, sequence=1, continuation=True)
        assert final["stop_reason"] == "terminal", final["problems"]
        assert final["counts"]["map_done"] == 2 and final["ticks_used"] == 3

    verified = [record.args[0] for record in caplog.records
                if record.name == driver.__name__ and record.msg == "bridge verified %d binary artifact bytes"]
    binary_reads = [n for n in hooks.reads if n != driver.catalog_bridge.MAX_DOCUMENT_BYTES + 1]
    assert len(binary_reads) > len(verified) > 0 and all(0 < n <= 8 for n in binary_reads)
    product_bytes = sum(ref["bytes"] for window in final["windows"]
                        for stage in window["stages"].values()
                        for ref in stage["products"].values() if not ref["path"].endswith(".json"))
    assert product_bytes > 0 and sum(verified) > product_bytes
    print(f"Synthetic binary verification: {sum(verified)} bytes in {len(verified)} checks, "
          f"{product_bytes} bytes in final window products")
