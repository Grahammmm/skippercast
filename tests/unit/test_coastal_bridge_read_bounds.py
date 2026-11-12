"""Bridge metadata reads are bounded by the bytes actually read, not one fstat."""
import hashlib
import json
import os
from types import SimpleNamespace

import pytest

from skippercast.coastal.coordinator import bridge_run as driver, catalog_bridge
from tests.unit.test_coastal_bridge_run import enqueue, offline_and_provenance, snapshot, world  # noqa: F401

CAP = catalog_bridge.MAX_DOCUMENT_BYTES
REFUSED = "regular bounded metadata required"


class Hooks:
    """Driver-local os/json proxies: stale fstat for one inode, read-size and parse recording."""

    def __init__(self, monkeypatch, target=None, grow_to=0):
        self.target, self.grow_to = target, grow_to
        self.grown, self.streams, self.reads, self.parsed, self.fail_read = False, [], [], [], False
        hooks = self

        class Stream:
            def __init__(self, inner):
                self.inner = inner

            def __getattr__(self, name):
                return getattr(self.inner, name)

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return self.inner.__exit__(*exc)

            def read(self, size=-1):
                hooks.reads.append(size)
                if hooks.fail_read:
                    raise OSError("injected read failure")
                return self.inner.read(size)

        def fstat(fd):
            real = os.fstat(fd)
            if (hooks.target is not None and not hooks.grown
                    and (real.st_dev, real.st_ino) == (lambda s: (s.st_dev, s.st_ino))(os.stat(hooks.target))):
                with open(hooks.target, "ab") as other:  # separate real handle, valid JSON whitespace
                    other.write(b" " * (hooks.grow_to - real.st_size))
                hooks.grown = True
            return real  # the captured pre-growth observation

        def fdopen(fd, *args, **kwargs):
            stream = os.fdopen(fd, *args, **kwargs)
            hooks.streams.append(stream)
            return Stream(stream)

        def loads(raw, *args, **kwargs):
            hooks.parsed.append(len(raw))
            return json.loads(raw, *args, **kwargs)

        names = {n: getattr(os, n) for n in dir(os) if not n.startswith("__")}
        monkeypatch.setattr(driver, "os", SimpleNamespace(**dict(names, fstat=fstat, fdopen=fdopen)))
        monkeypatch.setattr(driver, "json", SimpleNamespace(loads=loads, dumps=json.dumps))


def small(tmp_path, name="doc.json", data=b"{}"):
    path = tmp_path / name
    path.write_bytes(data)
    return path


def test_metadata_growth_after_fstat_refuses_before_parse(tmp_path, monkeypatch):
    path = small(tmp_path)
    hooks = Hooks(monkeypatch, target=path, grow_to=CAP + 100)
    with pytest.raises(ValueError, match=REFUSED):
        driver._json(tmp_path, "doc.json")
    assert hooks.grown and path.stat().st_size == CAP + 100
    assert hooks.parsed == []


def test_metadata_read_request_is_cap_plus_one(tmp_path, monkeypatch):
    path = small(tmp_path)
    hooks = Hooks(monkeypatch, target=path, grow_to=CAP + 100)
    with pytest.raises(ValueError, match=REFUSED):
        driver._ref(tmp_path, path, "queue:x")
    assert hooks.reads and all(0 <= size <= CAP + 1 for size in hooks.reads)
    hooks.target = None
    path.write_bytes(b'{"a": 1}')
    hooks.reads.clear()
    assert driver._json(tmp_path, "doc.json") == {"a": 1}
    assert hooks.reads and all(0 <= size <= CAP + 1 for size in hooks.reads)


