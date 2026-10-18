"""Process-local Linux descendant ownership for the dedicated supervisor.

This is lifecycle accounting, not an aggregate memory/CPU/task-count limit.
Only kernel-owned direct children are signalled, through pinned pidfds. Killing
and reaping their parents makes even detached grandchildren adoptable here.
"""
from __future__ import annotations

import ctypes
import os
from pathlib import Path
import signal
import time

PROTOCOL = "subreaper-pidfd-v1"


def _subreaper_enabled():
    enabled = ctypes.c_int()
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(37, ctypes.byref(enabled), 0, 0, 0) != 0:
        raise OSError(ctypes.get_errno(), "PR_GET_CHILD_SUBREAPER failed")
    return enabled.value == 1


def _enable_subreaper():
    if not hasattr(os, "pidfd_open") or not hasattr(signal, "pidfd_send_signal"):
        raise RuntimeError("owned descendant cleanup requires Linux pidfds")
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(36, 1, 0, 0, 0) != 0:
        raise OSError(ctypes.get_errno(), "PR_SET_CHILD_SUBREAPER failed")
    if not _subreaper_enabled():
        raise RuntimeError("supervisor child-subreaper setup was not verified")


class OwnedChildren:
    """Own descendants solely inside the detached supervisor."""

    def __init__(self, identity, persist):
        _enable_subreaper()  # Fail before spawning any target if unavailable.
        self.pid = os.getpid()
        self.identity = identity
        self.persist = persist
        self.records = {}
        self.history = []
        self.fds = {}
        self.uncertain = False
        self.term_until = None
        self.kill_until = None

    def children(self):
        # Kernel parentage is independent of session membership. Include all
        # supervisor threads so a future extra thread cannot conceal a child.
        children = set()
        for task in Path(f"/proc/{self.pid}/task").iterdir():
            try:
                children.update(int(pid) for pid in (task / "children").read_text().split())
            except FileNotFoundError:
                continue
        return children

    @staticmethod
    def _same(first, second):
        keys = ("host", "boot_id", "pid", "start_ticks")
        return second is not None and all(first[k] == second[k] for k in keys)

    def observe(self):
        try:
            self._observe()
        except BaseException:
            self.uncertain = True
            raise

    def _observe(self):
        for pid in self.children():
            before = self.identity(pid)
            if before is None:
                continue
            if before.get("ppid") != self.pid:
                raise RuntimeError("kernel child identity is uncertain")
            if pid in self.fds:
                if not self._same(self.records[pid], before):
                    raise RuntimeError("owned child PID was reused")
                continue
            try:
                fd = os.pidfd_open(pid, 0)
            except ProcessLookupError:
                continue
            after = self.identity(pid)
            if not self._same(before, after) or after.get("ppid") != self.pid:
                os.close(fd)
                if after is None:
                    continue
                raise RuntimeError("owned child identity changed while pinning pidfd")
            self.fds[pid] = fd
            self.records[pid] = after
            self.history.append(after)
            # Partial records cannot prove universal absence after a crash.
            self.persist(list(self.history))

    def _signal(self, sig):
        try:
            self.observe()
        except (OSError, RuntimeError, ValueError, KeyError):
            self.uncertain = True
        for pid, fd in list(self.fds.items()):
            current = self.identity(pid)
            if current is None or current["state"] in {"Z", "X"}:
                continue
            if not self._same(self.records[pid], current) or current.get("ppid") != self.pid:
                self.uncertain = True
                continue
            try:
                signal.pidfd_send_signal(fd, sig, None, 0)
            except ProcessLookupError:
                pass

    def _reap(self, target):
        # Popen must retain the target exit status. A generic waitpid must not
        # consume it and make a failed target appear successful.
        target_done = target is None or target.poll() is not None
        for pid in self.children():
            if target is not None and pid == target.pid:
                continue
            try:
                os.waitpid(pid, os.WNOHANG)
            except ChildProcessError:
                pass
        for pid, fd in list(self.fds.items()):
            if self.identity(pid) is None:
                os.close(fd)
                del self.fds[pid]
        if not target_done:
            return False
        try:
            reaped, _ = os.waitpid(-1, os.WNOHANG)
            if reaped:
                return False
        except ChildProcessError:
            # ECHILD includes adopted descendants that raced with snapshots.
            return not self.children() and _subreaper_enabled() and not self.uncertain
        return False

    def stop(self, target, grace_s):
        """Bound cleanup; only ECHILD and an empty kernel list prove completion."""
        if self.kill_until is None:
            self.term_until = time.monotonic() + grace_s
            self.kill_until = self.term_until + max(1.0, grace_s)
        while time.monotonic() < self.kill_until:
            try:
                self._signal(signal.SIGTERM if time.monotonic() < self.term_until else signal.SIGKILL)
                if self._reap(target):
                    return True
            except (OSError, RuntimeError, ValueError, KeyError):
                self.uncertain = True
                # Continue cleaning verifiable children, but never create a
                # stopped proof following an ownership observation error.
            time.sleep(0.01)
        return False

    def close(self):
        for fd in self.fds.values():
            os.close(fd)
        self.fds.clear()
