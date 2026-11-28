#!/usr/bin/env python3
"""Guarded per-region runner for the relief pipeline (DATA-LIVE-6; E2E-PIPELINE §1-§3).

    run_region.py <region> --out <OUT> --through <stage> [--norm <NORM>]
                  [--scope public] [--region-config FILE] [--provenance FILE]
                  [--census FILE --census-sha256 HEX]
                  [--coarse TIF --water GEOJSON --coarse-source ID [--coarse-date D]]
                  [--basemap PMTILES] [--qa-support TIF] [--qa-fine-proof ZOOM TIF ...]
    run_region.py <region> --out <OUT> --through <stage> --inputs FILE
    run_region.py <region> [--out <OUT>] --dry-run  # preview the full chain without stage inputs

Runs ``region.py <stage> --region <region> --out <OUT>`` through the requested stage::

    select mosaic tiles zone survey_detail survey_gap digests inventory contours nearshore_vectors
    package shots qa envelope

The survey stages (public only) are opt-in. They derive the Chart's survey-confidence detail and its
no-survey gap companion from the zone output; inventory lists their pairs as release layers and
package takes them as upstream. ``--survey detail-and-gap`` runs both (Morro Bay); ``--survey
detail`` runs survey_detail only (a region whose detail has no unsurveyed area, e.g. Big Sur); the
default ``--survey none`` skips both and packages relief without survey layers, as before.

With --census, census-bind runs before select. Normalize separately, per source. Select reads
the resulting cache and the source-label file given by --provenance (without it, select falls
back to $SC_RELIEF_PROVENANCE, else PROVENANCE-LABELS.json in the working directory; an --inputs
record can SHA-256 pin it). Zone fills omitted coarse and water paths from done stage receipts;
when using stage coarse it defaults the source ID to the family in the receipted coarse.json.
Package reads the inventory and its public producer receipts, including the unscoped contours receipt
for style provenance. Contour files remain QA evidence, not release layers. A held
contours stage stops the chain before package. Shots needs a local basemap and performs receipt-bound MB-08
capture. The runner checks ``region.py status --json`` after package and shots: QA uses
the exact package release hash and the shots stage's own generation, while the envelope
uses the package generation. No caller-supplied manifest, evidence path for shots, or
release identity can replace these handoffs.
After a successful envelope stage, the runner prints that region's read-only R8 packet.
A NOT READY packet exits 1 without changing the written envelope.

--inputs loads a sc-run-inputs/1 JSON record for the positional region. Listed files are
SHA-256 checked as a group before any stage, even if the chain stops early. Paths use the
same working-directory and ~ rules as flags. Use flags only for values not set by the record
(null metadata does not set an option). Dry runs report the record digest and each file verdict.

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
* ``--out`` or the effective normalized cache (``--norm``, else ``$SC_RELIEF_NORM`` even when
  empty, i.e. the working directory, else the built-in default) is, or resolves to, a path under
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

Every run that takes the region lock writes a run log ``OUT/<region>/runs/<UTC stamp>-p<pid>.json``
(schema ``sc-run-log/1``): one row per step with its exit code, state and seconds, and the run's
outcome (``complete``, ``stopped``, ``refused``, ``interrupted``; ``running`` while it runs). It is
rewritten atomically after every step, so a killed run leaves the steps it finished. A step's
state comes from its exit code: 0 ``ok``, 1 ``failed``, 2 ``not available``, 3 ``blocked``,
4 ``held``, 5 ``busy`` (any other code ``failed``). The log is written only inside a real
``OUT/<region>/runs`` directory (never through a symlink), via an exclusively created temporary
file in that directory. The run ends by printing the log as a step / state / seconds table.

``--dry-run`` prints the chain and the state of every guard. With an output root it also
previews the region's receipt-based rebuild plan. It runs nothing and creates no file or
directory. Nothing here downloads, uploads, pushes or publishes, and this script writes
only the lock file and the run logs inside ``OUT/<region>/`` and the two slot files. The stages
themselves keep their own receipts. A run log that cannot be written is reported on stderr and does
not stop the chain.

Exit codes: 0 chain complete (or dry run), 2 usage error or stage not available, 3 a guard
or input check refused, 5 region already running or two runs already on the box (3 when
that cannot be established), anything else is the code of the stage that failed.
"""
import argparse
from dataclasses import dataclass, field
from datetime import datetime, timezone
import errno
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import time

DEFAULT_NORM = '/mnt/agentorange-backup/seafloor-relief-cache/_norm'  # select's --cache default
SURVEY_STAGES = ('survey_detail', 'survey_gap')
SCOPED_STAGES = ('mosaic', 'tiles', 'zone', *SURVEY_STAGES, 'nearshore_vectors')
STAGES = ('select', 'mosaic', 'tiles', 'zone', *SURVEY_STAGES, 'digests', 'inventory', 'contours',
          'nearshore_vectors', 'package', 'shots', 'qa', 'envelope')
