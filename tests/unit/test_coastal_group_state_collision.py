"""Regressions for the ``_group_state`` verdicts that once flaked (SC-FLAKE-PGID, SC1952-02).

``check (3.13)`` once failed ``test_coastal_operations`` with
``ValueError: recovery refused: owned process identity is uncertain`` and went green on
an identical rerun. ``_group_state`` (src/skippercast/coastal/runner.py) scans the
``/proc`` entries; it used to answer wrongly for a fully stopped group in three ways:

1. NUMBER COLLISION. An entry matching the recorded pgid *number* alone was treated as a
   member (``uncertain``). Now only the recorded SESSION decides membership: a foreign
   session holding the pgid number is unrelated, whatever its age.
2. ZOMBIES JUDGED FIRST. Dead (Z/X) entries are now dropped before any age comparison, so
   an older zombie session leader no longer counts as evidence against its own group.
3. VANISHING PROCESS. A process leaving ``/proc`` between the scan's ``open`` and ``read``
   makes the kernel answer ESRCH (``ProcessLookupError``); ``process_identity`` treats it
   as disappearance, like ENOENT.

The unsafe direction is covered too: a NEWER foreign session reusing the recorded sid
number used to read ``live``, which would let ``_signal_owned_group`` killpg that
session's groups. The session leader at the recorded sid now proves the incarnation: a
leader that started after the recorded process means the sid is a different session, so
the group reads ``stopped``. Member age alone is not proof (descendants start later).

A natural collision cannot be summoned on demand (the kernel picks PIDs, and the ESRCH
window is a few microseconds wide), so these tests build each condition on purpose:
real processes whose real pgid/sid/start time come from ``/proc``, and a recorded
identity for a stopped group carrying those same numbers. Every number the group
itself is given elsewhere lies above ``kernel.pid_max`` so no process can hold it. The
scan is restricted to the processes the test created (``scan`` fixture), so unrelated
processes on the machine cannot add an accidental ``uncertain`` to a control.
Nothing races: ``Popen(start_new_session=True)`` has run ``setsid`` before it returns;
zombies are made with ``waitid(WNOWAIT)``, which blocks until exit without reaping; the
ESRCH is produced by opening the stat file, reaping the process, then reading.
``os.killpg`` is always replaced by a recorder: no test signals a process group.
"""
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import uuid

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

def test_unrelated_process_exiting_during_the_scan_does_not_make_a_stopped_group_uncertain(spawn, scan):
    # Not a member, not a collision: a process leaving /proc between open and read
    # raises ProcessLookupError. Treat that as disappearance, just like ENOENT.
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


def test_foreign_session_holding_the_pgid_number_does_not_make_a_stopped_group_uncertain(foreign_session):
    # Same pgid number, different session: the group that owned it is gone and a
    # foreign session now holds the number.
    owned = stopped_group(pgid=foreign_session["pgid"], start_ticks=foreign_session["start_ticks"] - 100)
    assert owned["sid"] != foreign_session["sid"]
    assert _group_state(owned) == "stopped"


def test_foreign_zombie_holding_the_pgid_number_does_not_make_a_stopped_group_uncertain(foreign_zombie):
    # As above, but the holder is a dead, unreaped zombie.
    owned = stopped_group(pgid=foreign_zombie["pgid"], start_ticks=foreign_zombie["start_ticks"] - 100)
    assert _group_state(owned) == "stopped"


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


def test_foreign_session_holding_the_sid_number_does_not_make_a_stopped_group_live(foreign_session):
    # Same sid number, newer start: a newer session reusing the number, so nothing in it
    # is ours. It must not read `live`, which would also let _signal_owned_group signal
    # that foreign session's groups.
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


def test_recovery_of_a_stopped_run_is_not_refused_by_a_foreign_session_holding_a_pgid_number(
        tmp_path, foreign_session):
    path, receipt = recovery_inputs(tmp_path, stopped_group(
        pgid=foreign_session["pgid"], start_ticks=foreign_session["start_ticks"] - 100))
    assert recover(path, receipt)["state"] == "recovered"


