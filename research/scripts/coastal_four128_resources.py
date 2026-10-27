"""Private trial envelope: command construction and read-only verification, never service launch."""
import datetime as dt
import hashlib
import json
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
# Revision 7 of the amendment (signed 2026-10-20T17:29Z, astra-orchestrator) adds
# T15 rerun 2, which COMPLETED (run tag 20261020r2): its eight settled admissions
# (294,060,544 B) are charged and exhaust the revision-6 cap exactly. It also
# charges, in advance and never refunded, ONE cached-BAG SC-5 mask-geometry
# pre-scan open (36,757,568 B): that open is a separate advance charge inside the
# prior, never a ninth runtime admission. Revision 7 authorises one fresh
# eight-admission allowance for the partial-support run (tag 20261020p1). A
# revision-6 amendment, which omits rerun 2 and the pre-scan, is refused.
BUDGET_AMENDMENT = "coastal-four128-budget-amendment-v1"
AMENDMENT_STATUS = "SIGNED_DELEGATED_BUDGET_AUTHORITY"
AMENDMENT_SIGNERS = ("fable-2nd-look", "astra-orchestrator")
HARNESS_AUTHOR = "opus-coder"
LEDGER_RELATIVE = 'research/catalog/coastal-four128-charge-ledger.json'


def load_charge_ledger(path):
    """Read reviewed data, never an environment-selected accounting floor.

    The original signed amendment is pinned by raw SHA256. This projection is
    anchored by repository review, not by a newly invented signing key.
    """
    path = Path(path)
    if path.is_symlink() or any(p.is_symlink() for p in path.parents):
        raise ValueError('charge ledger symlink')
    ledger = json.loads(path.read_text())
    if ledger.get('schema') != 'coastal-four128-charge-ledger-v1':
        raise ValueError('charge ledger schema')
    head = ledger['head']
    if (head['status'] != AMENDMENT_STATUS
            or head['signer']['profile'] not in AMENDMENT_SIGNERS
            or not head['signer'].get('model') or 'opus' in head['signer']['model'].lower()
            or not re.fullmatch('[0-9a-f]{64}', head['sha256'])
            or not re.fullmatch('[0-9a-f]{64}', head['supersedes_sha256'])
            or type(head['revision']) is not int or head['revision'] < 1):
        raise ValueError('signed charge ledger head required')
    source, scratch = ledger['source'], ledger['scratch']
    charges = {k: v for k, v in source.items()
               if k == 'pre_failure_prior_bytes' or k.endswith('_charged_bytes')}
    if not charges or 'pre_failure_prior_bytes' not in charges:
        raise ValueError('charge ledger has no baseline')
    for block in (source, scratch):
        if any(type(v) is not int or v < 0 for k, v in block.items() if k.endswith('_bytes')):
            raise ValueError('exact integer charge ledger accounting required')
        if block.get('refunds') is not False:
            raise ValueError('charge ledger refunds forbidden')
    prior = sum(charges.values())
    if (type(source.get('downloads')) is not int or source['downloads'] != 0
            or prior != source['prior_effective_bytes']
            or source['additional_bytes'] != max(0, prior + source['fresh_allowance_bytes'] - source['previous_cumulative_limit_bytes'])
            or source['cumulative_limit_bytes'] != source['previous_cumulative_limit_bytes'] + source['additional_bytes']
            or scratch['additional_bytes'] != max(0, scratch['charged_prior_bytes'] + scratch['trial_reservation_bytes'] - scratch['previous_cumulative_maximum_bytes'])
            or scratch['cumulative_maximum_bytes'] != scratch['previous_cumulative_maximum_bytes'] + scratch['additional_bytes']):
        raise ValueError('charge ledger does not balance')
    return ledger


CHARGE_LEDGER = load_charge_ledger(Path(__file__).resolve().parents[2] / LEDGER_RELATIVE)
SOURCE_CHARGES = {k: v for k, v in CHARGE_LEDGER['source'].items()
                  if k == 'pre_failure_prior_bytes' or k.endswith('_charged_bytes')}
# Compatibility names for historical consumers; validation iterates the ledger,
# so future signed charges require a reviewed data update, not Python edits.
PRE_FAILURE_SOURCE_PRIOR = SOURCE_CHARGES['pre_failure_prior_bytes']
FAILED_TRIAL_SOURCE_CHARGED = SOURCE_CHARGES['failed_trial_charged_bytes']
FAILED_TRIAL2_SOURCE_CHARGED = SOURCE_CHARGES['failed_trial_2_charged_bytes']
FAILED_TRIAL4_SOURCE_CHARGED = SOURCE_CHARGES['failed_trial_4_charged_bytes']
PRESCAN_SOURCE_CHARGED = SOURCE_CHARGES['window_prescan_charged_bytes']
FAILED_TRIAL5_SOURCE_CHARGED = SOURCE_CHARGES['failed_trial_5_charged_bytes']
TRIAL6_SOURCE_CHARGED = SOURCE_CHARGES['trial_6_charged_bytes']
VALIDATION_HASH_SOURCE_CHARGED = SOURCE_CHARGES['validation_hash_reads_charged_bytes']
RERUN1_SOURCE_CHARGED = SOURCE_CHARGES['rerun_1_charged_bytes']
RERUN2_SOURCE_CHARGED = SOURCE_CHARGES['rerun_2_charged_bytes']
SC5_PRESCAN_SOURCE_CHARGED = SOURCE_CHARGES['sc5_geometry_prescan_charged_bytes']
SOURCE_PRIOR_FLOOR = sum(SOURCE_CHARGES.values())
RECORDED_SOURCE_LIMIT = CHARGE_LEDGER['source']['previous_cumulative_limit_bytes']
FRESH_SOURCE = CHARGE_LEDGER['source']['fresh_allowance_bytes']
SCRATCH_PRIOR_FLOOR = CHARGE_LEDGER['scratch']['charged_prior_bytes']
RECORDED_SCRATCH_LIMIT = CHARGE_LEDGER['scratch']['previous_cumulative_maximum_bytes']
TRIAL_SCRATCH = CHARGE_LEDGER['scratch']['trial_reservation_bytes']


def budget_limits_bytes(raw):
    """Live callers must bind actual signed bytes, not just self-claimed roles."""
    if hashlib.sha256(raw).hexdigest() != CHARGE_LEDGER['head']['sha256']:
        raise ValueError('signed amendment differs from reviewed charge ledger head')
    doc = json.loads(raw)
    if (doc.get('amendment_revision') != CHARGE_LEDGER['head']['revision']
            or doc.get('signer') != CHARGE_LEDGER['head']['signer']
            or doc.get('signed_at') != CHARGE_LEDGER['head']['signed_at']
            or doc.get('supersedes', {}).get('sha256') != CHARGE_LEDGER['head']['supersedes_sha256']):
        raise ValueError('signed amendment differs from charge ledger attestation')
    return budget_limits(doc)


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
    keys = (*SOURCE_CHARGES,
            "prior_effective_bytes", "previous_cumulative_limit_bytes", "additional_bytes",
            "cumulative_limit_bytes", "fresh_allowance_bytes")
    if any(not _exact_int(source.get(k)) for k in keys):
        raise ValueError("exact integer source accounting required")
    prior, cap = source["prior_effective_bytes"], source["cumulative_limit_bytes"]
    if (any(source[k] != value for k, value in SOURCE_CHARGES.items())
            or {k for k in source if k.endswith('_charged_bytes')} != {k for k in SOURCE_CHARGES if k.endswith('_charged_bytes')}
            or prior != sum(source[k] for k in SOURCE_CHARGES)
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
