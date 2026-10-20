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

# Cumulative source-read and scratch accounting for a fresh four128 trial.
# The 2026-10-11 authority (approved-trial-budget-arithmetic-v1) set source prior
# 821,491,388 B under a 1,115,551,932 B cap and a 2 GiB cumulative scratch maximum.
# The failed 2026-10-11 attempt then charged two conservative source reservations
# (its Budget ledger: 73,515,136 B) and carried its full 536,870,912 B scratch
# reservation. Those charges stay charged: a fresh eight-copy trial needs explicit
# extra authority, recorded in one signed amendment the harness reads instead of
# constants. Floors refuse any prior that omits the failed attempt.
# Revision 2 of the amendment (2026-10-19) adds attempt 2 of the fresh 2026-10-19
# trial: it failed at A-acquire (native worker bootstrap absent) after reserving
# one source admission (36,757,568 B) that stays charged as uncertain. Attempt 1
# charged no source bytes. A revision-1 amendment, which omits that charge, is
# refused.
# Revision 3 of the amendment (2026-10-20T04:06Z) adds attempt 4, which held at
# B-acquire (window B had 18 mask-invalid cells) after three source reservations
# (110,272,704 B, charged), and the two read-only window pre-scan opens of the
# cached BAG (73,515,136 B, charged in advance, never refunded). A revision-2
# amendment, which omits both, is refused.
# Revision 4 of the amendment (2026-10-20T06:15Z) adds attempt 5, which failed at
# D-acquire when its native job hit the stage deadline (the managed-output ledger
# read cost grew quadratically with mission size). Its seven source reservations
# (six settled A/B/C acquire+qualify, one uncertain D-acquire; 257,302,976 B) stay
# charged, no refunds. A revision-3 amendment, which omits them, is refused.
# Revision 5 of the amendment (2026-10-20T06:51Z) adds attempt 6, which COMPLETED
# at ed28dc69 (launched 2026-10-20T06:37Z): its eight settled source admissions
# (A-D acquire+qualify; 294,060,544 B) are charged, no refunds, and exhaust the
# revision-4 cap exactly. It also charges, in advance and never refunded, the two
# read-only SHA256 passes over the cached BAG made by the independent validation
# of attempt 6 (73,515,136 B; same treatment as the two pre-scan opens). Revision 5
# authorised one fresh eight-admission rerun. A revision-4 amendment, and the
# unused revision-5 draft that omits the validation reads, are refused.
# Revision 6 of the amendment (2026-10-20T07:24Z) adds T15 clean-state rerun 1,
# which COMPLETED at 292cb0aa (run tag 20261020r1, launched 2026-10-20T07:13Z): its
# eight settled source admissions (294,060,544 B) are charged, no refunds, and
# exhaust the revision-5 cap exactly. Revision 6 authorises rerun 2 only (one fresh
# eight-admission allowance). A revision-5 amendment, which omits rerun 1, is refused.
BUDGET_AMENDMENT = "coastal-four128-budget-amendment-v1"
AMENDMENT_STATUS = "SIGNED_DELEGATED_BUDGET_AUTHORITY"
AMENDMENT_SIGNERS = ("fable-2nd-look", "astra-orchestrator")
HARNESS_AUTHOR = "opus-coder"
PRE_FAILURE_SOURCE_PRIOR = 821491388
FAILED_TRIAL_SOURCE_CHARGED = 73515136
FAILED_TRIAL2_SOURCE_CHARGED = 36757568
FAILED_TRIAL4_SOURCE_CHARGED = 110272704
PRESCAN_SOURCE_CHARGED = 73515136
FAILED_TRIAL5_SOURCE_CHARGED = 257302976
# Attempt 6 COMPLETED at ed28dc69 (2026-10-20T06:37Z): eight settled admissions, charged.
TRIAL6_SOURCE_CHARGED = 294060544
# Independent validation of attempt 6 (t_b40d52c8): two read-only BAG hash passes, charged.
VALIDATION_HASH_SOURCE_CHARGED = 73515136
# T15 clean-state rerun 1 COMPLETED at 292cb0aa, run tag 20261020r1, 2026-10-20T07:13Z:
# eight settled admissions, charged.
RERUN1_SOURCE_CHARGED = 294060544
SOURCE_PRIOR_FLOOR = (PRE_FAILURE_SOURCE_PRIOR + FAILED_TRIAL_SOURCE_CHARGED + FAILED_TRIAL2_SOURCE_CHARGED
                      + FAILED_TRIAL4_SOURCE_CHARGED + PRESCAN_SOURCE_CHARGED + FAILED_TRIAL5_SOURCE_CHARGED
                      + TRIAL6_SOURCE_CHARGED + VALIDATION_HASH_SOURCE_CHARGED + RERUN1_SOURCE_CHARGED)
RECORDED_SOURCE_LIMIT = 1115551932
FRESH_SOURCE = 294060544
SCRATCH_PRIOR_FLOOR = 1616905649
RECORDED_SCRATCH_LIMIT = 2147483648
TRIAL_SCRATCH = 536870912


