"""Private trial envelope: command construction and read-only verification, never service launch."""
import datetime as dt
import math
import os
from pathlib import Path
import re
import subprocess
import time
import uuid

SCHEMA = "coastal-authenticated-unit-v1"
# Every transient unit, the shared slice and the trial scratch carry one run tag.
# The default keeps the 2026-10-11 attempt's names readable; a fresh run names
# its own tag so it never collides with (or reuses) an earlier attempt's units
# or scratch.
HISTORICAL_RUN_TAG = "20261011"
RUN_TAG = os.environ.get("SKIPPERCAST_FOUR128_RUN_TAG", HISTORICAL_RUN_TAG)
if not re.fullmatch(r"[0-9]{8}[a-z0-9]{0,8}", RUN_TAG):
    raise ValueError("run tag must be YYYYMMDD plus up to 8 lowercase letters/digits")
SLICE = "skippercast-four128approved" + RUN_TAG + ".slice"
UNITS = {key: 'skippercast-four128approved-' + key.lower() + '-' + RUN_TAG + '.service' for key in ['probe'] + [w+'-'+stage for w in 'ABCD' for stage in ('acquire','qualify','map','hold')]}
UNITS.update({w+'-review-'+stage:'skippercast-four128approved-'+w.lower()+'-review-'+stage+'-'+RUN_TAG+'.service' for w in 'ABCD' for stage in ('acquire','qualify')})
UNITS.update({key:"skippercast-four128approved-"+key+"-"+RUN_TAG+".service" for key in ("source-size-probe","interrupted-map","recovery-map","render-handoff","terrain-review","render-handoff-recovered","terrain-review-recovered")})
CONTROL_UNITS = {key:"skippercast-four128approved-"+key+RUN_TAG+".service" for key in ("watchdog","driver")}
ENV = {"PYTHONDONTWRITEBYTECODE": "1", "OMP_NUM_THREADS": "1",
       "OPENBLAS_NUM_THREADS": "1", "MKL_NUM_THREADS": "1",
       "GDAL_NUM_THREADS": "1", "PROJ_NETWORK": "OFF"}

def launch_command(phase, python, wrapper):
    if phase not in UNITS:
        raise ValueError("fixed phase required")
    if not Path(python).is_absolute() or not Path(wrapper).is_absolute():
        raise ValueError("pinned absolute runtime paths required")
    args = ["/usr/bin/systemd-run", "--user", "--wait", "--pipe", "--collect",
            "--unit=" + UNITS[phase], "--slice=" + SLICE,
            "--property=RuntimeMaxSec=180", "--property=KillMode=control-group",
            "--property=KillSignal=SIGKILL", "--property=MemoryMax=1073741824",
            "--property=MemorySwapMax=0", "--property=CPUQuota=200%",
            "--property=TasksMax=32"]
    args += ["--setenv=" + key + "=" + value for key, value in ENV.items()]
    return args + [str(python), "-I", str(wrapper), "execute", phase]