# --survey choice -> the survey stages it skips; inventory and package take the rest.
SURVEY_SKIPS = {'detail-and-gap': (), 'detail': ('survey_gap',), 'none': SURVEY_STAGES}
SKIP = 'skip'  # stage_extras key: stages left out of this run's chain (never a stage name)
ZONE_STAGE_INPUTS = {'--coarse': 'coarse', '--water': 'water', '--coarse-source': 'coarse'}
REGION_ID = re.compile(r'[a-z0-9][a-z0-9-]{0,63}')  # the same rule as skippercast.relief.receipts
HEX64 = re.compile(r'[0-9a-f]{64}')
LOCK_NAME = '.run_region.lock'
RUNS_DIR = 'runs'
RUN_LOG_SCHEMA = 'sc-run-log/1'
EXIT_STATES = {1: 'failed', 2: 'not available', 3: 'blocked', 4: 'held', 5: 'busy'}
# file-valued options: the guard and the stage see the same spelling
PATH_OPTIONS = ('region_config', 'provenance', 'coarse', 'water', 'basemap', 'qa_support', 'census')
RECORD_FILES = frozenset(PATH_OPTIONS) - {'region_config'}
RECORD_METADATA = ('coarse_source', 'coarse_date', 'norm')
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
    basemap_roots: tuple = (Path.home(), Path('/mnt/agentorange-backup'))
    max_runs: int = 2  # run_region.py processes on the box, this one included
    slot_dir: Path = Path('/tmp') / f'run_region-slots-{os.getuid()}'  # box-wide: never TMPDIR
    proc_root: str = '/proc'
    is_mount: object = field(default=os.path.ismount)
    prefix: tuple = ('nice', '-n', '19', 'ionice', '-c3')
    python: str = sys.executable
    free_bytes: object = field(default=_default_free_bytes)
    pid: int = field(default_factory=os.getpid)
    r8_packet_py: Path = Path(__file__).resolve().with_name('r8_packet.py')
    clock: object = field(default=lambda: datetime.now(timezone.utc))


def effective_norm(option, environ=None):
    """The normalised-cache root select will really read, resolved once.

    Mirrors select's own ``--cache`` rule: the option
    if given, else ``$SC_RELIEF_NORM`` whenever it is *set* (an empty value is kept, and resolves
    to the working directory, exactly as select would have it), else ``DEFAULT_NORM``. The
    result is absolute; the guard checks this path and it is passed to select as ``--cache``.
    """
    environ = os.environ if environ is None else environ
    value = option if option is not None else environ.get('SC_RELIEF_NORM', DEFAULT_NORM)
    return Path(os.path.abspath(os.path.expanduser(value)))


def spelled(value):
    """The absolute filesystem spelling of an input path, ``~`` expanded and made absolute against the
    working directory WITHOUT collapsing ``..`` (a ``link/..`` must still be resolved by the OS, so it
    is the same path the guard resolves and the stage opens)."""
    return os.path.join(os.getcwd(), os.path.expanduser(str(value)))


def fine_zoom(parser, zoom):
    """The bare integer zoom (``'16'`` or ``'17'``) qa's ``--fine-proof`` parses with ``int()``; ``z16`` is accepted too."""
    match = re.fullmatch(r'[zZ]?(16|17)', zoom)
    if not match:
        parser.error(f'--qa-fine-proof ZOOM must be 16 or 17 (or z16/z17), not {zoom!r}')
    return match.group(1)


def real(path):
    return Path(os.path.realpath(spelled(path)))


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


def basemap_allowed(cfg, path):
    roots = [real(p) for p in cfg.basemap_roots]
    paths = (Path(os.path.abspath(path)), real(path))
    return all(any(p.is_relative_to(root) for root in roots) for p in paths)


def unique_object(pairs):
    obj = {}
    for key, value in pairs:
        if key in obj:
            raise ValueError(f'duplicate key {key!r}')
        obj[key] = value
    return obj


