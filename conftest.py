"""Repository-wide pytest setup, loaded before tests/ and research/tests/ conftests.

pytest imports skippercast from src/ (an editable install or PYTHONPATH=src). Left
alone, that writes src/skippercast/**/__pycache__, which the coastal source guard
(src/skippercast/coastal/_source_bootstrap.py) rightly refuses, so a coastal runner
pointed at a worktree that ran the tests would stop before its first stage. Turn
bytecode writing off here, before any project import, for this process and for the
Python subprocesses tests start (python -I ignores the variable; those tests set
their own flags).
"""
import os
import stat
import sys
from collections import deque

import pytest

sys.dont_write_bytecode = True
os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")


def pytest_configure(config):
    config.pluginmanager.register(_HostArchiveGuard(), "host-archive-guard")


def _archive_realpath(path, lstat=os.lstat, readlink=os.readlink):
    # Do not dispatch through os.path.realpath: tests can patch os.lstat to
    # model races, and a guard lookup must not consume a simulated observation.
    if not os.path.isabs(path):
        path = os.path.join(os.getcwd(), path)
    pending = deque(path.split(os.sep))
    resolved = []
    links_left = 40  # the host rejects opens through more symlinks than this
    while pending:
        part = pending.popleft()
        if not part or part == ".":
            continue
        if part == "..":
            if resolved:
                resolved.pop()
            continue
        resolved.append(part)
        current = os.sep + os.sep.join(resolved)
        try:
            if not stat.S_ISLNK(lstat(current).st_mode):
                continue
            target = readlink(current)
        except OSError:
            continue  # no link at this component (possibly a missing leaf)
        if not links_left:
            return current  # the requested open will fail with ELOOP
        links_left -= 1
        resolved.pop()
        if target.startswith(os.sep):
            resolved.clear()
        pending.extendleft(reversed(target.split(os.sep)))
    return os.sep + os.sep.join(resolved)


class _HostArchiveGuard:
    """Catch unintended Python file I/O in both test trees, including collection."""

    def __init__(self):
        home = os.path.expanduser("~")
        # Use the data roots from the historical configs, not their shared
        # parent: the maintainer also keeps source and Python tools there.
        project = os.path.join(home, "skippercast-data", "2026-10-07-pge-south")
        self.roots = tuple(map(os.path.realpath, (
            os.path.join(project, "outputs"), os.path.join(project, "scratch"),
            os.path.join(project, "repo", "var", "seafloor"),
            os.path.join(home, "agent-work", "t08"), os.path.join(home, "agent-work", "t08a"),
        )))
        self.enabled = True
        self.opted_in = os.environ.get("SC_ARCHIVE_TESTS") == "1"
        # Each xdist worker installs its own hook. Audit hooks cannot be removed.
        sys.addaudithook(self.check)

    def check(self, event, args):
        if not self.enabled or event not in {"open", "os.listdir", "os.scandir"}:
            return
        if not isinstance(args[0], (str, bytes)):
            return  # A file descriptor, not a new path.
        path = _archive_realpath(os.fsdecode(args[0]))
        if any(path == root or path.startswith(root + os.sep) for root in self.roots):
            raise AssertionError("host archive access requires @pytest.mark.host_archive and SC_ARCHIVE_TESTS=1")

    def pytest_collection_modifyitems(self, items):
        if not self.opted_in:
            for item in items:
                if item.get_closest_marker("host_archive") is not None:
                    item.add_marker(pytest.mark.skip(reason="Host archive test; set SC_ARCHIVE_TESTS=1 to run"))

    @pytest.hookimpl(wrapper=True, tryfirst=True)
    def pytest_runtest_protocol(self, item):
        self.enabled = not (self.opted_in and item.get_closest_marker("host_archive") is not None)
        try:
            return (yield)
        finally:
            self.enabled = True

    def pytest_unconfigure(self):
        self.enabled = False