def test_recovery_of_a_stopped_run_is_not_refused_by_a_newer_foreign_session_reusing_the_sid(
        tmp_path, foreign_session):
    path, receipt = recovery_inputs(tmp_path, stopped_group(
        pgid=foreign_session["pgid"], sid=foreign_session["sid"],
        start_ticks=foreign_session["start_ticks"] - 100))
    assert recover(path, receipt)["state"] == "recovered"


# --- scoped-scan edge paths (SC1952-02) --------------------------------------------------

@pytest.fixture
def killpg_calls(monkeypatch):
    """Replace os.killpg with a recorder: no test ever signals a process group."""
    calls = []
    monkeypatch.setattr(os, "killpg", lambda group, sig: calls.append((group, sig)))
    return calls


def owned_by(found, **override):
    """The recorded identity of the process ``found`` (from process_identity)."""
    fields = {"pid": found["pid"], "pgid": found["pgid"], "sid": found["sid"],
              "start_ticks": found["start_ticks"]}
    fields.update(override)
    return identity(**fields)


def make_zombie(spawn):
    proc = spawn(["true"])
    os.waitid(os.P_PID, proc.pid, os.WEXITED | os.WNOWAIT)
    found = process_identity(proc.pid)
    assert found["state"] == "Z"
    return found


