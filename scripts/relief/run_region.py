#!/usr/bin/env python3
"""Guarded per-region runner for the relief pipeline (DATA-LIVE-6; E2E-PIPELINE §1-§3).

    run_region.py <region> --out <OUT> --through <stage> [--norm <NORM>] [--scope public]
                  [--region-config FILE] [--coarse TIF --water GEOJSON --coarse-source ID [--coarse-date D]]
                  [--dry-run]

Runs ``region.py <stage> --region <region> --out <OUT>`` for every stage of the chain up to
and including ``--through``, in this order::

    normalize select mosaic tiles contours zone digests package qa envelope

``mosaic``, ``tiles`` and ``zone`` also get ``--scope <scope>`` (default ``public``) and, when
given, ``--region-config FILE`` (the DL-5 seam); ``zone`` also gets ``--coarse``, ``--water``,
``--coarse-source`` and ``--coarse-date``, and a chain that reaches ``zone`` without the first
three is a usage error before anything runs. Those input paths are checked against the
private-vault guard like OUT.

Each stage is a subprocess under ``nice -n 19 ionice -c3``. The run stops at the first stage
that exits non-zero, names that stage and its code, and exits with the same code (a code
outside 1-255 becomes 1). Exit code 2 from ``region.py`` (unknown stage: its module is not on
main yet) is reported as "not available" and stops the run there.

Before every stage (and so before the first) the run is refused, exit 3, while any of these hold:

* a stop file exists in ``~/agent-work/modes``: ``LOCAL-STOP`` or ``UNITFEED-STOP``;
* load5 is 24 or more;
* free space is under 250 GB on ``/`` or under 400 GB on ``/mnt/agentorange-backup``
  (a missing backup mount counts as under the floor);
* ``--out`` or ``--norm`` (default ``$SC_RELIEF_NORM``) is, or resolves to, a path under
  ``/mnt/privatevault``.

Once, before the first stage, the run is refused with exit 5 when this region already has a
run (an exclusive lock on ``OUT/<region>/.run_region.lock``, released by the kernel if the
process dies) or when two other ``run_region.py`` processes are already running on the box.

``--dry-run`` prints the chain and the state of every guard and runs nothing: it creates no
file or directory. Nothing here downloads, uploads, pushes or publishes, and this script writes
only the lock file inside ``OUT/<region>/``. The stages themselves keep their own receipts.

Exit codes: 0 chain complete (or dry run), 2 usage error or stage not available, 3 a guard
refused, 5 region already running or two runs already on the box, anything else is the code of
the stage that failed.
"""
import argparse
from dataclasses import dataclass, field
import errno
import fcntl
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time

SCOPED_STAGES = ('mosaic', 'tiles', 'zone')  # DL-5 seam: these take --scope and --region-config
STAGES = ('normalize', 'select', 'mosaic', 'tiles', 'contours', 'zone', 'digests', 'package', 'qa', 'envelope')
REGION_ID = re.compile(r'[a-z0-9][a-z0-9-]{0,63}')  # the same rule as skippercast.relief.receipts
LOCK_NAME = '.run_region.lock'
GB = 10 ** 9

EXIT_USAGE = 2  # also: region.py reports an unknown stage with 2
EXIT_REFUSED = 3
EXIT_RUNNING = 5


def _default_load5():
    return os.getloadavg()[1]


def _default_free_bytes(path):
    return shutil.disk_usage(path).free


@dataclass
class Config:
    """Every host-dependent value, so a test can point it at a temporary directory."""
    region_py: Path = Path(__file__).resolve().with_name('region.py')
    stop_files: tuple = (Path.home() / 'agent-work' / 'modes' / 'LOCAL-STOP',
                         Path.home() / 'agent-work' / 'modes' / 'UNITFEED-STOP')
    load_max: float = 24.0
    root_path: str = '/'
    root_floor: int = 250 * GB
    backup_path: str = '/mnt/agentorange-backup'
    backup_floor: int = 400 * GB
    forbidden_root: str = '/mnt/privatevault'
    max_runs: int = 2  # run_region.py processes on the box, this one included
    proc_root: str = '/proc'
    prefix: tuple = ('nice', '-n', '19', 'ionice', '-c3')
    python: str = sys.executable
    load5: object = field(default=_default_load5)
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
    """Per-stage extra arguments for the DL-5 consumer seam: ``--scope`` (default public) and
    ``--region-config`` for mosaic, tiles and zone; zone also takes its three local inputs."""
    extra = {}
    for stage in SCOPED_STAGES:
        extra[stage] = ['--scope', args.scope]
        if args.region_config:
            extra[stage] += ['--region-config', args.region_config]
    if args.coarse:
        extra['zone'] += ['--coarse', args.coarse, '--water', args.water, '--coarse-source', args.coarse_source]
        if args.coarse_date:
            extra['zone'] += ['--coarse-date', args.coarse_date]
    return extra