def validate(phase, properties, membership, readings, affinity, *,
             utc_now, monotonic_now, boot_id, own_pid):
    """Pure validation; callers bind this observation to the exact released wrapper."""
    if phase not in UNITS or str(uuid.UUID(boot_id)) != boot_id:
        raise ValueError("fixed phase and boot identity required")
    for value in (utc_now, monotonic_now):
        if type(value) not in (int, float) or not math.isfinite(value):
            raise ValueError("finite clock required")
    expected = {"KillMode": "control-group", "KillSignal": "9",
                "MemoryMax": "1073741824", "TasksMax": "32",
                "CPUQuotaPerSecUSec": "2s", "ActiveState": "active"}
    if any(properties.get(key) != value for key, value in expected.items()):
        raise ValueError("actual transient resource properties mismatch")
    if properties.get("RuntimeMaxUSec") not in ("3min", "180s"):
        raise ValueError("actual 180-second runtime limit required")
    invocation = properties.get("InvocationID", "")
    if not re.fullmatch("[0-9a-f]{32}", invocation) or invocation == "0" * 32:
        raise ValueError("actual unit invocation identity required")
    if int(properties.get("ExecMainPID", "0")) != own_pid or own_pid <= 0:
        raise ValueError("wrapper must be the fixed unit main process")
    if not membership.startswith("0::/") or "\n" in membership:
        raise ValueError("single unified cgroup membership required")
    cg = membership[3:]
    if (".." in Path(cg).parts or properties.get("ControlGroup") != cg
            or Path(cg).name != UNITS[phase]):
        raise ValueError("actual fixed unit cgroup membership mismatch")
    if readings != {"memory.max": "1073741824", "memory.swap.max": "0",
                    "cpu.max": "200000 100000", "pids.max": "32"}:
        raise ValueError("actual hard cgroup limits mismatch")
    if (not isinstance(affinity, list) or not 1 <= len(affinity) <= 2
            or len(set(affinity)) != len(affinity)
            or any(type(cpu) is not int or cpu < 0 for cpu in affinity)):
        raise ValueError("actual one- or two-CPU affinity required")
    started = int(properties.get("ExecMainStartTimestampMonotonic", "0")) / 1_000_000
    if not 0 < started <= monotonic_now < started + 120:
        raise ValueError("actual phase active horizon is exhausted")
    # The absolute unit monotonic origin includes interpreter/wrapper startup.
    # UTC is an observed same-boot mapping, never a replacement mission clock.
    unit_utc = utc_now - (monotonic_now - started)
    return {"schema": SCHEMA, "phase": phase, "boot_id": boot_id,
            "unit_name": UNITS[phase], "invocation_id": invocation,
            "cgroup_path": cg, "exec_main_pid": own_pid,
            "phase_unit_start_utc": dt.datetime.fromtimestamp(unit_utc, dt.timezone.utc).isoformat(),
            "phase_unit_start_monotonic": started,
            "observed_utc": dt.datetime.fromtimestamp(utc_now, dt.timezone.utc).isoformat(),
            "observed_monotonic": monotonic_now, "runtime_max_s": 180,
            "kill_mode": "control-group", "kill_signal": "SIGKILL",
            "memory_max": 1073741824, "cpu_max_percent": 200, "pids_max": 32,
            "affinity": affinity, "properties": properties, "readings": readings}

def capture(phase):
    """Reads an already-running approved unit; does not create or change it."""
    if phase not in UNITS:
        raise ValueError("fixed phase required")
    keys = ["RuntimeMaxUSec", "KillSignal", "KillMode", "MemoryMax",
            "CPUQuotaPerSecUSec", "TasksMax", "ControlGroup",
            "ExecMainStartTimestampMonotonic", "InvocationID", "ExecMainPID", "ActiveState"]
    cmd = ["/usr/bin/systemctl", "--user", "show", UNITS[phase], "--no-pager"]
    cmd += ["--property=" + key for key in keys]
    completed = subprocess.run(cmd, check=True, capture_output=True, text=True,
                               timeout=5, env={"PATH": "/usr/bin:/bin", "LC_ALL": "C",
                                              "XDG_RUNTIME_DIR": os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")})
    if len(completed.stdout) > 32768:
        raise ValueError("unit property response exceeds cap")
    properties = dict(line.split("=", 1) for line in completed.stdout.splitlines() if "=" in line)
    membership = Path("/proc/self/cgroup").read_text().strip()
    if not membership.startswith("0::/") or "\n" in membership:
        raise ValueError("unified cgroup required")
    relative = membership[3:]
    if ".." in Path(relative).parts:
        raise ValueError("invalid cgroup path")
    cg = Path("/sys/fs/cgroup" + relative)
    readings = {name: (cg / name).read_text().strip()
                for name in ("memory.max", "memory.swap.max", "cpu.max", "pids.max")}
    mono = time.monotonic()
    utc = time.time()
    return validate(phase, properties, membership, readings,
                    sorted(os.sched_getaffinity(0)), utc_now=utc,
                    monotonic_now=mono,
                    boot_id=Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
                    own_pid=os.getpid())