def test_metadata_exact_cap_and_one_over(tmp_path, monkeypatch):
    exact = small(tmp_path, data=b"{}" + b" " * (CAP - 2))
    assert driver._json(tmp_path, "doc.json") == {}
    assert driver._read(tmp_path, "doc.json") == exact.read_bytes()
    small(tmp_path, "over.json", b"{}" + b" " * (CAP - 1))
    with pytest.raises(ValueError, match=REFUSED):
        driver._json(tmp_path, "over.json")
    grow = small(tmp_path, "grow.json")
    Hooks(monkeypatch, target=grow, grow_to=CAP + 1)
    with pytest.raises(ValueError, match=REFUSED):
        driver._json(tmp_path, "grow.json")
    monkeypatch.undo()
    small(tmp_path, "empty.json", b"")
    assert driver._read(tmp_path, "empty.json") == b""
    with pytest.raises(json.JSONDecodeError):
        driver._json(tmp_path, "empty.json")


def test_reference_wrappers_inherit_bound(tmp_path, monkeypatch):
    path = small(tmp_path)
    Hooks(monkeypatch, target=path, grow_to=CAP + 10)
    with pytest.raises(ValueError, match=REFUSED):
        driver._ref(tmp_path, path, "queue:x")
    monkeypatch.undo()
    grown = path.read_bytes()
    # A correctly refreshed descriptor for the oversized bytes still cannot pass.
    refreshed = dict(root_id="queue:x", path="doc.json", sha256=hashlib.sha256(grown).hexdigest(), bytes=len(grown))
    path.write_bytes(b"{}")
    Hooks(monkeypatch, target=path, grow_to=CAP + 10)
    with pytest.raises(ValueError, match=REFUSED):
        driver._verify(tmp_path, refreshed, "queue:x")
    monkeypatch.undo()
    assert path.read_bytes() == grown


def test_binary_artifact_mode_unchanged(tmp_path):
    data = os.urandom(64) * ((CAP + 4096) // 64)
    path = small(tmp_path, "artifact.bin", data)
    ref = dict(path="artifact.bin", sha256=hashlib.sha256(data).hexdigest(), bytes=len(data))
    assert driver._read(tmp_path, "artifact.bin", metadata=False) == data
    assert driver._verify(tmp_path, ref, "queue:x", metadata=False) == data
    with pytest.raises(ValueError, match=REFUSED):
        driver._read(tmp_path, "artifact.bin")
    assert path.read_bytes() == data


def test_descriptor_closes_on_overrun_and_read_error(tmp_path, monkeypatch):
    path = small(tmp_path)
    hooks = Hooks(monkeypatch, target=path, grow_to=CAP + 5)
    with pytest.raises(ValueError, match=REFUSED):
        driver._read(tmp_path, "doc.json")
    path.write_bytes(b'{"b": 2}')
    hooks.target, hooks.fail_read = None, True
    with pytest.raises(OSError, match="injected read failure"):
        driver._read(tmp_path, "doc.json")
    assert len(hooks.streams) == 2 and all(s.closed for s in hooks.streams)
    hooks.fail_read = False
    assert driver._read(tmp_path, "doc.json") == b'{"b": 2}'
    (tmp_path / "link.json").symlink_to(path)
    with pytest.raises(OSError):
        driver._read(tmp_path, "link.json")
    (tmp_path / "dir.json").mkdir()
    with pytest.raises(IsADirectoryError):  # existing non-regular refusal, unchanged
        driver._read(tmp_path, "dir.json")
    with pytest.raises(ValueError, match="confined relative"):
        driver._read(tmp_path, "../doc.json")
    assert all(s.closed for s in hooks.streams)


def test_enqueue_growth_refuses_before_intent_or_store_write(world, monkeypatch):
    w = world
    admission = w.p / "admission.json"
    before, original = snapshot(w), admission.read_bytes()
    frozen = []
    monkeypatch.setattr(driver, "_freeze", lambda *a, **k: frozen.append(a))
    monkeypatch.setattr(driver, "Store", lambda *a, **k: frozen.append("store"))
    hooks = Hooks(monkeypatch, target=admission, grow_to=CAP + 64)
    with pytest.raises(ValueError, match=REFUSED):
        enqueue(w)
    assert hooks.grown and admission.read_bytes() == original + b" " * (CAP + 64 - len(original))
    assert frozen == [] and hooks.parsed == []
    assert not (w.root / "var/coastal/enqueue-intents").exists()
    assert not (w.p / "bridge/enqueue-receipt.json").exists()
    assert snapshot(w) == before