def load_inputs(args, parser):
    """Validate the closed record and CLI conflicts before inspecting any listed input."""
    try:
        path = Path(spelled(args.inputs))
        if not path.is_file():
            raise ValueError('not a regular file')
        raw = path.read_bytes()
        doc = json.loads(raw, object_pairs_hook=unique_object)
        if (not isinstance(doc, dict) or doc.keys() != {'schema', 'region', 'inputs', *RECORD_METADATA}
                or doc['schema'] != 'sc-run-inputs/1' or not isinstance(doc['inputs'], dict)):
            raise ValueError('expected a sc-run-inputs/1 object with schema, region, inputs, coarse_source, coarse_date and norm')
        if doc['region'] != args.region:
            raise ValueError(f'region {doc["region"]!r} does not match {args.region!r}')
        pins, options = {}, {}
        for name, entry in doc['inputs'].items():
            if name not in RECORD_FILES:
                raise ValueError(f'unknown input {name!r}')
            if not isinstance(entry, dict) or entry.keys() != {'path', 'sha256'} or not isinstance(entry['path'], str):
                raise ValueError(f'{name}: expected path and sha256')
            digest = entry['sha256']
            if not isinstance(digest, str) or not HEX64.fullmatch(digest.lower()):
                raise ValueError(f'{name}: sha256 must be 64 hexadecimal digits')
            pins[name] = digest.lower()
            options[name] = entry['path']
        if 'census' in pins:
            options['census_sha256'] = pins['census']
        for name in RECORD_METADATA:
            value = doc[name]
            if value is not None:
                if not isinstance(value, str):
                    raise ValueError(f'{name} must be a string or null')
                options[name] = value
        for name in options:
            if getattr(args, name) is not None:
                raise ValueError(f'also supplied --{name.replace("_", "-")} on the command line')
    except (OSError, ValueError, RecursionError) as exc:
        parser.error(f'--inputs {args.inputs}: {exc}')
        raise  # argparse.error exits
    for name, value in options.items():
        setattr(args, name, value)
    return hashlib.sha256(raw).hexdigest(), pins


def input_problem(cfg, name, path, digest):
    # NUL is valid JSON but cannot name a filesystem path; realpath itself raises on it.
    if '\x00' in path:
        return f'{path!r} is missing or not a regular file'
    # Hashing opens the file earlier than a stage would; honor the same read boundaries first.
    if under(path, cfg.forbidden_root):
        return f'{path} is under {cfg.forbidden_root}'
    if name == 'basemap' and not basemap_allowed(cfg, path):
        return f'{path} must be in an allowed read root'
    try:
        if not os.path.isfile(path):
            return f'{path} is missing or not a regular file'
        with open(path, 'rb') as handle:
            actual = hashlib.file_digest(handle, 'sha256').hexdigest()
    except OSError as exc:
        return f'cannot read {path}: {exc.strerror}'
    return None if actual == digest else f'{path} expected sha256 {digest}, got {actual}'


def chain_through(through, skip=()):
    return tuple(stage for stage in STAGES[:STAGES.index(through) + 1] if stage not in skip)


def stage_command(cfg, stage, region, out, extra=None):
    return [*cfg.prefix, cfg.python, str(cfg.region_py), stage, '--region', region, '--out', str(out),
            *(extra or {}).get(stage, ())]


def steps_through(through, extra):
    if 'census-bind' in extra:
        yield 'census-bind', None
    for stage in chain_through(through, extra.get(SKIP, ())):
        yield stage, None
        if stage in ('package', 'shots'):
            yield 'status', stage


def stage_extras(args, out):
    """Static inputs and preview values; status binds the latter during a real run."""
    root = out / args.region
    mosaic = root / 'mosaic/public'
    extra = {
        'select': ['--cache', str(args.norm)],
        'package': ['--manifest', str(root / 'inventory/manifest.json'),
                    '--upstream', 'tiles:public', '--upstream', 'digests',
                    '--upstream', 'zone:public', '--upstream', 'inventory', '--upstream', 'contours'],
        'shots': ['--basemap', args.basemap or '<basemap>'],
        'status': ['--json'],
        'qa': ['--generation', '<generation>', '--release-sha256', '<release-sha256>',
               '--elevation', str(mosaic / 'elevation.tif'), '--contributor', str(mosaic / 'contributor.tif'),
               '--upstream', 'mosaic:public', '--upstream', 'nearshore_vectors:public',
               '--shots', str(root / 'shots/<shots-generation>/shots.json')],
        'envelope': ['--generation', '<generation>'],
    }
    if args.census:
        extra['census-bind'] = ['--from', args.census, '--sha256', args.census_sha256]
    for stage in SCOPED_STAGES:
        extra[stage] = ['--scope', args.scope]
    if args.region_config:
        for stage in ('select', *SCOPED_STAGES):
            if stage not in SURVEY_STAGES:  # they read only receipted zone/select outputs
                extra[stage] += ['--region-config', args.region_config]
    extra[SKIP] = SURVEY_SKIPS[args.survey]
    surveyed = [stage for stage in SURVEY_STAGES if stage not in extra[SKIP]]
    if surveyed:
        extra['inventory'] = ['--survey', args.survey]
    for stage in surveyed:
        extra['package'] += ['--upstream', f'{stage}:public']
    if args.provenance:
        extra['select'] += ['--provenance', args.provenance]
    for source_id in args.exclude_source or ():
        extra['select'] += ['--exclude-source', source_id]
    for name in ('coarse', 'water', 'coarse-source', 'coarse-date'):
        if value := getattr(args, name.replace('-', '_')):
            extra['zone'] += [f'--{name}', value]
    if args.qa_support:
        extra['qa'] += ['--support', args.qa_support]
    for zoom, path in args.qa_fine_proof or ():
        extra['qa'] += ['--fine-proof', zoom, path]
    return extra


