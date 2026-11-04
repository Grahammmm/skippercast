"""Deliberate reproduction of the ``_group_state`` ``uncertain`` flake (SC-FLAKE-PGID).

``check (3.13)`` once failed ``test_coastal_operations`` with
``ValueError: recovery refused: owned process identity is uncertain`` and went green on
an identical rerun. ``_group_state`` (src/skippercast/coastal/runner.py) scans every
``/proc`` entry and answers ``uncertain`` for a group that is in fact fully stopped in
three ways, each reproduced below without waiting for luck:

1. NUMBER COLLISION. Any entry whose pgid OR sid *number* equals the recorded one is
   treated as a member: ``uncertain`` if its sid differs or it started before the
   recorded process. A foreign session that reuses the number trips this.
2. ZOMBIES JUDGED FIRST. The ``uncertain`` test (runner.py:102-103) runs before the Z/X
   exclusion (:104), so a dead, unreaped process counts as evidence against the group.
3. VANISHING PROCESS. ``process_identity`` only catches ``FileNotFoundError``. A process
   that exits between the scan's ``open`` and ``read`` of ``/proc/<pid>/stat`` makes the
   kernel answer ESRCH (``ProcessLookupError``); that falls through ``_group_state``'s
   ``except OSError`` to ``uncertain``. ANY process on the machine exiting during a scan
   can do it, with no relation to the group. Measured on the dev box: 20 of ~24,000
   scans of a live group (8 parallel spawn/kill loops), against 0 of ~3,500 with one.
   Under ``pytest -n 4`` on a busy runner this is by far the likeliest cause of the
   one-off CI failure; the pgid/sid collision needs a reused PID and is much rarer.

A natural collision cannot be summoned on demand (the kernel picks PIDs, and the ESRCH
window is a few microseconds wide), so these tests build each condition on purpose:
real processes whose real pgid/sid/start time come from ``/proc``, and a recorded
identity for a stopped group carrying those same numbers. Every number the group
itself is given elsewhere lies above ``kernel.pid_max`` so no process can hold it. The
scan is restricted to the processes the test created (``scan`` fixture), so unrelated
processes on the machine cannot add a fourth, accidental ``uncertain`` to a control.
Nothing races: ``Popen(start_new_session=True)`` has run ``setsid`` before it returns;
zombies are made with ``waitid(WNOWAIT)``, which blocks until exit without reaping; the
ESRCH is produced by opening the stat file, reaping the process, then reading.

The tests that expose the flake state the verdict a fix should reach (``stopped``) and
are ``xfail(strict=True)``: green and deterministic today, and red the moment the runner
changes, so whoever fixes it must delete the marker and thereby proves the fix. Watch
them fail for real against today's runner with::

    python -m pytest tests/unit/test_coastal_group_state_collision.py --runxfail

Whether each scenario SHOULD read ``stopped`` is the fix card's decision; the runner is
deliberately conservative and nothing here changes it.
"""
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys

import pytest

from skippercast.coastal import runner
from skippercast.coastal.receipts import digest
from skippercast.coastal.runner import PROTOCOL, boot_id, process_identity, recover, _group_state

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="coastal supervisor requires Linux /proc")

PID_MAX = int(Path("/proc/sys/kernel/pid_max").read_text())
_unreachable = iter(range(PID_MAX + 1000, PID_MAX + 2000))


def unreachable():
    """A positive number no process can ever hold (above kernel.pid_max)."""
    return next(_unreachable)


def identity(*, pid, pgid, sid, start_ticks):
    return {"host": socket.gethostname(), "boot_id": boot_id(), "pid": pid,
            "start_ticks": start_ticks, "pgid": pgid, "sid": sid}


def stopped_group(*, pgid=None, sid=None, start_ticks=1000):
    """Identity of a group with no member anywhere; pgid/sid override to plant a collision."""
    return identity(pid=unreachable(), pgid=pgid or unreachable(), sid=sid or unreachable(),
                    start_ticks=start_ticks)


@pytest.fixture
def spawn():
    started = []

    def start(argv, **kwargs):
        proc = subprocess.Popen(argv, start_new_session=True, **kwargs)
        started.append(proc)
        return proc

    yield start
    for proc in started:
        if proc.poll() is None:
            proc.kill()
        proc.wait()


