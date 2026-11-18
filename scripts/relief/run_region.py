#!/usr/bin/env python3
"""Guarded per-region runner for the relief pipeline (DATA-LIVE-6; E2E-PIPELINE §1-§3).

    run_region.py <region> --out <OUT> --through <stage> --source SRC [--norm <NORM>] [--family F]
                  [--scope public] [--region-config FILE]
                  [--coarse TIF --water GEOJSON --coarse-source ID [--coarse-date D]]
                  [--manifest JSON --upstream STAGE[:SCOPE] ...] [--generation SHA256] [--dry-run]
    run_region.py <region> --out <OUT> --dry-run  # preview the full chain without stage inputs

Runs ``region.py <stage> --region <region> --out <OUT>`` for every stage of the chain up to
and including ``--through``, in this order::

    normalize select mosaic tiles contours zone digests package qa envelope

Each stage also gets the inputs its own command line requires, as the stage modules declare
them: ``normalize`` gets ``--source`` (always required) and, when given, ``--family`` and
``--cache <NORM>``; ``mosaic``, ``tiles`` and ``zone`` get ``--scope <scope>`` (default
``public``) and, when given, ``--region-config FILE`` (the DL-5 seam); ``zone`` also gets
``--coarse``, ``--water``, ``--coarse-source`` and ``--coarse-date``; ``package`` gets
``--manifest`` and every ``--upstream``; ``envelope`` gets ``--generation`` (the option, else the
generation of the package receipt left by the package stage of this chain). A chain that reaches
a stage without its required inputs is a usage error before anything runs. Those input paths
are checked against the private-vault guard like OUT.

Each stage is a subprocess under ``nice -n 19 ionice -c3``. The run stops at the first stage
that exits non-zero, names that stage and its code, and exits with the same code (a code
outside 1-255 becomes 1). Exit code 2 from ``region.py`` (unknown stage: its module is not on
main yet) is reported as "not available" and stops the run there.

Before every stage (and so before the first) the run is refused, exit 3, while any of these hold:

* a stop file exists in ``~/agent-work/modes``: ``LOCAL-STOP`` or ``UNITFEED-STOP``, or
  its absence cannot be established;
* CPU pressure (``some avg60`` in ``/proc/pressure/cpu``) is 25% or more, or unavailable;
* free space is under 250 GB on ``/`` or under 400 GB on ``/mnt/agentorange-backup``
  (a backup path that is not a mounted filesystem counts as under the floor, whatever the
  free space of the directory's parent filesystem is);
* ``--out`` or ``--norm`` (default ``$SC_RELIEF_NORM``) is, or resolves to, a path under
  ``/mnt/privatevault``.

Before the first stage, the run is refused with exit 5 when this region already has a run
(an exclusive lock on ``OUT/<region>/.run_region.lock``, released by the kernel if the
process dies) or when the box already has two runs. The box-wide cap is enforced atomically:
a run must hold one of two advisory slot locks (``/tmp/run_region-slots-<uid>/slot-N``, also
released by the kernel), so two simultaneous starts cannot both take the last slot. The slot is
held throughout the chain, and the supplemental ``/proc`` scan for other ``run_region.py``
processes (``python3 -u run_region.py`` included) is repeated before every stage.
When the cap state cannot be established (``/proc`` unreadable, slot directory not safely
ours) the run is refused, exit 3.

``--dry-run`` prints the chain and the state of every guard and runs nothing: it creates no
file or directory. Nothing here downloads, uploads, pushes or publishes, and this script writes
only the lock file inside ``OUT/<region>/`` and the two slot files. The stages themselves keep
their own receipts.

Exit codes: 0 chain complete (or dry run), 2 usage error or stage not available, 3 a guard
refused, 5 region already running or two runs already on the box (3 when that cannot be established), anything else is the code of
the stage that failed.
"""
import argparse
from dataclasses import dataclass, field
import errno
import fcntl
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import time