def missing_inputs(args, through):
    """``[(stage, [flag, ...])]`` for every stage of the chain whose required inputs were not given."""
    rows = []
    chain = chain_through(through)
    if 'zone' in chain and args.coarse and not args.coarse_source:
        rows.append(('zone', ['--coarse-source']))
    if 'shots' in chain and not args.basemap:
        rows.append(('shots', ['--basemap']))
    return rows


def bind_zone_inputs(cfg, out, region, zone):
    """Fill only omitted options from verified producer outputs, just before zone."""
    flags = zone[::2]
    if '--coarse' in flags and '--water' in flags:
        return

    from skippercast.relief import receipts

    receipt_region = receipts.Region(out, region)

    def outputs(stage, *names):
        verdict = receipts.check(receipt_region, stage)
        if not verdict.done or verdict.receipt is None:
            raise ValueError(f'{stage} is not done ({verdict.state}: {verdict.reason})')
        for name in names:
            paths = [receipt_region.resolve(item['path']) for item in verdict.receipt['outputs']
                     if Path(item['path']).name == name]
            if len(paths) != 1:
                raise ValueError(f'{stage} receipt must name one {name} output')
            if under(paths[0], cfg.forbidden_root):
                raise ValueError(f'{stage} output {name} is under {cfg.forbidden_root}')
            yield str(paths[0])

    if '--coarse' not in flags:
        if '--coarse-source' in flags:
            coarse, = outputs('coarse', 'coarse-3310.tif')
        else:
            coarse, report = outputs('coarse', 'coarse-3310.tif', 'coarse.json')
            doc = json.loads(Path(report).read_bytes())
            family = doc.get('family') if isinstance(doc, dict) else None
            if not isinstance(family, str) or not family.strip():
                raise ValueError('coarse.json has no family')
            zone += ['--coarse-source', family]
        zone += ['--coarse', coarse]
    if '--water' not in flags:
        water, = outputs('water', 'water.geojson')
        zone += ['--water', water]


def attested_generation(raw, region, stage):
    doc = json.loads(raw)
    if not isinstance(doc, dict) or doc.get('region') != region or not isinstance(doc.get('stages'), list):
        raise ValueError('invalid status document')
    rows = [r for r in doc['stages'] if isinstance(r, dict) and r.get('key') == stage]
    if len(rows) != 1:
        raise ValueError(f'expected one {stage} status row')
    row = rows[0]
    if row.get('state') != 'done':
        raise ValueError(f'{stage} is not done ({row.get("state")}: {row.get("reason")})')
    generation = row.get('generation')
    if not isinstance(generation, str) or not HEX64.fullmatch(generation):
        raise ValueError(f'invalid {stage} generation')
    return generation


def bind_handoff(cfg, out, region, extra, raw, stage):
    generation = attested_generation(raw, region, stage)
    if stage == 'package':
        release = real(out) / region / 'release' / generation / 'release.json'
        if real(release) != release or under(release, cfg.forbidden_root):
            raise ValueError('release path is not a canonical local artifact')
        values = {'<generation>': generation, '<release-sha256>': hashlib.sha256(release.read_bytes()).hexdigest()}
        for downstream in ('qa', 'envelope'):
            extra[downstream] = [values.get(arg, arg) for arg in extra[downstream]]
    else:
        # The capture stage is content-addressed separately from the package.
        index = extra['qa'].index('--shots') + 1
        extra['qa'][index] = str(out / region / 'shots' / generation / 'shots.json')


def check_guards(cfg, out, norm, inputs=(), *, basemap=None):
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
    if basemap is not None and not under(basemap, cfg.forbidden_root):
        # Both the lexical/comparable path and its actual target must be inside admitted read roots.
        allowed = basemap_allowed(cfg, basemap)
        try:
            ok = allowed and Path(basemap).is_file()
        except OSError:
            ok = False
        checks.append(('basemap', ok, f'{basemap} must be an existing file in an allowed read root'))
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


def _iso(moment):
    return moment.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def step_state(code):
    """The run-log state of one finished step from its exit code (module docstring)."""
    return EXIT_STATES.get(code, 'failed') if code else 'ok'


