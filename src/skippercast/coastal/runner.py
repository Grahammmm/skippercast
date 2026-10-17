"""One Linux bounded subprocess protocol with a parent-independent supervisor.

The supervisor owns and reaps descendants, including detached sessions, and
captures bounded output. Recovery never signals a PID. New-protocol recovery
requires complete durable descendant ownership proof; a partial ledger cannot
prove universal absence after a supervisor crash on the same boot.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
import fcntl
import io
import json
import math
import os
from pathlib import Path
import resource
import selectors
import signal
import socket
import subprocess
import sys
import time
import threading
import uuid

from ._owned_processes import OwnedChildren, PROTOCOL
from .receipts import (SYSTEM_CLOCK, atomic_json, digest, epoch, file_sha256, monotonic, utc,
                       managed_configuration, managed_writer, managed_writes)


@dataclass(frozen=True)
class Outcome:
    status: str
    rc: int | None
    elapsed: float
    pid: int | None
    intent_path: str
    stdout_path: str
    stderr_path: str

    @property
    def returncode(self):
        return self.rc


@contextmanager
def _locked(path):
    with open(str(path) + ".lock", "a+b") as stream:
        fcntl.flock(stream, fcntl.LOCK_EX)
        yield


def boot_id():
    return Path("/proc/sys/kernel/random/boot_id").read_text().strip()


def process_identity(pid):
    """Linux PID identity; numeric PID alone is never proof of ownership."""
    try:
        raw = Path(f"/proc/{pid}/stat").read_text()
        fields = raw[raw.rindex(")") + 2:].split()
        return {"host": socket.gethostname(), "boot_id": boot_id(), "pid": int(pid),
                "start_ticks": int(fields[19]), "pgid": int(fields[2]),
                "sid": int(fields[3]), "ppid": int(fields[1]), "state": fields[0]}
    except FileNotFoundError:
        return None


def _group_state(identity):
    """Return stopped/live/uncertain without signalling or trusting an attestation."""
    if not isinstance(identity, dict):
        return "uncertain"
    required = ("host", "boot_id", "pid", "start_ticks", "pgid", "sid")
    if any(key not in identity for key in required):
        return "uncertain"
    for key in ("pid", "start_ticks", "pgid", "sid"):
        if isinstance(identity[key], bool) or not isinstance(identity[key], int) or identity[key] <= 0:
            return "uncertain"
    try:
        uuid.UUID(identity["boot_id"])
    except (ValueError, TypeError, AttributeError):
        return "uncertain"
    if identity["host"] != socket.gethostname():
        return "uncertain"
    try:
        if identity["boot_id"] != boot_id():
            return "stopped"
        leader = process_identity(identity["pid"])
        if leader is not None and leader["start_ticks"] != identity["start_ticks"]:
            return "uncertain"
        live = False
        for entry in Path("/proc").iterdir():
            if not entry.name.isdigit():
                continue
            member = process_identity(int(entry.name))
            if member is None:
                continue
            if member["pgid"] == identity["pgid"] or member["sid"] == identity["sid"]:
                if member["sid"] != identity["sid"] or member["start_ticks"] < identity["start_ticks"]:
                    return "uncertain"
                if member["state"] not in {"Z", "X"}:
                    live = True
        return "live" if live else "stopped"
    except (OSError, ValueError, IndexError, KeyError):
        return "uncertain"


def _signal_owned_group(identity, sig):
    """Only signal the exact still-owned group, never a reused numeric PID."""
    state = _group_state(identity)
    if state == "uncertain":
        raise RuntimeError("owned process-group identity is uncertain; refusing signal")
    if state == "stopped":
        return
    # A session may contain extra child process groups. Match the recorded
    # session and signal each observed group after rechecking its members.
    groups = set()
    for entry in Path("/proc").iterdir():
        if entry.name.isdigit():
            member = process_identity(int(entry.name))
            if member and member["sid"] == identity["sid"] and member["state"] not in {"Z", "X"}:
                if member["start_ticks"] < identity["start_ticks"]:
                    raise RuntimeError("session member identity is uncertain")
                groups.add(member["pgid"])
    for group in groups:
        # Recheck before signalling: disappearing groups are fine; a new session
        # reusing this numeric group is not ours.
        observed = []
        for entry in Path("/proc").iterdir():
            if entry.name.isdigit():
                member = process_identity(int(entry.name))
                if member and member["pgid"] == group and member["state"] not in {"Z", "X"}:
                    observed.append(member)
        if any(m["sid"] != identity["sid"] or m["start_ticks"] < identity["start_ticks"] for m in observed):
            raise RuntimeError("process group was reused; refusing signal")
        if observed:
            try:
                os.killpg(group, sig)
            except ProcessLookupError:
                pass


def _stop_group(identity, grace_s):
    _signal_owned_group(identity, signal.SIGTERM)
    end = SYSTEM_CLOCK.monotonic() + grace_s
    while _group_state(identity) == "live" and SYSTEM_CLOCK.monotonic() < end:
        time.sleep(0.01)
    if _group_state(identity) == "live":
        _signal_owned_group(identity, signal.SIGKILL)
    end = SYSTEM_CLOCK.monotonic() + max(1.0, grace_s)
    while _group_state(identity) == "live" and SYSTEM_CLOCK.monotonic() < end:
        time.sleep(0.01)
    return _group_state(identity) == "stopped"


def _write_state(path, **updates):
    with _locked(path):
        state = json.loads(Path(path).read_text())
        state.update(updates)
        atomic_json(path, state)
        return state


def _limits(values):
    accepted = {"memory_bytes": resource.RLIMIT_AS, "cpu_s": resource.RLIMIT_CPU,
                "file_bytes": resource.RLIMIT_FSIZE, "open_files": resource.RLIMIT_NOFILE}
    result = {}
    for key, value in (values or {}).items():
        if key not in accepted:
            raise ValueError(f"unknown resource limit: {key}")
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ValueError(f"resource limit {key} must be a positive integer")
        result[key] = value
    return result


def _deadline(value):
    if value is None:
        return None
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if isinstance(value, datetime):
        if value.tzinfo is None:
            raise ValueError("deadline needs an aware datetime")
        value = value.timestamp()
    if isinstance(value, bool) or not math.isfinite(float(value)):
        raise ValueError("deadline must be finite")
    return float(value)


def _positive(value, name, *, zero=False):
    if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value):
        raise ValueError(f"{name} must be finite")
    if value < 0 if zero else value <= 0:
        raise ValueError(f"{name} must be {'non-negative' if zero else 'positive'}")
    return float(value)


def admit_managed_runtime(intent, configuration, *, scratch=None, stdout_path=None,
                          stderr_path=None, output_limit_bytes=16384):
    """Reserve the fixed runtime file envelope before any source reservation."""
    if type(output_limit_bytes) is not int or not 0 < output_limit_bytes <= 16384:
        raise ValueError("bounded managed runtime log allowance required")
    intent = Path(intent).absolute()
    scratch = Path(scratch).absolute() if scratch is not None else intent.with_name(intent.name + ".scratch")
    stdout = Path(stdout_path).absolute() if stdout_path else scratch / "stdout"
    stderr = Path(stderr_path).absolute() if stderr_path else scratch / "stderr"
    with managed_writes(configuration) as writer:
        if writer is None:
            raise ValueError("explicit managed runtime grant required")
        configuration = managed_configuration()
        if intent.exists() or intent.is_symlink():
            raise FileExistsError("existing runtime intent preserved")
        name = writer.relative_path(intent)
        checkpoint_intent = "checkpoint:" + name
        writer.reserve_file(name, role=configuration["role"], max_bytes=configuration["max_bytes"],
                            intent=checkpoint_intent)
        writer.reserve_file(".managed-checkpoints/" + name, role=configuration["role"],
                            max_bytes=configuration["max_bytes"],
                            intent=digest([checkpoint_intent, "checkpoint-temporary"]))
        for output in (stdout, stderr):
            name = writer.relative_path(output)
            if output.exists() or output.is_symlink():
                raise FileExistsError("existing runtime log preserved")
            writer.reserve_file(name, role=configuration["role"], max_bytes=output_limit_bytes,
                                intent="runner-log:" + name)
        return writer.audit()


def run_bounded(argv, *, managed_output=None, **kwargs):
    """Run the legacy protocol, with optional exact managed output fencing."""
    configuration = managed_output if managed_output is not None else managed_configuration()
    with managed_writes(configuration):
        return _run_bounded(argv, managed_output=managed_configuration(), **kwargs)


def _run_bounded(argv, *, intent, deadline_utc=None, timeout_s=None,
                byte_reservation=None, rlimits=None, env=None, grace_s=2,
                clock=None, scratch=None, cancel=None, cwd=None,
                stdout_path=None, stderr_path=None, output_limit_bytes=1048576,
                identity_callback=None, execution_binding=None, managed_output=None):
    """Persist launch intent then supervise one bounded target without a shell.

    intent and scratch/output files must be fresh paths. Failures before the
    durable launch intent never leave a RUNNING checkpoint. Failed/uncertain
    operations preserve byte_reservation verbatim; this runner never refunds it.
    cancel is a callable or threading.Event-like object polled by the parent.
    """
    if not isinstance(argv, (list, tuple)) or not argv or any(not isinstance(a, str) or "\0" in a for a in argv):
        raise ValueError("run_bounded argv must be a nonempty string sequence")
    if not Path("/proc/self/stat").exists():
        raise RuntimeError("bounded supervisor requires Linux /proc")
    if execution_binding is not None:
        if not isinstance(execution_binding, str) or len(execution_binding) != 64 or any(
                c not in "0123456789abcdef" for c in execution_binding):
            raise ValueError("execution_binding must be a SHA-256 capability identity")
    limits = _limits(rlimits)
    grace_s = _positive(grace_s, "grace_s", zero=True)
    if isinstance(output_limit_bytes, bool) or not isinstance(output_limit_bytes, int) or output_limit_bytes <= 0:
        raise ValueError("output_limit_bytes must be a positive integer")
    if byte_reservation is not None and (isinstance(byte_reservation, bool) or not isinstance(byte_reservation, int) or byte_reservation < 0):
        raise ValueError("byte_reservation must be a non-negative integer")
    deadline_epoch = _deadline(deadline_utc)
    duration = None if timeout_s is None else _positive(timeout_s, "timeout_s")
    if deadline_epoch is not None:
        until = deadline_epoch - epoch(clock)
        duration = until if duration is None else min(duration, until)
    if duration is None or duration <= 0:
        raise ValueError("a future deadline or positive timeout_s is required")
    if env is not None and (not isinstance(env, dict) or any(
            not isinstance(k, str) or not isinstance(v, str) or "\0" in k + v or "=" in k for k, v in env.items())):
        raise ValueError("env must map valid environment names to strings")
    if cwd is not None:
        cwd = str(Path(cwd).resolve(strict=True))
        if not Path(cwd).is_dir():
            raise ValueError("cwd must be a directory")
    intent = Path(intent).absolute()
    scratch = Path(scratch).absolute() if scratch is not None else intent.with_name(intent.name + ".scratch")
    stdout = Path(stdout_path).absolute() if stdout_path else scratch / "stdout"
    stderr = Path(stderr_path).absolute() if stderr_path else scratch / "stderr"
    started = monotonic(clock)
    enforce_started = SYSTEM_CLOCK.monotonic()
    with _locked(intent):
        if intent.exists():
            raise FileExistsError(f"run_bounded intent already exists: {intent}")
        # All filesystem collision checks happen before the launch intent.
        scratch.mkdir(exist_ok=False)
        created = []
        try:
            for output in (stdout, stderr):
                if managed_output is not None:
                    if output.exists() or output.is_symlink():
                        raise FileExistsError("managed runner output already exists")
                    writer = managed_writer()
                    name = writer.relative_path(output)
                    writer.reserve_file(name, role=managed_output["role"],
                                        max_bytes=output_limit_bytes, intent="runner-log:" + name)
                else:
                    fd = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
                    os.close(fd)
                    created.append(output)
        except BaseException:
            for output in created:
                output.unlink()
            scratch.rmdir()
            raise
        state = {"schema": "coastal-run-intent-v1", "state": "launching", "argv": list(argv),
                 "parent": process_identity(os.getpid()), "supervisor": None, "child": None,
                 "ownership_protocol": PROTOCOL, "ownership_complete": False, "owned_descendants": [],
                 "created_utc": utc(clock), "boot_id": boot_id(), "execution_binding": execution_binding, "duration_s": duration,
                 "deadline_epoch": deadline_epoch, "enforce_deadline_monotonic": enforce_started + duration,
                 "grace_s": grace_s, "byte_reservation": byte_reservation,
                 "rlimits": limits, "env": env or {}, "cwd": cwd,
                 "stdout_path": str(stdout), "stderr_path": str(stderr),
                 "output_limit_bytes": output_limit_bytes, "cancel_requested": False,
                 "status": None, "rc": None}
        if managed_output is not None:
            state["managed_output"] = managed_output
        atomic_json(intent, state)
    supervisor_env = dict(os.environ)
    # Isolated supervisor/gate interpreters ignore PYTHONPATH. Ordinary targets
    # inherit this trusted absolute prefix after exec, regardless of artifact cwd;
    # explicit target env overrides still take precedence in _supervise.
    package_root = str(Path(__file__).resolve().parents[2])
    supervisor_env["PYTHONPATH"] = package_root + os.pathsep + supervisor_env.get("PYTHONPATH", "")
    bootstrap = str(Path(__file__).resolve().with_name("_runner_bootstrap.py"))
    try:
        supervisor = subprocess.Popen(
            [sys.executable, "-I", bootstrap, "--supervise", str(intent)],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            start_new_session=True, env=supervisor_env, close_fds=True)
    except OSError as exc:
        if managed_output is not None:
            writer = managed_writer()
            for output in (stdout, stderr):
                name = writer.relative_path(output)
                writer.write_bytes(name, b"", role=managed_output["role"],
                                   max_bytes=output_limit_bytes, intent="runner-log:" + name)
        state = _write_state(intent, state="finished", status="failed_launch", rc=None,
                             error=f"{type(exc).__name__}: {exc}", processes_stopped=True, ownership_complete=True)
        return _outcome(intent, state, max(0, monotonic(clock) - started))
    reported = False
    interrupted = False
    saved_handlers = {}
    if threading.current_thread() is threading.main_thread():
        def parent_signal(signum, frame):
            raise KeyboardInterrupt(f"runner parent received signal {signum}")
        for signum in (signal.SIGTERM, signal.SIGHUP):
            previous = signal.getsignal(signum)
            if previous == signal.SIG_DFL:
                saved_handlers[signum] = previous
                signal.signal(signum, parent_signal)
    try:
        while supervisor.poll() is None:
            with _locked(intent):
                state = json.loads(intent.read_text())
            if state.get("child") and not reported:
                if identity_callback:
                    identity_callback(dict(state["child"]))
                reported = True
            cancelled = cancel and (cancel.is_set() if hasattr(cancel, "is_set") else cancel())
            if cancelled:
                _write_state(intent, cancel_requested=True)
            time.sleep(0.01)
    except BaseException as exc:
        interrupted = True
        _write_state(intent, cancel_requested=True, parent_interruption=f"{type(exc).__name__}: {exc}")
        # The independent supervisor does the cleanup; wait only within a bound.
        try:
            supervisor.wait(timeout=grace_s + 3)
        except subprocess.TimeoutExpired:
            pass
        if not isinstance(exc, (KeyboardInterrupt, SystemExit)):
            raise
    finally:
        for signum, previous in saved_handlers.items():
            signal.signal(signum, previous)
    with _locked(intent):
        state = json.loads(intent.read_text())
    if state.get("state") != "finished":
        state = _write_state(intent, state="failed_uncertain", status="failed_uncertain",
                             error="supervisor exited without a complete outcome")
    elif interrupted:
        state = _write_state(intent, status="interrupted")
    if state.get("child") and not reported and identity_callback:
        identity_callback(dict(state["child"]))
    return _outcome(intent, state, max(0, monotonic(clock) - started))


def _outcome(intent, state, elapsed):
    child = state.get("child") or {}
    return Outcome(state.get("status") or "failed_uncertain", state.get("rc"), elapsed,
                   child.get("pid"), str(intent), state["stdout_path"], state["stderr_path"])


def _supervise(path):
    state = json.loads(Path(path).read_text())
    with managed_writes(state.get("managed_output")):
        return _supervise_impl(path)


def _supervise_impl(path):
    """Detached host supervisor. Uses a real monotonic deadline, not an env hint."""
    path = Path(path)
    state = _write_state(path, supervisor=process_identity(os.getpid()), state="supervising")
    stopped = False
    child = None
    identity = None
    owned = None
    total = 0
    status = "failed_uncertain"
    rc = None
    selector = selectors.DefaultSelector()
    outputs = []
    received_signal = False

    def interrupt(signum, frame):
        nonlocal received_signal
        received_signal = True

    signal.signal(signal.SIGTERM, interrupt)
    signal.signal(signal.SIGINT, interrupt)
    signal.signal(signal.SIGHUP, interrupt)

    def apply_limits():
        mapping = {"memory_bytes": resource.RLIMIT_AS, "cpu_s": resource.RLIMIT_CPU,
                   "file_bytes": resource.RLIMIT_FSIZE, "open_files": resource.RLIMIT_NOFILE}
        for key, value in state["rlimits"].items():
            resource.setrlimit(mapping[key], (value, value))

    try:
        owned = OwnedChildren(process_identity, lambda identities: _write_state(
            path, owned_descendants=identities, ownership_complete=False))
        target_env = dict(os.environ)
        target_env.update(state["env"])
        target_env["COASTAL_DEADLINE_EPOCH"] = str(state["deadline_epoch"] if state["deadline_epoch"] is not None
                                                   else epoch() + max(0, state["enforce_deadline_monotonic"] - SYSTEM_CLOCK.monotonic()))
        # The child blocks on a launch gate until its identity is durable. That
        # closes the spawn-to-identity race even if this supervisor is killed.
        gate_read, gate_write = os.pipe()
        # Inherited environment and target argv can contain secrets. A private
        # inherited memfd transports them without exposing them in /proc cmdline
        # or hitting Linux's per-argument length bound.
        config_fd = os.memfd_create("coastal-target-config", os.MFD_CLOEXEC)
        try:
            config = json.dumps({"argv": state["argv"], "env": target_env}).encode()
            with os.fdopen(os.dup(config_fd), "wb") as config_stream:
                config_stream.write(config)
                config_stream.flush()
            os.lseek(config_fd, 0, os.SEEK_SET)
            child = subprocess.Popen(
                [sys.executable, "-I", str(Path(__file__).resolve().with_name("_runner_bootstrap.py")),
                 "--target", str(gate_read), str(config_fd)],
                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                start_new_session=True, env=dict(os.environ), cwd=state["cwd"], close_fds=True,
                pass_fds=(gate_read, config_fd), preexec_fn=apply_limits)
        finally:
            os.close(config_fd)
            os.close(gate_read)
        identity = process_identity(child.pid)
        if identity is None:
            os.close(gate_write)
            raise RuntimeError("target identity unavailable before launch gate")
        owned.observe()
        _write_state(path, child=identity, state="running")
        os.write(gate_write, b"1")
        os.close(gate_write)
        for stream, output_path in ((child.stdout, state["stdout_path"]), (child.stderr, state["stderr_path"])):
            os.set_blocking(stream.fileno(), False)
            if state.get("managed_output") is not None:
                output = io.BytesIO()
            else:
                fd = os.open(output_path, os.O_WRONLY | os.O_NOFOLLOW)
                output = os.fdopen(fd, "wb")
            outputs.append(output)
            selector.register(stream, selectors.EVENT_READ, output)
        while True:
            owned.observe()
            current = json.loads(path.read_text())
            if received_signal or current.get("cancel_requested"):
                status = "killed"
                break
            if SYSTEM_CLOCK.monotonic() >= state["enforce_deadline_monotonic"]:
                status = "timeout"
                break
            for key, _ in selector.select(timeout=0.01):
                part = os.read(key.fileobj.fileno(), 65536)
                if not part:
                    selector.unregister(key.fileobj)
                    key.fileobj.close()
                    continue
                available = state["output_limit_bytes"] - total
                key.data.write(part[:available])
                total += len(part)
                if total > state["output_limit_bytes"]:
                    status = "output_limit"
                    break
            if status == "output_limit":
                break
            rc = child.poll()
            if rc is not None and not selector.get_map():
                status = "ok" if rc == 0 else "failed_uncertain"
                break
        stopped = owned.stop(child, state["grace_s"])
        child.wait(timeout=max(1, state["grace_s"]))
        rc = child.returncode
        if not stopped:
            status = "failed_uncertain"
        # A wrapper's exec failure uses 127 and must never be credited as success.
        if rc == 127 and status == "failed_uncertain":
            status = "failed_launch"
    except BaseException as exc:
        if owned is not None:
            try:
                stopped = owned.stop(child, state["grace_s"])
            except BaseException:
                stopped = False
        elif child is None:
            stopped = True  # No target was spawned before ownership setup failed.
        status = "failed_launch" if child is None else "failed_uncertain"
        _write_state(path, error=f"{type(exc).__name__}: {exc}")
    finally:
        if owned is not None:
            owned.close()
        selector.close()
        publication_error = None
        try:
            if state.get("managed_output") is not None:
                writer = managed_writer()
                for index, output_path in enumerate((state["stdout_path"], state["stderr_path"])):
                    data = outputs[index].getvalue() if index < len(outputs) else b""
                    name = writer.relative_path(output_path)
                    writer.write_bytes(name, data, role=state["managed_output"]["role"],
                                       max_bytes=state["output_limit_bytes"], intent="runner-log:" + name)
        except BaseException as exc:
            publication_error = f"{type(exc).__name__}: {exc}"
            status = "failed_uncertain"
        finally:
            for output in outputs:
                try:
                    output.flush()
                    if state.get("managed_output") is None:
                        os.fsync(output.fileno())
                finally:
                    output.close()
        for directory_path in {Path(state["stdout_path"]).parent, Path(state["stderr_path"]).parent}:
            directory_fd = os.open(directory_path, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        captured_outputs = []
        for output_path in (state["stdout_path"], state["stderr_path"]):
            output_path = Path(output_path)
            if publication_error is not None and not output_path.exists():
                continue
            captured_outputs.append({"path": str(output_path), "bytes": output_path.stat().st_size,
                                     "sha256": file_sha256(output_path, cap=state["output_limit_bytes"])})
        terminal = dict(state="finished" if stopped and publication_error is None else "failed_uncertain",
                        status=status, rc=rc, output_bytes=min(total, state["output_limit_bytes"]),
                        outputs=captured_outputs, processes_stopped=stopped,
                        ownership_complete=stopped, finished_utc=utc())
        if publication_error is not None:
            terminal.update(error="managed log publication failed: " + publication_error,
                            output_publication_complete=False)
        _write_state(path, **terminal)


def recover(intent, receipt):
    state = json.loads(Path(intent).read_text())
    with managed_writes(state.get("managed_output")):
        return _recover(intent, receipt)


def _recover(intent, receipt):
    """Accept one hash-bound recovery only after every owned group has stopped.

    Preserve the original checkpoint so a crash after intent recovery but before a
    consuming ledger transaction can safely replay the exact same proof. Replays
    validate all current bytes against the one allowed mutation and recheck groups.
    """
    intent = Path(intent)
    receipt = json.loads(Path(receipt).read_text()) if isinstance(receipt, (str, Path)) else receipt
    with _locked(intent):
        state = json.loads(intent.read_text())
        original = state
        already_recovered = state.get("state") == "recovered"
        if already_recovered:
            original = state.get("recovery_checkpoint")
            if not isinstance(original, dict):
                raise ValueError("recovery replay has no original checkpoint; identity uncertain")
            expected = dict(original)
            expected.update(state="recovered", status="failed_uncertain", recovery=receipt,
                            processes_stopped=True, recovery_checkpoint=original)
            if state != expected:
                raise ValueError("recovery replay receipt or recovered intent bytes mismatch")
        if original.get("schema") != "coastal-run-intent-v1":
            raise ValueError("recovery intent schema invalid")
        try:
            uuid.UUID(original.get("boot_id"))
        except (ValueError, TypeError, AttributeError):
            raise ValueError("recovery intent boot identity invalid") from None
        if not isinstance(receipt, dict) or receipt.get("schema") != "coastal-recovery-v1":
            raise ValueError("recover requires coastal-recovery-v1")
        if receipt.get("checkpoint_sha256") != digest(original):
            raise ValueError("recovery checkpoint hash mismatch")
        if receipt.get("processes_stopped") is not True or not isinstance(receipt.get("attested_by"), str) or not receipt["attested_by"].strip():
            raise ValueError("recovery requires stopped attestation and attested_by")
        identities = [original.get("supervisor"), original.get("child")]
        if original.get("ownership_protocol") not in {None, PROTOCOL}:
            raise ValueError("recovery refused: descendant ownership protocol is uncertain")
        new_protocol = original.get("ownership_protocol") == PROTOCOL
        if new_protocol and original.get("boot_id") == boot_id():
            descendants = original.get("owned_descendants")
            if not isinstance(descendants, list):
                raise ValueError("recovery refused: descendant ownership identities are uncertain")
            identities.extend(descendants)
        if original.get("boot_id") != boot_id():
            states = ["stopped", "stopped"]
        else:
            states = [_group_state(i) for i in identities if i is not None]
            if original.get("supervisor") is None and original.get("state") != "finished":
                states.append("uncertain")
            if original.get("child") is None and not original.get("processes_stopped"):
                states.append("uncertain")
        if "live" in states:
            raise ValueError("recovery refused: owned process group is live")
        if "uncertain" in states:
            raise ValueError("recovery refused: owned process identity is uncertain")
        if new_protocol and original.get("boot_id") == boot_id():
            if original.get("ownership_complete") is not True or original.get("processes_stopped") is not True:
                raise ValueError("recovery refused: descendant ownership proof is incomplete")
        if already_recovered:
            return state
        recovered = dict(original)
        recovered.update(state="recovered", status="failed_uncertain", recovery=receipt,
                         processes_stopped=True, recovery_checkpoint=original)
        atomic_json(intent, recovered)
        return recovered


def _target(gate_fd, config_fd):
    with os.fdopen(config_fd, "rb") as config_stream:
        config = json.load(config_stream)
    if os.read(gate_fd, 1) != b"1":
        raise SystemExit(125)
    os.close(gate_fd)
    try:
        os.execvpe(config["argv"][0], config["argv"], config["env"])
    except OSError as exc:
        print(f"launch {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(127)


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--supervise":
        _supervise(sys.argv[2])
    elif len(sys.argv) == 4 and sys.argv[1] == "--target":
        _target(int(sys.argv[2]), int(sys.argv[3]))
    else:
        raise SystemExit("runner is an internal supervisor, not a shell")