def _exact_int(value):
    return type(value) is int and value >= 0


def budget_limits(doc):
    """Validate a signed budget amendment and return the bound quantities.

    The extra allowance must equal the shortfall exactly (no margin), nothing is
    refunded, no download is authorised, and the harness author cannot sign."""
    if not isinstance(doc, dict) or doc.get("schema") != BUDGET_AMENDMENT:
        raise ValueError("signed four128 budget amendment required")
    signer = doc.get("signer")
    if (doc.get("status") != AMENDMENT_STATUS or not isinstance(signer, dict)
            or signer.get("profile") not in AMENDMENT_SIGNERS
            or signer.get("profile") == HARNESS_AUTHOR
            or not isinstance(signer.get("model"), str) or not signer["model"]
            or "opus" in signer["model"].lower()
            or doc.get("author_under_review") != HARNESS_AUTHOR):
        raise ValueError("budget amendment must be signed by delegated authority, not the harness author")
    source, scratch = doc.get("source"), doc.get("scratch")
    if not isinstance(source, dict) or not isinstance(scratch, dict):
        raise ValueError("source and scratch accounting required")
    keys = ("pre_failure_prior_bytes", "failed_trial_charged_bytes", "failed_trial_2_charged_bytes",
            "failed_trial_4_charged_bytes", "window_prescan_charged_bytes", "failed_trial_5_charged_bytes",
            "trial_6_charged_bytes", "validation_hash_reads_charged_bytes", "rerun_1_charged_bytes",
            "prior_effective_bytes", "previous_cumulative_limit_bytes", "additional_bytes",
            "cumulative_limit_bytes", "fresh_allowance_bytes")
    if any(not _exact_int(source.get(k)) for k in keys):
        raise ValueError("exact integer source accounting required")
    prior, cap = source["prior_effective_bytes"], source["cumulative_limit_bytes"]
    if (source["pre_failure_prior_bytes"] != PRE_FAILURE_SOURCE_PRIOR
            or source["failed_trial_charged_bytes"] != FAILED_TRIAL_SOURCE_CHARGED
            or source["failed_trial_2_charged_bytes"] != FAILED_TRIAL2_SOURCE_CHARGED
            or source["failed_trial_4_charged_bytes"] != FAILED_TRIAL4_SOURCE_CHARGED
            or source["window_prescan_charged_bytes"] != PRESCAN_SOURCE_CHARGED
            or source["failed_trial_5_charged_bytes"] != FAILED_TRIAL5_SOURCE_CHARGED
            or source["trial_6_charged_bytes"] != TRIAL6_SOURCE_CHARGED
            or source["validation_hash_reads_charged_bytes"] != VALIDATION_HASH_SOURCE_CHARGED
            or source["rerun_1_charged_bytes"] != RERUN1_SOURCE_CHARGED
            or prior != (source["pre_failure_prior_bytes"] + source["failed_trial_charged_bytes"]
                         + source["failed_trial_2_charged_bytes"] + source["failed_trial_4_charged_bytes"]
                         + source["window_prescan_charged_bytes"] + source["failed_trial_5_charged_bytes"]
                         + source["trial_6_charged_bytes"] + source["validation_hash_reads_charged_bytes"]
                         + source["rerun_1_charged_bytes"])
            or prior < SOURCE_PRIOR_FLOOR
            or source["previous_cumulative_limit_bytes"] != RECORDED_SOURCE_LIMIT
            or source["fresh_allowance_bytes"] != FRESH_SOURCE
            or source["additional_bytes"] != max(0, prior + FRESH_SOURCE - RECORDED_SOURCE_LIMIT)
            or cap != RECORDED_SOURCE_LIMIT + source["additional_bytes"]
            or prior + FRESH_SOURCE > cap
            or source.get("refunds") is not False or source.get("downloads") != 0):
        raise ValueError("source amendment must carry the failed charges and add exactly the shortfall")
    keys = ("charged_prior_bytes", "previous_cumulative_maximum_bytes", "additional_bytes",
            "cumulative_maximum_bytes", "trial_reservation_bytes")
    if any(not _exact_int(scratch.get(k)) for k in keys):
        raise ValueError("exact integer scratch accounting required")
    sprior, scap = scratch["charged_prior_bytes"], scratch["cumulative_maximum_bytes"]
    if (sprior < SCRATCH_PRIOR_FLOOR
            or scratch["previous_cumulative_maximum_bytes"] != RECORDED_SCRATCH_LIMIT
            or scratch["trial_reservation_bytes"] != TRIAL_SCRATCH
            or scratch["additional_bytes"] != max(0, sprior + TRIAL_SCRATCH - RECORDED_SCRATCH_LIMIT)
            or scap != RECORDED_SCRATCH_LIMIT + scratch["additional_bytes"]
            or sprior + TRIAL_SCRATCH > scap
            or scratch.get("refunds") is not False):
        raise ValueError("scratch amendment must carry the failed reservation and add exactly the shortfall")
    return dict(source_prior_bytes=prior, source_limit_bytes=cap,
                scratch_prior_bytes=sprior, scratch_limit_bytes=scap)


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