class RunLog:
    """``OUT/<region>/runs/<stamp>-p<pid>.json``, rewritten atomically after every step.

    Every write goes through a descriptor of the verified ``runs`` directory: the directory
    and the region directory are opened without following symlinks, the temporary file is
    created exclusively (``O_EXCL | O_NOFOLLOW``) inside it and renamed in it, so neither a
    redirected ``runs`` nor a planted temporary path can send the log elsewhere.
    """

    def __init__(self, cfg, out, region, through):
        self.cfg = cfg
        started = cfg.clock()
        self.path = out / region / RUNS_DIR / f'{started.astimezone(timezone.utc):%Y%m%dT%H%M%SZ}-p{cfg.pid}.json'
        self.doc = {'schema': RUN_LOG_SCHEMA, 'region': region, 'through': through, 'started': _iso(started),
                    'ended': None, 'outcome': 'running', 'exit': None, 'reason': None, 'steps': []}
        self.broken = False
        self.dir_fd = None
        try:
            self.dir_fd = self._open_runs_dir(out, region)
        except OSError as exc:
            self._warn(exc)
        self.save()

    @staticmethod
    def _open_runs_dir(out, region):
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        region_fd = os.open(Path(out) / region, flags)
        try:
            try:
                os.mkdir(RUNS_DIR, 0o755, dir_fd=region_fd)
            except FileExistsError:
                pass
            return os.open(RUNS_DIR, flags, dir_fd=region_fd)
        finally:
            os.close(region_fd)

    def _warn(self, exc):
        # stderr: stdout's last line is the run's result (completion, stop reason or R8 packet),
        # and the final log write happens after it.
        self.broken = True
        print(f'run_region: warning: cannot write the run log {self.path}: {exc} (the chain continues)',
              file=sys.stderr, flush=True)

    def step(self, name, code, state, seconds):
        self.doc['steps'].append({'step': name, 'exit': code, 'state': state, 'seconds': round(seconds, 1)})
        self.save()

    def finish(self, outcome, code, reason=None):
        self.doc.update(ended=_iso(self.cfg.clock()), outcome=outcome, exit=code, reason=reason)
        self.save()

    def save(self):
        if self.broken:
            return
        tmp = f'.{self.path.name}.tmp-{os.urandom(6).hex()}'
        data = (json.dumps(self.doc, indent=1) + '\n').encode()
        try:
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o644, dir_fd=self.dir_fd)
            try:
                with os.fdopen(fd, 'wb') as handle:
                    handle.write(data)
                os.replace(tmp, self.path.name, src_dir_fd=self.dir_fd, dst_dir_fd=self.dir_fd)
            except OSError:
                try:
                    os.unlink(tmp, dir_fd=self.dir_fd)
                except OSError:
                    pass
                raise
        except OSError as exc:
            self._warn(exc)

    def close(self):
        if self.dir_fd is not None:
            os.close(self.dir_fd)
            self.dir_fd = None

    def table(self):
        rows = [(s['step'], s['state'], f'{s["seconds"]:.1f}') for s in self.doc['steps']]
        width = max([len('step'), *(len(r[0]) for r in rows)])
        lines = [f'run log {self.path}', f'  {"step":<{width}}  {"state":<13}  seconds']
        lines += [f'  {step:<{width}}  {state:<13}  {seconds:>7}' for step, state, seconds in rows]
        return '\n'.join(lines)


def show_rebuild_plan(cfg, out, region, survey=()):
    if __package__:
        from . import rebuild_plan as report
    else:
        import rebuild_plan as report

    stages = out / region / 'stages'
    if under(out, cfg.forbidden_root) or under(stages, cfg.forbidden_root):
        say('rebuild plan unavailable: receipt directory is under the forbidden root')
        return
    try:
        # The planner reads every *.json receipt, including scoped and symlinked files.
        if any(under(path, cfg.forbidden_root) for path in stages.glob('*.json')):
            say('rebuild plan unavailable: receipt is under the forbidden root')
            return
        rows = report._region_plan(out, region, report._stage_digests(), survey=survey)
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
        say(f'rebuild plan unavailable: {exc}')
        return
    say('rebuild plan (from receipts):')
    for row in rows:
        reasons = ', '.join(row['reasons']) or '-'
        say(f"  {row['stage']} {row['action']} ({reasons})")


