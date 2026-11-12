"""Bridge driver reads refuse a writer-less FIFO instead of blocking in open()."""
from __future__ import annotations

import errno
import os
from pathlib import Path
import signal
import stat
import subprocess
import sys

import pytest

from skippercast.coastal.coordinator import bridge_run as driver, catalog_bridge
# Fixtures and helpers only (not test functions): reuse the synthetic world.
from tests.unit.test_coastal_bridge_run import enqueue, offline_and_provenance, snapshot, world  # noqa: F401

_CHILD = """
import sys
from pathlib import Path
from skippercast.coastal.coordinator import bridge_run
print("ready", flush=True)
try:
    bridge_run._json(Path(sys.argv[1]), "pipe")
except ValueError as error:
    print("REFUSED", error)
"""


@pytest.fixture(autouse=True)
def blocking_guard():
    """An old-code blocking open() is interrupted and fails, never hangs the suite."""
    def expired(signum, frame):
        raise AssertionError("blocking open on a FIFO")
    previous = signal.signal(signal.SIGALRM, expired)
    signal.alarm(30)
    yield
    signal.alarm(0)
    signal.signal(signal.SIGALRM, previous)


@pytest.fixture
def root(tmp_path):
    base = tmp_path / "root"
    (base / "sub").mkdir(parents=True)
    return base


def fifo(base, name="pipe"):
    path = base / name
    os.mkfifo(path)
    return path


def test_fifo_without_writer_refuses_without_wait(root):
    fifo(root)
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTHONPATH=str(Path(driver.__file__).parents[3]))
    done = subprocess.run([sys.executable, "-B", "-c", _CHILD, str(root)], capture_output=True, text=True, timeout=60, env=env)
    assert done.returncode == 0, done.stderr
    assert done.stdout.splitlines() == ["ready", "REFUSED regular bounded metadata required"]


def test_leaf_open_requires_nonblock_and_nofollow(root, monkeypatch):
    (root / "sub/doc.json").write_text("{}")
    real_open, leaf_calls = os.open, []

    def spy(path, flags, *args, **kwargs):
        if path == "doc.json":
            assert flags & os.O_NONBLOCK, "leaf open would block on a FIFO"
            leaf_calls.append((flags, kwargs.get("dir_fd")))
        return real_open(path, flags, *args, **kwargs)
    monkeypatch.setattr(os, "open", spy)
    assert driver._read(root, "sub/doc.json") == b"{}"
    (flags, dir_fd), = leaf_calls
    assert flags & os.O_NOFOLLOW and not flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT) and dir_fd is not None


@pytest.mark.parametrize("metadata", [True, False])
def test_both_modes_refuse_fifo_and_close_descriptor(root, monkeypatch, metadata):
    fifo(root)
    real_open, leaf_fds = os.open, []

    def spy(path, flags, *args, **kwargs):
        fd = real_open(path, flags, *args, **kwargs)
        if path == "pipe":
            leaf_fds.append(fd)
        return fd
    monkeypatch.setattr(os, "open", spy)
    with pytest.raises(ValueError, match="regular bounded metadata required"):
        driver._read(root, "pipe", metadata=metadata)
    (fd,) = leaf_fds
    with pytest.raises(OSError) as closed:
        os.fstat(fd)
    assert closed.value.errno == errno.EBADF
    assert stat.S_ISFIFO((root / "pipe").lstat().st_mode)


def test_enqueue_fifo_admission_has_no_side_effects(world):
    w = world
    admission = w.p / "admission.json"
    admission.rename(w.p / "admission-backup.json")
    os.mkfifo(admission)
    before = snapshot(w)
    with pytest.raises(ValueError, match="regular bounded metadata required"):
        enqueue(w)
    assert snapshot(w) == before
    assert not (w.p / "bridge/enqueue-receipt.json").exists()
    assert not list((w.root / "var/coastal/enqueue-intents").glob("*"))
    assert stat.S_ISFIFO(admission.lstat().st_mode)


def test_regular_metadata_and_binary_controls_unchanged(root):
    cap = catalog_bridge.MAX_DOCUMENT_BYTES
    exact, over = b" " * (cap - 2) + b"{}", b" " * (cap - 1) + b"{}"
    (root / "exact.json").write_bytes(exact)
    (root / "over.json").write_bytes(over)
    (root / "small.json").write_text('{"a": 1}')
    assert driver._read(root, "exact.json") == exact
    assert driver._json(root, "small.json") == {"a": 1}
    with pytest.raises(ValueError, match="regular bounded metadata required"):
        driver._read(root, "over.json")
    assert driver._read(root, "over.json", metadata=False) == over
    assert (root / "over.json").read_bytes() == over


def test_path_refusals_and_input_preservation(root):
    pipe = fifo(root)
    (root / "good.json").write_text("{}")
    (root / "link").symlink_to("good.json")
    with pytest.raises(OSError) as loop:
        driver._read(root, "link")
    assert loop.value.errno == errno.ELOOP
    with pytest.raises(IsADirectoryError):
        driver._read(root, "sub")
    with pytest.raises(FileNotFoundError):
        driver._read(root, "missing.json")
    with pytest.raises(ValueError, match="regular bounded metadata required"):
        driver._read(root, "pipe")
    assert driver._read(root, "good.json") == b"{}"
    assert stat.S_ISFIFO(pipe.lstat().st_mode) and (root / "link").is_symlink()
