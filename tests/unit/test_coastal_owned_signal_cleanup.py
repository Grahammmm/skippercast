"""RF2100-6: one unverifiable owned child must not starve sibling cleanup.

Synthetic already-owned children only: invented identities, fake fds and a
mocked pidfd send. No process is created and no real signal is sent.
"""
from __future__ import annotations

import os
import signal
from unittest import mock

import pytest

from skippercast.coastal import _owned_processes as op

BAD, GOOD = 101, 202
ORDINARY = [OSError("unreadable"), PermissionError(), RuntimeError("x"),
            ValueError("x"), KeyError("state")]


def ident(pid, ppid=None, start=1, state="S"):
    return {"host": "h", "boot_id": "b", "pid": pid, "start_ticks": start,
            "ppid": os.getpid() if ppid is None else ppid, "state": state}


class Owner:
    """Already-owned synthetic owner; ``current`` maps pid -> identity/exception."""

    def __init__(self, order, current, send_errors=None):
        with mock.patch.object(op, "_enable_subreaper"):
            self.owner = op.OwnedChildren(self._identity, lambda h: None)
        self.owner.children = lambda: set()  # observe is a no-op; empty kernel list
        self.current = dict(current)
        self.send_errors = dict(send_errors or {})
        self.sent = []  # (pid, sig)
        for pid in order:
            self.owner.fds[pid] = 1000 + pid
            self.owner.records[pid] = ident(pid)

    def _identity(self, pid):
        item = self.current[pid]
        if isinstance(item, BaseException):
            raise item
        return item

    def _send(self, fd, sig, info, flags):
        pid = fd - 1000
        if pid in self.send_errors:
            raise self.send_errors[pid]
        self.sent.append((pid, sig))

    def signal(self, sig=signal.SIGTERM):
        with mock.patch.object(op.signal, "pidfd_send_signal", self._send, create=True):
            self.owner._signal(sig)


@pytest.mark.parametrize("exc", ORDINARY, ids=lambda e: type(e).__name__)
@pytest.mark.parametrize("order", [[BAD, GOOD], [GOOD, BAD]], ids=["bad-first", "bad-last"])
def test_unreadable_first_child_does_not_starve_sibling(exc, order):
    fx = Owner(order, {BAD: exc, GOOD: ident(GOOD)})
    fx.signal()
    assert fx.sent == [(GOOD, signal.SIGTERM)]
    assert fx.owner.uncertain is True
    assert set(fx.owner.fds) == {BAD, GOOD}  # no descriptor discarded


@pytest.mark.parametrize("exc", [OSError("send"), PermissionError()], ids=["OSError", "PermissionError"])
def test_failed_send_does_not_starve_sibling(exc):
    fx = Owner([BAD, GOOD], {BAD: ident(BAD), GOOD: ident(GOOD)}, {BAD: exc})
    fx.signal(signal.SIGKILL)
    assert fx.sent == [(GOOD, signal.SIGKILL)]
    assert fx.owner.uncertain is True


def test_process_lookup_on_send_stays_benign_and_continues():
    fx = Owner([BAD, GOOD], {BAD: ident(BAD), GOOD: ident(GOOD)},
               {BAD: ProcessLookupError()})
    fx.signal()
    assert fx.sent == [(GOOD, signal.SIGTERM)]
    assert fx.owner.uncertain is False


@pytest.mark.parametrize("bad", [{"ppid": os.getpid(), "state": "S"},  # _same KeyError
                                 {"host": "h"}],  # missing state -> KeyError
                         ids=["missing-identity-key", "missing-state"])
def test_comparison_error_is_local(bad):
    fx = Owner([BAD, GOOD], {BAD: bad, GOOD: ident(GOOD)})
    fx.signal()
    assert fx.sent == [(GOOD, signal.SIGTERM)]
    assert fx.owner.uncertain is True


def test_programming_errors_are_not_suppressed():
    fx = Owner([BAD, GOOD], {BAD: TypeError("bug"), GOOD: ident(GOOD)})
    with pytest.raises(TypeError):
        fx.signal()


@pytest.mark.parametrize("current,uncertain", [
    (None, False),
    (ident(BAD, state="Z"), False),
    (ident(BAD, state="X"), False),
    (ident(BAD, start=2), True),   # reused PID
    (ident(BAD, ppid=1), True),    # changed parent
], ids=["gone", "zombie", "dead", "reused", "reparented"])
def test_unverifiable_entries_never_signalled(current, uncertain):
    fx = Owner([BAD, GOOD], {BAD: current, GOOD: ident(GOOD)})
    with mock.patch.object(op.os, "kill") as kill, \
            mock.patch.object(op.os, "pidfd_open", create=True) as opened:
        fx.signal()
    assert fx.sent == [(GOOD, signal.SIGTERM)]
    assert fx.owner.uncertain is uncertain
    kill.assert_not_called()
    opened.assert_not_called()


def _reap(fx):
    with mock.patch.object(op.os, "waitpid", side_effect=ChildProcessError()), \
            mock.patch.object(op, "_subreaper_enabled", return_value=True):
        return fx.owner._reap(None)


def test_uncertainty_never_becomes_stopped_proof():
    fx = Owner([BAD, GOOD], {BAD: OSError("unreadable"), GOOD: ident(GOOD)})
    fx.signal()
    fx.current[BAD] = ident(BAD)  # even once readable again, uncertainty persists
    assert fx.sent and _reap(fx) is False
    clean = Owner([BAD, GOOD], {BAD: ident(BAD), GOOD: ident(GOOD)})
    clean.signal()
    assert _reap(clean) is True


def test_persistent_bad_entry_across_stop_phases():
    fx = Owner([BAD, GOOD], {BAD: OSError("unreadable"), GOOD: ident(GOOD)})
    clock = [0.0]

    def sleep(seconds):
        clock[0] += 0.1

    with mock.patch.object(op.time, "monotonic", lambda: clock[0]), \
            mock.patch.object(op.time, "sleep", sleep), \
            mock.patch.object(op.os, "waitpid", side_effect=ChildProcessError()), \
            mock.patch.object(op, "_subreaper_enabled", return_value=True), \
            mock.patch.object(op.signal, "pidfd_send_signal", fx._send, create=True):
        assert fx.owner.stop(None, 0.5) is False
    sigs = {sig for pid, sig in fx.sent if pid == GOOD}
    assert sigs == {signal.SIGTERM, signal.SIGKILL}
    assert all(pid == GOOD for pid, _ in fx.sent)
    assert fx.owner.uncertain is True