def dry_run(cfg, region, out, norm, through, extra, inputs, missing, basemap, *, show_plan):
    source_root = Path(__file__).resolve().parents[2] / 'src'
    if str(source_root) not in sys.path:
        sys.path.insert(0, str(source_root))
    from skippercast.relief.render_config import resolve_style

    say(f'run_region dry run: region {region}, through {through}, out {out}')
    try:
        version, style = resolve_style(region)
        say(f"tiles style: {version}; B={style.digest('baked') if style is not None else '(legacy)'}")
    except (OSError, ValueError) as exc:
        say(f'  REFUSE tiles style: {exc}')
        if 'tiles' in chain_through(through):
            missing = [*missing, ('tiles', ('valid render recipe',))]
    if 'census-bind' in extra:
        say('inputs for census-bind: --census (option), --census-sha256 (option)')
    if 'zone' in chain_through(through):
        zone = extra['zone']
        flags = zone[::2]
        sources = []
        for flag, producer in ZONE_STAGE_INPUTS.items():
            if flag in flags:
                sources.append(f'{flag} (option)')
            elif flag == '--coarse-source' and '--coarse' in flags:
                sources.append(f'{flag} (missing option)')
            else:
                sources.append(f'{flag} (stage {producer})')
                label = 'family' if flag == '--coarse-source' else 'output'
                zone += [flag, f'<{producer} {label}>']
        say('inputs for zone: ' + ', '.join(sources))
    say('chain (in order, each as a subprocess under ' + ' '.join(cfg.prefix) + '):')
    for index, (stage, attest) in enumerate(steps_through(through, extra), 1):
        note = f'  # verify {attest}' if attest else ''
        say(f'  {index:>2}. {" ".join(stage_command(cfg, stage, region, out, extra))}{note}')
    later = chain_through(STAGES[-1], extra.get(SKIP, ()))[len(chain_through(through, extra.get(SKIP, ()))):]
    say('not run: ' + (', '.join(later) or '(none)'))
    if extra.get(SKIP):
        say('skipped (--survey): ' + ', '.join(extra[SKIP]))
    if through == 'envelope':
        say('r8 packet: after envelope')
    if show_plan:
        show_rebuild_plan(cfg, out, region,
                          tuple(stage for stage in SURVEY_STAGES if stage not in extra.get(SKIP, ())))
    say('guards (re-checked before every stage):')
    refused = bool(missing)
    for stage, flags in missing:
        say(f'  REFUSE {stage} inputs: a real run through {through} needs ' + ', '.join(flags))
    for name, ok, detail in check_guards(cfg, out, norm, inputs, basemap=basemap):
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


def refusal(cfg, out, norm, inputs, basemap):
    return [f'{name}: {detail}' for name, ok, detail in check_guards(cfg, out, norm, inputs, basemap=basemap) if not ok]


def run_cap_refusal(cfg):
    try:
        others = other_runs(cfg)
    except OSError as exc:  # fail closed: an unreadable process table is not "no other runs"
        return EXIT_REFUSED, f'cannot establish how many runs are on the box: {exc}'
    if len(others) + 1 > cfg.max_runs:
        return (EXIT_RUNNING, f'{len(others)} other run_region.py process(es) already running '
                f'(pids {", ".join(map(str, others))}); at most {cfg.max_runs} at once')
    return None


def run_chain(cfg, region, out, norm, through, extra, inputs, basemap):
    if cap := run_cap_refusal(cfg):
        code, detail = cap
        say(f'run_region: refused: {detail}')
        return code
    problems = refusal(cfg, out, norm, inputs, basemap)  # before any lock, so a refused run leaves no file behind
    if problems:
        first = 'census-bind' if 'census-bind' in extra else STAGES[0]
        say(f'run_region: refused before {first}: ' + '; '.join(problems))
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
        return run_locked(cfg, region, out, norm, through, extra, inputs, basemap)
    finally:
        os.close(slot)


def print_r8_packet(cfg, region, out):
    command = [*cfg.prefix, cfg.python, '-B', str(cfg.r8_packet_py), '--out', str(out), region]
    try:
        result = subprocess.run(command, stdin=subprocess.DEVNULL, capture_output=True, text=True, errors='replace')
    except OSError as exc:
        reason = f'cannot start the command: {exc}'
    else:
        print(result.stdout, end='', flush=True)
        if not result.returncode:
            return 0
        heading = f'NOT READY {region}: '
        reason = (result.stdout.rstrip('\n').removeprefix(heading) if result.stdout.startswith(heading)
                  else result.stderr.strip() or f'r8_packet.py exit {result.returncode}')
    say(f'run_region: envelope written but R8 packet NOT READY: {reason}')
    return 1