@pytest.fixture
def scan(monkeypatch):
    """Confine _group_state's /proc scan to chosen PIDs: ``scan.only(pid, ...)``.

    The entries are still read from the real /proc. ``scan.on_read(pid, fn)`` replaces
    the next read of that PID's stat file with ``fn(path)``.
    """
    class Scoped(type(Path())):
        pids = []
        hooks = {}

        def iterdir(self):
            if str(self) == "/proc":
                return iter([Scoped(f"/proc/{pid}") for pid in Scoped.pids])
            return super().iterdir()

        def read_text(self, *args, **kwargs):
            hook = Scoped.hooks.pop(str(self), None)
            return hook(self) if hook else super().read_text(*args, **kwargs)

    def only(*pids):
        Scoped.pids = list(pids)

    def on_read(pid, fn):
        Scoped.hooks[f"/proc/{pid}/stat"] = fn

    monkeypatch.setattr(runner, "Path", Scoped)
    Scoped.only, Scoped.on_read = staticmethod(only), staticmethod(on_read)
    only()
    return Scoped


@pytest.fixture
def foreign_session(spawn, scan):
    """A live process leading its own session and group: pgid == sid == pid."""
    proc = spawn(["sleep", "300"])
    found = process_identity(proc.pid)
    assert found["pgid"] == found["sid"] == proc.pid and found["state"] != "Z"
    scan.only(proc.pid)
    return found


@pytest.fixture
def foreign_zombie(spawn, scan):
    """A dead, unreaped session leader: still in /proc with its pgid and sid, state Z."""
    proc = spawn(["true"])
    os.waitid(os.P_PID, proc.pid, os.WEXITED | os.WNOWAIT)   # blocks until exit, does not reap
    found = process_identity(proc.pid)
    assert found["state"] == "Z" and found["pgid"] == found["sid"] == proc.pid
    scan.only(proc.pid)
    return found


# --- controls: definite verdicts that must stay definite --------------------------------

def test_group_with_no_member_is_stopped(scan):
    assert _group_state(stopped_group()) == "stopped"


def test_running_group_is_live(foreign_session):
    assert _group_state(identity(pid=foreign_session["pid"], pgid=foreign_session["pgid"],
                                 sid=foreign_session["sid"],
                                 start_ticks=foreign_session["start_ticks"])) == "live"


def test_group_whose_only_member_is_its_own_zombie_is_stopped(foreign_zombie):
    owned = identity(pid=foreign_zombie["pid"], pgid=foreign_zombie["pgid"],
                     sid=foreign_zombie["sid"], start_ticks=foreign_zombie["start_ticks"])
    assert _group_state(owned) == "stopped"


def test_unrelated_process_with_other_numbers_does_not_matter(foreign_session):
    assert _group_state(stopped_group()) == "stopped"


def test_kernel_answers_esrch_not_enoent_for_a_stat_handle_opened_before_the_process_was_reaped(spawn):
    # The fact the vanishing-process case rests on; process_identity only catches ENOENT.
    proc = spawn(["sleep", "300"])
    fd = os.open(f"/proc/{proc.pid}/stat", os.O_RDONLY)
    try:
        proc.kill()
        proc.wait()
        with pytest.raises(ProcessLookupError):
            os.read(fd, 4096)
    finally:
        os.close(fd)
    with pytest.raises(FileNotFoundError):
        Path(f"/proc/{proc.pid}/stat").read_text()


# --- the reproduction: a stopped group that reads `uncertain` ---------------------------

STOPPED_BUT_UNCERTAIN = ("_group_state reports a stopped group `uncertain` (runner.py:100-110); "
                         "SC-FLAKE-PGID")


@pytest.mark.xfail(strict=True, reason=STOPPED_BUT_UNCERTAIN + ": unrelated process exited mid-scan (ESRCH)")
def test_unrelated_process_exiting_during_the_scan_does_not_make_a_stopped_group_uncertain(spawn, scan):
    # Not a member, not a collision: any process leaving /proc between the scan's open
    # and read of its stat file raises ProcessLookupError, which process_identity does
    # not catch and _group_state's `except OSError` turns into `uncertain`.
    victim = spawn(["sleep", "300"])
    scan.only(victim.pid)

    def read_across_exit(path):
        fd = os.open(path, os.O_RDONLY)   # succeeds: the process is still there
        victim.kill()
        victim.wait()                     # reaped before the read
        try:
            return os.read(fd, 4096).decode()   # kernel: ESRCH
        finally:
            os.close(fd)

    scan.on_read(victim.pid, read_across_exit)
    assert _group_state(stopped_group()) == "stopped"