SCOPED_STAGES = ('mosaic', 'tiles', 'zone')  # DL-5 seam: these take --scope and --region-config
STAGES = ('normalize', 'select', 'mosaic', 'tiles', 'contours', 'zone', 'digests', 'package', 'qa', 'envelope')
# Inputs the stage modules require on their own command line (a chain that reaches the stage without
# them is a usage error before anything runs). envelope's --generation is not here: it is read from
# the package receipt when not given.
STAGE_INPUTS = {'normalize': ('source',), 'zone': ('coarse', 'water', 'coarse-source'), 'package': ('manifest', 'upstream')}
REGION_ID = re.compile(r'[a-z0-9][a-z0-9-]{0,63}')  # the same rule as skippercast.relief.receipts
HEX64 = re.compile(r'[0-9a-f]{64}')
LOCK_NAME = '.run_region.lock'
GB = 10 ** 9
STOP_FILE_NAMES = ('LOCAL-STOP', 'UNITFEED-STOP')

EXIT_USAGE = 2  # also: region.py reports an unknown stage with 2
EXIT_REFUSED = 3
EXIT_RUNNING = 5


def cpu_some_avg60(proc_root):
    """Read the kernel's 60-second CPU pressure percentage, not the load average."""
    for line in (Path(proc_root) / 'pressure' / 'cpu').read_text(encoding='ascii').splitlines():
        row = line.split()
        if row and row[0] == 'some':
            values = [sample.removeprefix('avg60=') for sample in row[1:] if sample.startswith('avg60=')]
            if len(values) == 1:
                value = float(values[0])
                if 0 <= value <= 100:
                    return value
            break
    raise ValueError('missing or invalid some avg60')


def _default_free_bytes(path):
    return shutil.disk_usage(path).free


@dataclass
class Config:
    """Every host-dependent value, so a test can point it at a temporary directory."""
    region_py: Path = Path(__file__).resolve().with_name('region.py')
    stop_files: tuple = tuple(Path.home() / 'agent-work' / 'modes' / name for name in STOP_FILE_NAMES)
    cpu_pressure_max: float = 25.0
    root_path: str = '/'
    root_floor: int = 250 * GB
    backup_path: str = '/mnt/agentorange-backup'
    backup_floor: int = 400 * GB
    forbidden_root: str = '/mnt/privatevault'
    max_runs: int = 2  # run_region.py processes on the box, this one included
    slot_dir: Path = Path('/tmp') / f'run_region-slots-{os.getuid()}'  # box-wide: never TMPDIR
    proc_root: str = '/proc'
    is_mount: object = field(default=os.path.ismount)
    prefix: tuple = ('nice', '-n', '19', 'ionice', '-c3')
    python: str = sys.executable
    free_bytes: object = field(default=_default_free_bytes)
    pid: int = field(default_factory=os.getpid)


def real(path):
    return Path(os.path.realpath(os.path.abspath(os.path.expanduser(str(path)))))


def under(path, root):
    """Whether ``path`` is ``root`` or inside it, before and after resolving symlinks."""
    root = Path(os.path.abspath(root))
    real_root = Path(os.path.realpath(root))
    plain = Path(os.path.abspath(os.path.expanduser(str(path))))
    for candidate in (plain, real(path)):
        for base in (root, real_root):
            if candidate == base or base in candidate.parents:
                return True
    return False


def chain_through(through):
    return STAGES[:STAGES.index(through) + 1]


def stage_command(cfg, stage, region, out, extra=None):
    return [*cfg.prefix, cfg.python, str(cfg.region_py), stage, '--region', region, '--out', str(out),
            *(extra or {}).get(stage, ())]


def stage_extras(args):
    """Per-stage extra arguments: the inputs the stage modules themselves require (normalize
    ``--source``, zone ``--coarse``/``--water``/``--coarse-source``, package ``--manifest`` and
    ``--upstream``, envelope ``--generation``), plus the DL-5 seam, ``--scope`` (default public)
    and ``--region-config`` for mosaic, tiles and zone."""
    extra = {'normalize': [] if args.source is None else ['--source', args.source]}
    if args.family:
        extra['normalize'] += ['--family', args.family]
    if args.norm:  # normalize writes its cache here; the guard must watch the path it really uses
        extra['normalize'] += ['--cache', args.norm]
    for stage in SCOPED_STAGES:
        extra[stage] = ['--scope', args.scope]
        if args.region_config:
            extra[stage] += ['--region-config', args.region_config]
    for name in ('coarse', 'water', 'coarse-source', 'coarse-date'):
        if value := getattr(args, name.replace('-', '_')):
            extra['zone'] += [f'--{name}', value]
    if args.manifest:
        extra['package'] = ['--manifest', args.manifest]
    for ref in args.upstream or ():
        extra.setdefault('package', []).extend(['--upstream', ref])
    if args.generation:
        extra['envelope'] = ['--generation', args.generation]
    return extra