def run_locked(cfg, region, out, norm, through, extra, inputs, basemap):
    try:
        fd = acquire_lock(cfg, out, region)
    except (OSError, RuntimeError) as exc:
        say(f'run_region: refused: cannot take the region lock: {exc}')
        return EXIT_REFUSED
    if fd is None:
        say(f'run_region: refused: region {region} already has a run (lock {lock_path(out, region)})')
        return EXIT_RUNNING
    log = RunLog(cfg, out, region, through)

    def end(outcome, code, reason):
        # The table comes first, so the run's last line stays the reason it stopped.
        log.finish(outcome, code, reason)
        say(log.table())
        say(f'run_region: {reason}')
        return code

    try:
        for stage, attest in steps_through(through, extra):
            problems = refusal(cfg, out, norm, inputs, basemap)
            if problems:
                return end('refused', EXIT_REFUSED, f'refused before {stage}: ' + '; '.join(problems))
            if cap := run_cap_refusal(cfg):
                code, detail = cap
                return end('refused', code, f'refused before {stage}: {detail}')
            if stage == 'zone':
                try:
                    bind_zone_inputs(cfg, out, region, extra['zone'])
                except (OSError, ValueError) as exc:
                    return end('refused', EXIT_REFUSED, f'refused before zone: {exc}')
            command = stage_command(cfg, stage, region, out, extra)
            label = f'status for {attest}' if attest else stage
            step = f'status:{attest}' if attest else stage
            say(f'run_region: stage {label}: ' + ' '.join(command))
            started = time.monotonic()
            try:
                result = subprocess.run(command, stdin=subprocess.DEVNULL, capture_output=bool(attest))
            except OSError as exc:
                log.step(step, None, 'failed', time.monotonic() - started)
                return end('stopped', 1, f'STOPPED at {label}: cannot start the command: {exc}')
            code = result.returncode
            seconds = time.monotonic() - started
            if code == 0:
                if attest:
                    try:
                        bind_handoff(cfg, out, region, extra, result.stdout, attest)
                    except (OSError, ValueError) as exc:
                        log.step(step, 0, 'failed', seconds)
                        return end('stopped', EXIT_REFUSED, f'STOPPED at {label}: {exc}')
                log.step(step, 0, step_state(0), seconds)
                say(f'run_region: stage {label}: exit 0 ({seconds:.1f}s)')
                continue
            log.step(step, code, step_state(code), seconds)
            if attest and result.stderr:
                say(result.stderr.decode(errors='replace').rstrip())
            if code == EXIT_USAGE:
                return end('stopped', EXIT_USAGE, f'STOPPED at {label}: not available (region.py exit 2: no such '
                           f'stage module on this checkout, or a usage error; see its message above)')
            return end('stopped', code if 0 < code < 256 else 1, f'STOPPED at {label}: exit {code}')
        say(log.table())
        say(f'run_region: {region} complete through {through}')
        # Keep the region lock until the packet has read the just-built evidence.
        code = print_r8_packet(cfg, region, out) if through == 'envelope' else 0
        log.finish('complete' if code == 0 else 'stopped', code,
                   None if code == 0 else 'envelope written but R8 packet NOT READY')
        return code
    except KeyboardInterrupt:
        log.finish('interrupted', 130, 'interrupted')
        raise
    finally:
        log.close()
        os.close(fd)  # releases the lock


def parse(argv):
    parser = argparse.ArgumentParser(prog='run_region.py', description='Run one region through the relief stage chain, guarded.',
                                     epilog='stages: ' + ' '.join(STAGES))
    parser.add_argument('region', help='region id (a line of regions.tsv)')
    parser.add_argument('--out', default=os.environ.get('SC_RELIEF_OUT') or None,
                        help='pipeline output root OUT (default $SC_RELIEF_OUT; required except for dry runs)')
    parser.add_argument('--through', help='last stage to run (required except for a full dry-run preview): '
                        + ', '.join(STAGES))
    parser.add_argument('--norm', help='normalized cache NORM: checked against the private-vault guard and passed '
                        f'to select as --cache (default $SC_RELIEF_NORM when set, else {DEFAULT_NORM})')
    parser.add_argument('--scope', default='public', choices=('public', 'private'),
                        help='scope of the scoped stages mosaic, tiles and zone (default public)')
    parser.add_argument('--survey', default='none', choices=tuple(SURVEY_SKIPS),
                        help='survey layers in the release: none (default; no survey stage), detail '
                        '(survey_detail only) or detail-and-gap (survey_detail and survey_gap)')
    parser.add_argument('--basemap', help='local basemap PMTiles (required for shots, qa and envelope)')
    parser.add_argument('--qa-support', help='qa option: mosaic support_class TIFF')
    parser.add_argument('--qa-fine-proof', nargs=2, action='append', metavar=('ZOOM', 'PATH'),
                        help='qa option: fine-support raster for zoom 16 or 17 (z16/z17 also accepted; qa receives 16/17); repeat per zoom')
    parser.add_argument('--region-config', help='region config file for select, mosaic, tiles and zone (default: regions/<id>/region.json)')
    parser.add_argument('--provenance', help='select input: source-label file (PROVENANCE-LABELS.json); default is '
                        "select's own ($SC_RELIEF_PROVENANCE, else the working directory)")
    parser.add_argument('--census', help='local census to bind before select')
    parser.add_argument('--exclude-source', action='append', default=[], metavar='REGISTRY_ID',
                        help='select option: skip census rows bound to this registry source id (repeatable)')
    parser.add_argument('--census-sha256', help='expected SHA-256 of --census (required with --census)')
    parser.add_argument('--coarse', help='zone input: EPSG:3310 elevation TIFF (defaults to done coarse output)')
    parser.add_argument('--water', help='zone input: WGS84 ocean-water GeoJSON (defaults to done water output)')
    parser.add_argument('--coarse-source', help='zone source ID (required with --coarse; otherwise defaults to the coarse family)')
    parser.add_argument('--coarse-date', help='zone input: optional date of --coarse')
    parser.add_argument('--inputs', metavar='FILE', help='region input record (sc-run-inputs/1), with SHA-256 pinned files')
    parser.add_argument('--dry-run', action='store_true', help='print the chain and the guard state; run nothing')
    args = parser.parse_args(argv)
    if args.inputs is None:
        resolve_options(args, parser)
    return parser, args


