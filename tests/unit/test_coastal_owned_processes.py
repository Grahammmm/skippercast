"""Descriptor-lifetime regressions for OwnedChildren._observe (synthetic seams)."""
from __future__ import annotations

import os
from unittest import mock

import pytest

from skippercast.coastal import _owned_processes as op

PID = 4242


def ident(pid=PID, ppid=None, start=1):
    return {"host": "h", "boot_id": "b", "pid": pid, "start_ticks": start,
            "ppid": os.getpid() if ppid is None else ppid, "state": "S"}


class Fixture:
    def __init__(self, identities, persist=None):
        self.seq = list(identities)
        self.opened = []
        with mock.patch.object(op, "_enable_subreaper"):
            self.owner = op.OwnedChildren(self._identity, persist or (lambda h: None))
        self.owner.children = lambda: {PID}

    def _identity(self, pid):
        item = self.seq.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item

    def pidfd_open(self, pid, flags):
        fd = os.open(os.devnull, os.O_RDONLY)
        self.opened.append(fd)
        return fd

    def observe(self):
        with mock.patch.object(op.os, "pidfd_open", self.pidfd_open, create=True):
            self.owner.observe()

    def is_open(self, fd):
        try:
            os.fstat(fd)
            return True
        except OSError:
            return False

    def cleanup(self):
        for fd in self.opened:
            if self.is_open(fd):
                os.close(fd)


class Boom(BaseException):
    pass


@pytest.mark.parametrize("exc", [OSError("read failed"), Boom()])
def test_post_open_identity_exception_closes_fd(exc):
    fx = Fixture([ident(), exc])
    try:
        with pytest.raises(type(exc)):
            fx.observe()
        assert fx.owner.uncertain is True
        assert not fx.is_open(fx.opened[0])
        assert fx.owner.fds == {} and fx.owner.history == []
    finally:
        fx.cleanup()


def test_post_open_comparison_error_closes_fd():
    bad = {"ppid": os.getpid()}  # missing keys -> KeyError in _same
    fx = Fixture([ident(), bad])
    try:
        with pytest.raises(KeyError):
            fx.observe()
        assert fx.owner.uncertain is True
        assert not fx.is_open(fx.opened[0])
        assert fx.owner.fds == {}
    finally:
        fx.cleanup()


def test_disappeared_closes_and_continues():
    fx = Fixture([ident(), None])
    try:
        fx.observe()
        assert not fx.is_open(fx.opened[0])
        assert fx.owner.fds == {} and fx.owner.history == []
        assert fx.owner.uncertain is False
    finally:
        fx.cleanup()


@pytest.mark.parametrize("after", [ident(start=2), ident(ppid=1)])
def test_changed_identity_or_parent_closes_and_raises(after):
    fx = Fixture([ident(), after])
    try:
        with pytest.raises(RuntimeError):
            fx.observe()
        assert not fx.is_open(fx.opened[0])
        assert fx.owner.fds == {} and fx.owner.history == []
    finally:
        fx.cleanup()


def test_successful_pin_transfers_once():
    persisted = []
    fx = Fixture([ident(), ident(), ident()], persist=lambda h: persisted.append(h))
    try:
        fx.observe()
        fd = fx.owner.fds[PID]
        assert fx.is_open(fd) and len(persisted) == 1
        fx.observe()  # already owned: no reopen
        assert len(fx.opened) == 1 and len(persisted) == 1
        fx.owner.close()
        assert not fx.is_open(fd) and fx.owner.fds == {}
    finally:
        fx.cleanup()


def test_persist_failure_retains_registered_fd():
    def persist(history):
        raise OSError("persist failed")

    fx = Fixture([ident(), ident()], persist=persist)
    try:
        with pytest.raises(OSError):
            fx.observe()
        assert fx.owner.uncertain is True
        fd = fx.owner.fds[PID]
        assert fx.is_open(fd)
        fx.owner.close()
        assert not fx.is_open(fd)
    finally:
        fx.cleanup()


def test_pre_open_and_acquisition_failures():
    fx = Fixture([OSError("first read")])
    try:
        with pytest.raises(OSError):
            fx.observe()
        assert fx.opened == [] and fx.owner.uncertain is True
    finally:
        fx.cleanup()

    fx = Fixture([ident()])
    def gone(pid, flags):
        raise ProcessLookupError()
    try:
        with mock.patch.object(op.os, "pidfd_open", gone, create=True), \
                mock.patch.object(op.os, "close") as close:
            fx.owner.observe()
            close.assert_not_called()
        assert fx.owner.uncertain is False
    finally:
        fx.cleanup()

    fx = Fixture([ident()])
    def denied(pid, flags):
        raise PermissionError()
    with mock.patch.object(op.os, "pidfd_open", denied, create=True):
        with pytest.raises(PermissionError):
            fx.owner.observe()
    assert fx.owner.uncertain is True