def missing_inputs(args, through):
    """``[(stage, [flag, ...])]`` for every stage of the chain whose required inputs were not given."""
    rows = []
    for stage in chain_through(through):
        names = [name for name in STAGE_INPUTS.get(stage, ()) if not getattr(args, name.replace('-', '_'))]
        if names:
            rows.append((stage, [f'--{name}' for name in names]))
    return rows


def package_generation(out, region):
    """The current package receipt's generation (envelope's ``--generation``), or None."""
    try:
        doc = json.loads((Path(out) / region / 'stages' / 'package.json').read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None
    value = doc.get('generation') if isinstance(doc, dict) else None
    return value if isinstance(value, str) and HEX64.fullmatch(value) else None


def check_guards(cfg, out, norm, inputs=()):
    """Every start/continue guard as ``[(name, ok, detail)]``. Never raises on a host quirk:
    a value that cannot be read is a refusal."""
    checks = []
    stops = []
    for path in cfg.stop_files:
        try:
            Path(path).lstat()  # only a missing entry is absent; even a dangling symlink is a stop
        except FileNotFoundError:
            continue
        except OSError as exc:
            stops.append(f'cannot check {path}: {exc}')
        else:
            stops.append(f'{path} present')
    checks.append(('stop-file', not stops, '; '.join(stops) or 'none present'))
    try:
        pressure = cpu_some_avg60(cfg.proc_root)
        checks.append(('cpu-pressure', pressure < cfg.cpu_pressure_max,
                       f'some avg60 {pressure:g}% (refuse at >= {cfg.cpu_pressure_max:g}%)'))
    except (OSError, ValueError) as exc:
        checks.append(('cpu-pressure', False, f'cannot read some avg60: {exc}'))
    for name, path, floor, must_mount in (('disk-root', cfg.root_path, cfg.root_floor, False),
                                          ('disk-backup', cfg.backup_path, cfg.backup_floor, True)):
        try:
            if must_mount and not cfg.is_mount(path):
                # an empty mountpoint directory reports its parent filesystem's free space
                checks.append((name, False, f'{path} is not a mounted filesystem'))
                continue
            free = int(cfg.free_bytes(path))
            checks.append((name, free >= floor,
                           f'{free / GB:.0f} GB free on {path} (floor {floor // GB} GB)'))
        except (OSError, ValueError) as exc:
            checks.append((name, False, f'cannot read free space on {path}: {exc}'))
    for name, path in (('out-root', out), ('norm-root', norm)):
        if path is None:
            checks.append((name, True, 'not given'))
        elif under(path, cfg.forbidden_root):
            checks.append((name, False, f'{path} is under {cfg.forbidden_root}'))
        else:
            checks.append((name, True, f'{path} is not under {cfg.forbidden_root}'))
    for path in inputs:
        bad = under(path, cfg.forbidden_root)
        checks.append(('input-path', not bad, f'{path} is {"" if bad else "not "}under {cfg.forbidden_root}'))
    return checks


def runs_script(argv):
    """Whether ``argv`` is ``run_region.py`` itself or a python interpreter running it, with any
    interpreter options in between (``python3 -u run_region.py``, ``python3 -X dev run_region.py``)."""
    if not argv:
        return False
    head = os.path.basename(argv[0])
    if head == 'run_region.py':
        return True
    if not head.startswith('python'):
        return False
    rest = iter(argv[1:])
    for arg in rest:
        if arg == '--' or not arg.startswith('-') or arg == '-':
            if arg == '--':
                arg = next(rest, '')
            return os.path.basename(arg) == 'run_region.py'
        if arg == '-c':
            return False
        if arg == '-m':
            return os.path.basename(next(rest, '')).split('.')[-1] == 'run_region'
        if arg in ('-W', '-X'):
            next(rest, None)  # the option's separate value
    return False


def other_runs(cfg):
    """Pids of the other ``run_region.py`` processes. A wrapper such as ``timeout`` or ``nice`` is
    its own pid and is not counted twice. Raises OSError when the process table cannot be read:
    an unknown count must not be mistaken for zero."""
    found = []
    for name in os.listdir(cfg.proc_root):
        if not name.isdigit() or int(name) == cfg.pid:
            continue
        try:
            raw = (Path(cfg.proc_root) / name / 'cmdline').read_bytes()
        except (FileNotFoundError, ProcessLookupError):
            continue  # the process ended between the listing and the read
        argv = [a.decode('utf-8', 'replace') for a in raw.split(b'\0') if a]
        if runs_script(argv):
            found.append(int(name))
    return sorted(found)


def _slot_dir(cfg, create):
    """The slot directory, verified to be a real directory of this user that nobody else can write.
    Returns None when it does not exist and ``create`` is false. Raises OSError otherwise."""
    path = Path(cfg.slot_dir)
    if create:
        try:
            os.mkdir(path, 0o700)
        except FileExistsError:
            pass
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        if create:
            raise
        return None
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o022:
        raise OSError(errno.EPERM, f'slot directory {path} is not a private directory of this user')
    return path


def slots_held(cfg):
    """Dry-run probe: how many of the box-wide run slots are locked now. Creates nothing."""
    directory = _slot_dir(cfg, create=False)
    held = 0
    for index in range(cfg.max_runs) if directory else ():
        try:
            fd = os.open(directory / f'slot-{index}', os.O_RDONLY | os.O_NOFOLLOW)
        except FileNotFoundError:
            continue
        try:
            fcntl.flock(fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
        except OSError as exc:
            if exc.errno not in (errno.EAGAIN, errno.EACCES):
                raise
            held += 1
        finally:
            os.close(fd)
    return held


def acquire_slot(cfg):
    """Take one of ``cfg.max_runs`` box-wide advisory slot locks; returns the fd, or None when all
    are held. The kernel grants each lock to one open file description, so two simultaneous
    starts cannot both take the last slot, and a dead run frees its slot."""
    directory = _slot_dir(cfg, create=True)
    for index in range(cfg.max_runs):
        fd = os.open(directory / f'slot-{index}', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            os.close(fd)
            if exc.errno in (errno.EAGAIN, errno.EACCES):
                continue
            raise
        os.ftruncate(fd, 0)
        os.write(fd, f'pid {cfg.pid}\n'.encode())
        return fd
    return None


def lock_path(out, region):
    return Path(out) / region / LOCK_NAME


def lock_is_held(out, region):
    """Dry-run probe: whether another process holds the region lock. Creates nothing."""
    try:
        fd = os.open(lock_path(out, region), os.O_RDONLY)
    except OSError:
        return False
    try:
        fcntl.flock(fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
    except OSError as exc:
        return exc.errno in (errno.EAGAIN, errno.EACCES)
    finally:
        os.close(fd)
    return False


def acquire_lock(cfg, out, region):
    """Open and exclusively lock OUT/<region>/.run_region.lock; returns the fd or None if held."""
    region_dir = Path(out) / region
    region_dir.mkdir(exist_ok=True)
    if not under(region_dir, out) or real(region_dir).parent != real(out):
        raise RuntimeError(f'{region_dir} leaves {out}')
    fd = os.open(region_dir / LOCK_NAME, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as exc:
        os.close(fd)
        if exc.errno in (errno.EAGAIN, errno.EACCES):
            return None
        raise
    os.ftruncate(fd, 0)
    os.write(fd, f'pid {cfg.pid}\nstarted {time.strftime("%Y-%m-%dT%H:%M:%S%z")}\n'.encode())
    return fd


def say(text):
    print(text, flush=True)


def dry_run(cfg, region, out, norm, through, extra, inputs, missing):
    say(f'run_region dry run: region {region}, through {through}, out {out}')
    say('chain (in order, each as a subprocess under ' + ' '.join(cfg.prefix) + '):')
    shown = dict(extra)
    if 'envelope' not in shown:
        shown['envelope'] = ['--generation', '<generation of the current package receipt>']
    for index, stage in enumerate(chain_through(through), 1):
        say(f'  {index:>2}. {" ".join(stage_command(cfg, stage, region, out, shown))}')
    say('not run: ' + ', '.join(STAGES[STAGES.index(through) + 1:]) if through != STAGES[-1] else 'not run: (none)')
    say('guards (re-checked before every stage):')
    refused = bool(missing)
    for stage, flags in missing:
        say(f'  REFUSE {stage} inputs: a real run through {through} needs ' + ', '.join(flags))
    for name, ok, detail in check_guards(cfg, out, norm, inputs):
        say(f'  {"ok     " if ok else "REFUSE "}{name}: {detail}')
        refused = refused or not ok
    held = lock_is_held(out, region)
    say(f'  {"REFUSE " if held else "ok     "}region-lock: {lock_path(out, region)} '
        f'{"is held by another run" if held else "is free"}')
    try:
        others = other_runs(cfg)
        held_slots = slots_held(cfg)
        capped = len(others) + 1 > cfg.max_runs or held_slots >= cfg.max_runs
        cap_detail = (f'{len(others)} other run_region.py process(es), {held_slots} run slot(s) held, '
                      f'at most {cfg.max_runs} on the box including this one')
    except OSError as exc:
        capped = True
        cap_detail = f'cannot establish how many runs are on the box: {exc}'
    say(f'  {"REFUSE " if capped else "ok     "}run-cap: {cap_detail}')
    say('dry run: ' + ('a real run would be refused now' if refused or held or capped else 'a real run would start')
        + '; nothing was run and nothing was written')
    return 0


def refusal(cfg, out, norm, inputs):
    return [f'{name}: {detail}' for name, ok, detail in check_guards(cfg, out, norm, inputs) if not ok]


def run_cap_refusal(cfg):
    try:
        others = other_runs(cfg)
    except OSError as exc:  # fail closed: an unreadable process table is not "no other runs"
        return EXIT_REFUSED, f'cannot establish how many runs are on the box: {exc}'
    if len(others) + 1 > cfg.max_runs:
        return (EXIT_RUNNING, f'{len(others)} other run_region.py process(es) already running '
                f'(pids {", ".join(map(str, others))}); at most {cfg.max_runs} at once')
    return None


def run_chain(cfg, region, out, norm, through, extra, inputs):
    if cap := run_cap_refusal(cfg):
        code, detail = cap
        say(f'run_region: refused: {detail}')
        return code
    problems = refusal(cfg, out, norm, inputs)  # before any lock, so a refused run leaves no file behind
    if problems:
        say('run_region: refused before ' + STAGES[0] + ': ' + '; '.join(problems))
        return EXIT_REFUSED
    try:
        slot = acquire_slot(cfg)  # the atomic box-wide cap; the /proc scan above is only a second check
    except OSError as exc:
        say(f'run_region: refused: cannot take a run slot: {exc}')
        return EXIT_REFUSED
    if slot is None:
        say(f'run_region: refused: {cfg.max_runs} runs already hold the box run slots; at most {cfg.max_runs} at once')
        return EXIT_RUNNING
    try:
        return run_locked(cfg, region, out, norm, through, extra, inputs)
    finally:
        os.close(slot)


def run_locked(cfg, region, out, norm, through, extra, inputs):
    try:
        fd = acquire_lock(cfg, out, region)
    except (OSError, RuntimeError) as exc:
        say(f'run_region: refused: cannot take the region lock: {exc}')
        return EXIT_REFUSED
    if fd is None:
        say(f'run_region: refused: region {region} already has a run (lock {lock_path(out, region)})')
        return EXIT_RUNNING
    try:
        for stage in chain_through(through):
            problems = refusal(cfg, out, norm, inputs)
            if problems:
                say(f'run_region: refused before {stage}: ' + '; '.join(problems))
                return EXIT_REFUSED
            if cap := run_cap_refusal(cfg):
                code, detail = cap
                say(f'run_region: refused before {stage}: {detail}')
                return code
            stage_args = extra
            if stage == 'envelope' and 'envelope' not in extra:
                generation = package_generation(out, region)
                if generation is None:
                    say('run_region: STOPPED before envelope: no --generation given and no valid generation in the '
                        f'package receipt {Path(out) / region / "stages" / "package.json"}')
                    return EXIT_USAGE
                stage_args = {**extra, 'envelope': ['--generation', generation]}
            command = stage_command(cfg, stage, region, out, stage_args)
            say(f'run_region: stage {stage}: ' + ' '.join(command))
            started = time.monotonic()
            try:
                code = subprocess.run(command, stdin=subprocess.DEVNULL).returncode
            except OSError as exc:
                say(f'run_region: STOPPED at {stage}: cannot start the command: {exc}')
                return 1
            took = time.monotonic() - started
            if code == 0:
                say(f'run_region: stage {stage}: exit 0 ({took:.1f}s)')
                continue
            if code == EXIT_USAGE:
                say(f'run_region: STOPPED at {stage}: not available (region.py exit 2: no such stage module '
                    f'on this checkout, or a usage error; see its message above)')
                return EXIT_USAGE
            say(f'run_region: STOPPED at {stage}: exit {code}')
            return code if 0 < code < 256 else 1
        say(f'run_region: {region} complete through {through}')
        return 0
    finally:
        os.close(fd)  # releases the lock


def parse(argv):
    parser = argparse.ArgumentParser(prog='run_region.py', description='Run one region through the relief stage chain, guarded.',
                                     epilog='stages: ' + ' '.join(STAGES))
    parser.add_argument('region', help='region id (a line of regions.tsv)')
    parser.add_argument('--out', default=os.environ.get('SC_RELIEF_OUT') or None, required=not os.environ.get('SC_RELIEF_OUT'),
                        help='pipeline output root OUT (default $SC_RELIEF_OUT; must exist)')
    parser.add_argument('--through', help='last stage to run (required except for a full dry-run preview): '
                        + ', '.join(STAGES))
    parser.add_argument('--norm', default=os.environ.get('SC_RELIEF_NORM') or None,
                        help='normalised-cache root NORM, checked against the private-vault guard only (default $SC_RELIEF_NORM)')
    parser.add_argument('--scope', default='public', choices=('public', 'private'),
                        help='scope of the scoped stages mosaic, tiles and zone (default public)')
    parser.add_argument('--source', help='normalize input: the source file or directory (always needed: normalize is the first stage)')
    parser.add_argument('--family', help='normalize option: inventory family key (default: normalize\'s own, dem)')
    parser.add_argument('--manifest', help='package input: public layer inventory and metadata JSON (needed when the chain reaches package)')
    parser.add_argument('--upstream', action='append',
                        help='package input: a contributing stage[:scope]; repeat as needed (needed when the chain reaches package)')
    parser.add_argument('--generation', help='envelope input: release generation (default: the current package receipt\'s)')
    parser.add_argument('--region-config', help='region config file for mosaic, tiles and zone (default: regions/<id>/region.json)')
    parser.add_argument('--coarse', help='zone input: EPSG:3310 coarse elevation TIFF (needed when the chain reaches zone)')
    parser.add_argument('--water', help='zone input: reviewed WGS84 ocean-water GeoJSON (needed when the chain reaches zone)')
    parser.add_argument('--coarse-source', help='zone input: provenance id of --coarse (needed when the chain reaches zone)')
    parser.add_argument('--coarse-date', help='zone input: optional date of --coarse')
    parser.add_argument('--dry-run', action='store_true', help='print the chain and the guard state; run nothing')
    return parser, parser.parse_args(argv)


def main(argv=None, cfg=None):
    cfg = cfg or Config()
    parser, args = parse(sys.argv[1:] if argv is None else list(argv))
    full_preview = args.dry_run and args.through is None
    if full_preview:
        args.through = STAGES[-1]
    elif args.through is None:
        parser.error('the following arguments are required: --through')
    if not REGION_ID.fullmatch(args.region):
        parser.error(f'bad region id {args.region!r}: lower-case letters, digits and hyphens')
    if args.through not in STAGES:
        parser.error(f'unknown stage {args.through!r}; stages: {", ".join(STAGES)}')
    out = Path(os.path.abspath(os.path.expanduser(args.out)))
    if not out.is_dir():
        parser.error(f'--out {out} is not an existing directory')
    norm = Path(os.path.abspath(os.path.expanduser(args.norm))) if args.norm else None
    missing = missing_inputs(args, args.through)
    if missing and not full_preview:
        parser.error('; '.join(f'the chain reaches {stage}, which needs {", ".join(flags)}' for stage, flags in missing))
    extra = stage_extras(args)
    inputs = [Path(os.path.abspath(os.path.expanduser(p)))
              for p in (args.source, args.region_config, args.coarse, args.water, args.manifest) if p]
    if args.dry_run:
        return dry_run(cfg, args.region, out, norm, args.through, extra, inputs, missing)
    try:
        return run_chain(cfg, args.region, out, norm, args.through, extra, inputs)
    except KeyboardInterrupt:
        say('run_region: interrupted')
        return 130


if __name__ == '__main__':
    sys.exit(main())