@pytest.fixture
def leader_with_child(spawn):
    """A session leader whose child sits in its OWN process group of the same session."""
    leader = spawn([sys.executable, "-c",
                    "import subprocess,time\n"
                    "p = subprocess.Popen(['sleep', '300'], process_group=0)\n"
                    "print(p.pid, flush=True)\n"
                    "time.sleep(300)\n"], stdout=subprocess.PIPE, text=True)
    child_pid = int(leader.stdout.readline())
    leader.stdout.close()
    child = process_identity(child_pid)
    found = process_identity(leader.pid)
    assert child["sid"] == found["sid"] == leader.pid and child["pgid"] == child_pid != leader.pid
    assert found["start_ticks"] < child["start_ticks"]
    yield leader, found, child
    try:
        os.kill(child_pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


def kill_leader(leader, *, reap):
    leader.kill()
    if reap:
        leader.wait()
    else:
        os.waitid(os.P_PID, leader.pid, os.WEXITED | os.WNOWAIT)


@pytest.mark.parametrize("age", [-100, 0, 100])
def test_foreign_live_session_holding_the_pgid_number_is_unrelated_whatever_its_age(foreign_session, age):
    owned = stopped_group(pgid=foreign_session["pgid"], start_ticks=foreign_session["start_ticks"] + age)
    assert _group_state(owned) == "stopped"


@pytest.mark.parametrize("age", [-100, 0, 100])
def test_foreign_zombie_holding_the_pgid_number_is_unrelated_whatever_its_age(foreign_zombie, age):
    owned = stopped_group(pgid=foreign_zombie["pgid"], start_ticks=foreign_zombie["start_ticks"] + age)
    assert _group_state(owned) == "stopped"


def test_older_unrelated_session_with_other_numbers_is_ignored(foreign_session):
    assert _group_state(stopped_group(start_ticks=foreign_session["start_ticks"] + 100)) == "stopped"


@pytest.mark.parametrize("state", ["Z", "X"])
def test_dead_state_member_of_the_owned_session_does_not_count(foreign_session, monkeypatch, state):
    real = runner.process_identity
    monkeypatch.setattr(runner, "process_identity",
                        lambda pid: {**real(pid), "state": state} if pid == foreign_session["pid"] else real(pid))
    # An EARLIER member of the recorded session that is dead: neither uncertain nor live.
    owned = owned_by(foreign_session, pid=unreachable(), start_ticks=foreign_session["start_ticks"] + 100)
    assert _group_state(owned) == "stopped"


def test_own_zombie_only_group_is_stopped_even_when_older_than_the_record(foreign_zombie):
    owned = owned_by(foreign_zombie, pid=unreachable(), start_ticks=foreign_zombie["start_ticks"] + 100)
    assert _group_state(owned) == "stopped"


def test_newer_zombie_session_leader_reusing_the_sid_is_a_different_session(foreign_zombie):
    owned = stopped_group(sid=foreign_zombie["sid"], start_ticks=foreign_zombie["start_ticks"] - 100)
    assert _group_state(owned) == "stopped"


@pytest.mark.parametrize("collide_pgid", [False, True])
def test_newer_foreign_session_reusing_the_sid_is_never_signalled(foreign_session, killpg_calls, collide_pgid):
    owned = stopped_group(sid=foreign_session["sid"],
                          pgid=foreign_session["pgid"] if collide_pgid else None,
                          start_ticks=foreign_session["start_ticks"] - 100)
    assert _group_state(owned) == "stopped"
    runner._signal_owned_group(owned, signal.SIGTERM)
    assert killpg_calls == []


def test_older_live_member_of_the_recorded_session_keeps_the_verdict_uncertain(foreign_session, killpg_calls):
    # The process at the sid is OLDER than the record: it may really be ours, but it
    # cannot be proven, so the conservative earlier-live-member guard still refuses.
    owned = stopped_group(sid=foreign_session["sid"], start_ticks=foreign_session["start_ticks"] + 100)
    assert _group_state(owned) == "uncertain"
    with pytest.raises(RuntimeError, match="uncertain"):
        runner._signal_owned_group(owned, signal.SIGTERM)
    assert killpg_calls == []


def test_recorded_pid_reuse_stays_uncertain_and_is_not_signalled(foreign_session, killpg_calls):
    owned = owned_by(foreign_session, start_ticks=foreign_session["start_ticks"] + 100)
    assert _group_state(owned) == "uncertain"
    with pytest.raises(RuntimeError, match="uncertain"):
        runner._signal_owned_group(owned, signal.SIGTERM)
    assert killpg_calls == []


def test_exact_live_group_is_live_and_its_own_group_is_signalled(foreign_session, killpg_calls):
    owned = owned_by(foreign_session)
    assert _group_state(owned) == "live"
    runner._signal_owned_group(owned, signal.SIGTERM)
    assert killpg_calls == [(foreign_session["pgid"], signal.SIGTERM)]


@pytest.mark.parametrize("leader_first", [True, False])
def test_unrelated_sessions_around_a_live_group_do_not_change_its_verdict(spawn, scan, leader_first):
    mine, other = spawn(["sleep", "300"]), spawn(["sleep", "300"])
    owned = owned_by(process_identity(mine.pid))
    scan.only(*((mine.pid, other.pid) if leader_first else (other.pid, mine.pid)))
    assert _group_state(owned) == "live"


@pytest.mark.parametrize("zombie_first", [True, False])
def test_foreign_zombie_and_live_holders_of_a_pgid_number_in_either_order(spawn, scan, zombie_first):
    live, dead = process_identity(spawn(["sleep", "300"]).pid), make_zombie(spawn)
    owned = stopped_group(pgid=live["pgid"], start_ticks=live["start_ticks"] - 100)
    scan.only(*((dead["pid"], live["pid"]) if zombie_first else (live["pid"], dead["pid"])))
    assert _group_state(owned) == "stopped"
    owned = stopped_group(pgid=dead["pgid"], start_ticks=dead["start_ticks"] + 100)
    assert _group_state(owned) == "stopped"


@pytest.mark.parametrize("leader_first", [True, False])
def test_dead_older_leader_with_live_descendant_in_another_pgid_is_live(leader_with_child, scan, killpg_calls,
                                                                         leader_first):
    leader, found, child = leader_with_child
    kill_leader(leader, reap=False)
    scan.only(*((leader.pid, child["pid"]) if leader_first else (child["pid"], leader.pid)))
    # The recorded process is the zombie leader: its descendants are still the group's.
    owned = owned_by(found)
    assert _group_state(owned) == "live"
    # And the descendant's own record, with the older zombie leader sharing its session.
    assert _group_state(owned_by(child)) == "live"
    runner._signal_owned_group(owned, signal.SIGTERM)
    assert killpg_calls == [(child["pgid"], signal.SIGTERM)]


def test_missing_leader_with_a_surviving_descendant_is_not_stopped(leader_with_child, scan):
    leader, found, child = leader_with_child
    kill_leader(leader, reap=True)
    assert process_identity(leader.pid) is None
    scan.only(child["pid"])
    assert _group_state(owned_by(found)) == "live"


def test_missing_leader_with_no_survivor_is_stopped(leader_with_child, scan):
    leader, found, child = leader_with_child
    kill_leader(leader, reap=True)
    scan.only()
    assert _group_state(owned_by(found)) == "stopped"


def test_vanishing_entry_enoent_is_not_uncertain(foreign_session, scan):
    def gone(path):
        raise FileNotFoundError(path)

    scan.on_read(foreign_session["pid"], gone)
    assert _group_state(stopped_group()) == "stopped"


def test_permission_denied_reading_a_scanned_entry_stays_uncertain(foreign_session, scan, killpg_calls):
    def denied(path):
        raise PermissionError(path)

    scan.on_read(foreign_session["pid"], denied)
    assert _group_state(stopped_group()) == "uncertain"


def test_malformed_stat_of_a_scanned_entry_stays_uncertain(foreign_session, scan):
    scan.on_read(foreign_session["pid"], lambda path: "garbage without a closing paren")
    assert _group_state(stopped_group()) == "uncertain"


def test_unreadable_session_leader_stays_uncertain_not_stopped(foreign_session, scan, killpg_calls):
    def denied(path):
        raise PermissionError(path)

    scan.on_read(foreign_session["pid"], denied)   # the first read is the sid-leader probe
    owned = stopped_group(sid=foreign_session["sid"], start_ticks=foreign_session["start_ticks"] - 100)
    assert _group_state(owned) == "uncertain"
    scan.on_read(foreign_session["pid"], denied)   # hooks fire once: arm the gate's own probe
    with pytest.raises(RuntimeError, match="uncertain"):
        runner._signal_owned_group(owned, signal.SIGTERM)
    assert killpg_calls == []


def test_inconsistent_session_leader_record_stays_uncertain(foreign_session, monkeypatch):
    real = runner.process_identity
    monkeypatch.setattr(runner, "process_identity",
                        lambda pid: {**real(pid), "sid": real(pid)["sid"] + 1} if pid == foreign_session["sid"]
                        else real(pid))
    owned = stopped_group(sid=foreign_session["sid"], start_ticks=foreign_session["start_ticks"] - 100)
    assert _group_state(owned) == "uncertain"


def test_failed_boot_id_read_stays_uncertain(scan, monkeypatch):
    owned = stopped_group()

    def broken():
        raise PermissionError("boot_id")

    monkeypatch.setattr(runner, "boot_id", broken)
    assert _group_state(owned) == "uncertain"


def test_previous_boot_is_stopped_whatever_runs_now(foreign_session):
    owned = owned_by(foreign_session)
    owned["boot_id"] = str(uuid.uuid4())
    assert _group_state(owned) == "stopped"


@pytest.mark.parametrize("damage", ["not-a-dict", "missing-pgid", "bool-pid", "zero-start", "negative-sid",
                                    "float-pgid", "bad-uuid", "foreign-host"])
def test_bad_recorded_identities_stay_uncertain(foreign_session, killpg_calls, damage):
    owned = owned_by(foreign_session)
    if damage == "not-a-dict":
        owned = [owned]
    elif damage == "missing-pgid":
        del owned["pgid"]
    elif damage == "bool-pid":
        owned["pid"] = True
    elif damage == "zero-start":
        owned["start_ticks"] = 0
    elif damage == "negative-sid":
        owned["sid"] = -foreign_session["sid"]
    elif damage == "float-pgid":
        owned["pgid"] = float(foreign_session["pgid"])
    elif damage == "bad-uuid":
        owned["boot_id"] = "not-a-uuid"
    else:
        owned["host"] = "some-other-host"
    assert _group_state(owned) == "uncertain"
    with pytest.raises(RuntimeError, match="uncertain"):
        runner._signal_owned_group(owned, signal.SIGTERM)
    assert killpg_calls == []