@pytest.mark.xfail(strict=True, reason=STOPPED_BUT_UNCERTAIN + ": foreign session holds the pgid number")
def test_foreign_session_holding_the_pgid_number_does_not_make_a_stopped_group_uncertain(foreign_session):
    # Same pgid number, different session: the group that owned it is gone and a
    # foreign session now holds the number.
    owned = stopped_group(pgid=foreign_session["pgid"], start_ticks=foreign_session["start_ticks"] - 100)
    assert owned["sid"] != foreign_session["sid"]
    assert _group_state(owned) == "stopped"


@pytest.mark.xfail(strict=True, reason=STOPPED_BUT_UNCERTAIN + ": zombie holds the pgid number, judged before Z/X")
def test_foreign_zombie_holding_the_pgid_number_does_not_make_a_stopped_group_uncertain(foreign_zombie):
    # As above, but the holder is a dead, unreaped zombie: it cannot be live, yet it
    # is judged before the Z/X exclusion.
    owned = stopped_group(pgid=foreign_zombie["pgid"], start_ticks=foreign_zombie["start_ticks"] - 100)
    assert _group_state(owned) == "stopped"


@pytest.mark.xfail(strict=True, reason=STOPPED_BUT_UNCERTAIN + ": older zombie leader, no number reuse needed")
def test_unreaped_zombie_session_leader_does_not_make_a_stopped_descendant_group_uncertain(spawn, scan):
    # No reused number at all. A worker (the session leader) starts a child in its
    # session and exits unreaped; the child is then killed. Every process of the group
    # is dead, but the zombie leader started BEFORE the recorded child, so the
    # `start_ticks <` test fires on a zombie.
    leader = spawn(["sh", "-c", "sleep 0.1; sleep 300 & echo $!"], stdout=subprocess.PIPE, text=True)
    child_pid = int(leader.stdout.readline())
    leader.stdout.close()
    os.waitid(os.P_PID, leader.pid, os.WEXITED | os.WNOWAIT)
    child = process_identity(child_pid)
    zombie_leader = process_identity(leader.pid)
    os.kill(child_pid, signal.SIGKILL)
    assert zombie_leader["state"] == "Z"
    assert child["pgid"] == child["sid"] == leader.pid
    assert zombie_leader["start_ticks"] < child["start_ticks"]
    # The child's own PID is not scanned or probed: it is being reaped by init right now.
    scan.only(leader.pid)
    owned = identity(pid=unreachable(), pgid=child["pgid"], sid=child["sid"], start_ticks=child["start_ticks"])
    assert _group_state(owned) == "stopped"


@pytest.mark.xfail(strict=True, reason="a newer foreign session reusing the sid number reads `live`, "
                                       "the unsafe direction (SC-FLAKE-PGID observation)")
def test_foreign_session_holding_the_sid_number_does_not_make_a_stopped_group_live(foreign_session):
    # Same sid number, newer start: runner.py:102-103 takes it for a member of the
    # recorded session and answers `live`, which would also let _signal_owned_group
    # signal that foreign session's groups.
    owned = stopped_group(sid=foreign_session["sid"], start_ticks=foreign_session["start_ticks"] - 100)
    assert _group_state(owned) == "stopped"


# --- the same through the real recovery gate (runner.py:632) ----------------------------

def recovery_inputs(tmp_path, child):
    intent = {"schema": "coastal-run-intent-v1", "boot_id": boot_id(), "state": "finished",
              "ownership_protocol": PROTOCOL, "owned_descendants": [], "ownership_complete": True,
              "processes_stopped": True, "supervisor": stopped_group(), "child": child}
    path = tmp_path / "intent.json"
    path.write_text(json.dumps(intent))
    receipt = {"schema": "coastal-recovery-v1", "checkpoint_sha256": digest(intent),
               "processes_stopped": True, "attested_by": "test-operator"}
    return path, receipt


def test_recovery_of_a_stopped_run_succeeds(tmp_path, scan):
    path, receipt = recovery_inputs(tmp_path, stopped_group())
    assert recover(path, receipt)["state"] == "recovered"


@pytest.mark.xfail(strict=True, reason="recovery refused: owned process identity is uncertain -- the "
                                       "check (3.13) failure; SC-FLAKE-PGID")
def test_recovery_of_a_stopped_run_is_not_refused_by_a_foreign_session_holding_a_pgid_number(
        tmp_path, foreign_session):
    path, receipt = recovery_inputs(tmp_path, stopped_group(
        pgid=foreign_session["pgid"], start_ticks=foreign_session["start_ticks"] - 100))
    assert recover(path, receipt)["state"] == "recovered"