def check_guards(cfg, out, norm, inputs=()):
    """Every start/continue guard as ``[(name, ok, detail)]``. Never raises on a host quirk:
    a value that cannot be read is a refusal."""
    checks = []
    present = [str(p) for p in cfg.stop_files if Path(p).exists()]
    checks.append(('stop-file', not present, ', '.join(present) + ' present' if present else 'none present'))
    try:
        load = float(cfg.load5())
        checks.append(('load5', load < cfg.load_max, f'load5 {load:.1f} (refuse at >= {cfg.load_max:g})'))
    except (OSError, ValueError) as exc:
        checks.append(('load5', False, f'cannot read load5: {exc}'))
    for name, path, floor in (('disk-root', cfg.root_path, cfg.root_floor),
                              ('disk-backup', cfg.backup_path, cfg.backup_floor)):
        try:
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


def other_runs(cfg):
    """Pids of the other ``run_region.py`` processes (python or the script itself as argv[0]).
    A wrapper such as ``timeout`` or ``nice`` is its own pid and is not counted twice."""
    found = []
    try:
        names = os.listdir(cfg.proc_root)
    except OSError:
        return found
    for name in names:
        if not name.isdigit() or int(name) == cfg.pid:
            continue
        try:
            raw = (Path(cfg.proc_root) / name / 'cmdline').read_bytes()
        except OSError:
            continue
        argv = [a.decode('utf-8', 'replace') for a in raw.split(b'\0') if a]
        if not argv:
            continue
        head = os.path.basename(argv[0])
        script = os.path.basename(argv[1]) if len(argv) > 1 else ''
        if head == 'run_region.py' or (head.startswith('python') and script == 'run_region.py'):
            found.append(int(name))
    return sorted(found)


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


def dry_run(cfg, region, out, norm, through, extra, inputs):
    say(f'run_region dry run: region {region}, through {through}, out {out}')
    say('chain (in order, each as a subprocess under ' + ' '.join(cfg.prefix) + '):')
    for index, stage in enumerate(chain_through(through), 1):
        say(f'  {index:>2}. {" ".join(stage_command(cfg, stage, region, out, extra))}')
    say('not run: ' + ', '.join(STAGES[STAGES.index(through) + 1:]) if through != STAGES[-1] else 'not run: (none)')
    say('guards (re-checked before every stage):')
    refused = False
    for name, ok, detail in check_guards(cfg, out, norm, inputs):
        say(f'  {"ok     " if ok else "REFUSE "}{name}: {detail}')
        refused = refused or not ok
    held = lock_is_held(out, region)
    say(f'  {"REFUSE " if held else "ok     "}region-lock: {lock_path(out, region)} '
        f'{"is held by another run" if held else "is free"}')
    others = other_runs(cfg)
    capped = len(others) + 1 > cfg.max_runs
    say(f'  {"REFUSE " if capped else "ok     "}run-cap: {len(others)} other run_region.py process(es), '
        f'at most {cfg.max_runs} on the box including this one')
    say('dry run: ' + ('a real run would be refused now' if refused or held or capped else 'a real run would start')
        + '; nothing was run and nothing was written')
    return 0


def refusal(cfg, out, norm, inputs):
    return [f'{name}: {detail}' for name, ok, detail in check_guards(cfg, out, norm, inputs) if not ok]


def run_chain(cfg, region, out, norm, through, extra, inputs):
    others = other_runs(cfg)
    if len(others) + 1 > cfg.max_runs:
        say(f'run_region: refused: {len(others)} other run_region.py process(es) already running '
            f'(pids {", ".join(map(str, others))}); at most {cfg.max_runs} at once')
        return EXIT_RUNNING
    problems = refusal(cfg, out, norm, inputs)  # before the lock, so a refused run leaves no file behind
    if problems:
        say('run_region: refused before ' + STAGES[0] + ': ' + '; '.join(problems))
        return EXIT_REFUSED
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
            command = stage_command(cfg, stage, region, out, extra)
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
    parser.add_argument('--through', required=True, help='last stage to run: ' + ', '.join(STAGES))
    parser.add_argument('--norm', default=os.environ.get('SC_RELIEF_NORM') or None,
                        help='normalised-cache root NORM, checked against the private-vault guard only (default $SC_RELIEF_NORM)')
    parser.add_argument('--scope', default='public', choices=('public', 'private'),
                        help='scope of the scoped stages mosaic, tiles and zone (default public)')
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
    if not REGION_ID.fullmatch(args.region):
        parser.error(f'bad region id {args.region!r}: lower-case letters, digits and hyphens')
    if args.through not in STAGES:
        parser.error(f'unknown stage {args.through!r}; stages: {", ".join(STAGES)}')
    out = Path(os.path.abspath(os.path.expanduser(args.out)))
    if not out.is_dir():
        parser.error(f'--out {out} is not an existing directory')
    norm = Path(os.path.abspath(os.path.expanduser(args.norm))) if args.norm else None
    if 'zone' in chain_through(args.through):
        missing = [f'--{n}' for n in ('coarse', 'water', 'coarse-source') if not getattr(args, n.replace('-', '_'))]
        if missing:
            parser.error(f'the chain reaches zone, which needs {", ".join(missing)}')
    extra = stage_extras(args)
    inputs = [Path(os.path.abspath(os.path.expanduser(p))) for p in (args.region_config, args.coarse, args.water) if p]
    if args.dry_run:
        return dry_run(cfg, args.region, out, norm, args.through, extra, inputs)
    try:
        return run_chain(cfg, args.region, out, norm, args.through, extra, inputs)
    except KeyboardInterrupt:
        say('run_region: interrupted')
        return 130


if __name__ == '__main__':
    sys.exit(main())