def resolve_options(args, parser, pins=()):
    if bool(args.census) != bool(args.census_sha256):
        parser.error('--census and --census-sha256 must be given together')
    args.norm = effective_norm(args.norm)  # resolved once: guarded and forwarded as the very same path
    # every file input is likewise fixed once here: the spelling the guard resolves is the spelling forwarded
    for name in PATH_OPTIONS:
        if name in pins or getattr(args, name):
            setattr(args, name, spelled(getattr(args, name)))
    if args.qa_fine_proof:
        args.qa_fine_proof = [(fine_zoom(parser, zoom), spelled(path)) for zoom, path in args.qa_fine_proof]



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
    if args.through == 'normalize':
        parser.error('normalize is a separate, guarded per-source step: run region.py normalize --source PATH '
                     'once per held source before starting run_region.py')
    if args.through not in STAGES:
        parser.error(f'unknown stage {args.through!r}; stages: {", ".join(STAGES)}')
    if args.through in SURVEY_SKIPS[args.survey]:
        parser.error(f'--survey {args.survey} skips {args.through}; choose a stage this chain runs '
                     '(survey stages run only with --survey detail or detail-and-gap)')
    if args.scope != 'public' and any(stage in chain_through(args.through, SURVEY_SKIPS[args.survey])
                                      for stage in SURVEY_STAGES):
        parser.error(f'the chain reaches the public-only survey stages; with --scope {args.scope} '
                     'use --survey none or stop before survey_detail')
    if args.out is None and not args.dry_run:
        parser.error('the following arguments are required: --out')
    out = Path(os.path.abspath(os.path.expanduser(args.out))) if args.out is not None else Path('<OUT>')
    if args.out is not None and not out.is_dir():
        parser.error(f'--out {out} is not an existing directory')
    if args.inputs is not None:
        if under(args.inputs, cfg.forbidden_root):
            say(f'run_region: refused --inputs: {args.inputs} is under {cfg.forbidden_root}')
            return EXIT_REFUSED
        record_digest, pins = load_inputs(args, parser)
        resolve_options(args, parser, pins)
        checks = {name: input_problem(cfg, name, getattr(args, name), pin) for name, pin in pins.items()}
        if args.dry_run:
            say(f'inputs from {args.inputs} (sha256 {record_digest})')
            for name, problem in checks.items():
                say(f'  {name}: MISMATCH ({problem})' if problem else f'  {name}: ok')
        else:
            for name, problem in checks.items():
                if problem:
                    say(f'run_region: refused input {name}: {problem}')
        if any(checks.values()):
            return EXIT_REFUSED
    norm = args.norm
    missing = missing_inputs(args, args.through)
    if missing and not full_preview:
        parser.error('; '.join(f'the chain reaches {stage}, which needs {", ".join(flags)}' for stage, flags in missing))
    if args.out is None:
        missing = [('pipeline', ('--out',)), *missing]
    extra = stage_extras(args, out)
    # the very spellings stage_extras forwards, so guard and child see one path
    inputs = [Path(p) for p in (*(getattr(args, name) for name in PATH_OPTIONS),
                                *(path for _, path in args.qa_fine_proof or ())) if p]
    if args.dry_run:
        # Lazy imports for the preview must not create bytecode caches on a cold checkout.
        previous = sys.dont_write_bytecode
        sys.dont_write_bytecode = True
        try:
            return dry_run(cfg, args.region, out, norm, args.through, extra, inputs, missing, args.basemap,
                           show_plan=args.out is not None)
        finally:
            sys.dont_write_bytecode = previous
    try:
        return run_chain(cfg, args.region, out, norm, args.through, extra, inputs, args.basemap)
    except KeyboardInterrupt:
        say('run_region: interrupted')
        return 130


if __name__ == '__main__':
    # Prefer this checkout, as region.py does, for receipt verification.
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'src'))
    sys.exit(main())
