"""Stage receipts, the generation chain and the "done" rule (E2E-PIPELINE §3).

Every stage of a region writes ``OUT/<region>/stages/<stage>.json`` (``<stage>.<scope>.json``
for a scoped stage such as the public and private mosaics), schema ``sc-stage-receipt/1``::

    {"schema": "sc-stage-receipt/1", "region": "morro-bay", "stage": "mosaic", "scope": "public",
     "generation": "<sha256 of canonical {inputs, upstream, code, params}>",
     "inputs": [{"path": "...", "sha256": "...", "role": "sources"}],
     "upstream": [{"stage": "select", "generation": "..."}],
     "code": {"repo_sha": "<40 hex>", "stage_digest": "<sha256 of the stage's module files>"},
     "params": {...}, "target": "mosaic/public",
     "outputs": [{"path": "mosaic/public/elevation.tif", "sha256": "...", "bytes": 123}],
     "attempt": 1, "started": "...", "ended": "...", "rc": 0, "status": "ok|failed|held",
     "held_reason": null, "error": null, "host": {"load5": 12.3, "free_root_gb": 355.0}}

Rules (E2E-PIPELINE §3):

1. **Generation.** ``generation`` is the sha256 of the canonical JSON of the stage's inputs
   (role and content sha256; a path is recorded but not hashed, so moving a file does not
   rebuild), its upstream generations, its code (``stage_digest`` only: ``repo_sha`` is
   recorded, not hashed, so a commit that does not touch a stage's files does not rebuild
   it) and its params. The same inputs, upstream, code and params always give the same
   generation, on any host and in any directory.
2. **Done** = the receipt has status ``ok``, every output re-hashes (size and sha256) to the
   receipt, and every upstream generation equals the generation in the *current* upstream
   receipt, which is itself done. A stage run is additionally a no-op only when its newly
   computed generation equals the receipt's.
3. **Write then rename.** A run builds into ``<target>.tmp-<pid>`` and renames it to
   ``<target>`` only after the build returned; an existing ``<target>`` is moved aside to
   ``<target>.old-<stamp>`` first, never written in place. A failed attempt is kept as
   ``<target>.failed-<stamp>``; the half-written directory of a crashed attempt is moved
   to ``<target>.failed-<stamp>-recovered-<pid>`` by the next run. Receipts are written to
   a temporary file and renamed with ``os.replace``.
4. **Attempts** are counted per (stage, scope, generation). Each run records its attempt
   in the receipt *before* building (status ``failed``, ``error`` "interrupted ..."), so a
   crash or kill still counts. At most :data:`MAX_ATTEMPTS`; the failure of the last
   allowed attempt writes a ``held`` receipt with the reason, and a held generation is
   never rerun. A new generation (fixed upstream, code or params) starts at attempt 1.
5. **One run at a time** per (stage, scope): ``stages/<name>.lock`` is held with ``flock``.

Nothing here downloads, uploads or publishes.
"""
from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
import fcntl
import glob
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
from typing import Any

from skippercast.paths import repo_root

SCHEMA = 'sc-stage-receipt/1'
MAX_ATTEMPTS = 2
STATUSES = ('ok', 'failed', 'held')
STAGE_NAME = re.compile(r'[a-z][a-z0-9_]{0,63}')
SCOPE_NAME = re.compile(r'[a-z][a-z0-9_-]{0,31}')
REGION_ID = re.compile(r'[a-z0-9][a-z0-9-]{0,63}')
HEX64 = re.compile(r'[0-9a-f]{64}')
INTERRUPTED = 'interrupted: the attempt started and recorded no result (crash or kill)'
ERROR_CHARS = 2000
# Result state -> region.py exit code.
EXIT_CODES = {'done': 0, 'ok': 0, 'failed': 1, 'blocked': 3, 'held': 4, 'busy': 5}


class ReceiptError(ValueError):
    """A stage definition, name or receipt that the pipeline refuses."""


class Held(Exception):
    """Raised by a stage build to hold the stage for this generation (reason = message)."""


@dataclass(frozen=True)
class Input:
    """One file a stage reads; ``role`` names what it is for (``sources``, ``grid``, ...)."""
    path: str | os.PathLike
    role: str


@dataclass(frozen=True)
class Plan:
    """What a stage reads (files) and the parameters that change its outputs."""
    inputs: Sequence[Input] = ()
    params: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Ref:
    """An upstream stage receipt: ``stage`` or ``stage`` + ``scope``."""
    stage: str
    scope: str | None = None

    @classmethod
    def parse(cls, text: str, scope: str | None = None) -> Ref:
        """``"select"`` or ``"mosaic:public"``; ``{scope}`` becomes the running stage's scope."""
        if '{scope}' in text:
            if scope is None:
                raise ReceiptError(f'upstream {text!r} needs a scope')
            text = text.replace('{scope}', scope)
        stage, _, sc = text.partition(':')
        ref = cls(stage, sc or None)
        check_names(ref.stage, ref.scope)
        return ref

    @property
    def key(self) -> str:
        return self.stage if self.scope is None else f'{self.stage}.{self.scope}'


@dataclass
class StageContext:
    """What region.py hands to a stage module's ``plan`` and ``build``."""
    region: Region
    scope: str | None
    args: Any = None
    upstream: dict[str, dict] = field(default_factory=dict)


@dataclass(frozen=True)
class Verdict:
    """The "done" rule applied to one receipt."""
    state: str  # done | missing | invalid | unproved | stale | failed | running | held
    reason: str
    receipt: dict | None = None

    @property
    def done(self) -> bool:
        return self.state == 'done'


@dataclass(frozen=True)
class Result:
    """The outcome of :func:`run_stage`."""
    state: str  # done (no work) | ok | failed | held | blocked | busy
    stage: str
    scope: str | None
    generation: str | None
    reason: str
    receipt: Path

    @property
    def exit_code(self) -> int:
        return EXIT_CODES[self.state]

    def line(self) -> str:
        name = self.stage if self.scope is None else f'{self.stage}.{self.scope}'
        gen = (self.generation or '-')[:12]
        return f'[{name}] {self.state.upper()} generation {gen}: {self.reason}'


# --- names, hashing, canonical form ------------------------------------------------------------

def check_names(stage: str, scope: str | None = None, region: str | None = None) -> None:
    if not isinstance(stage, str) or not STAGE_NAME.fullmatch(stage):
        raise ReceiptError(f'invalid stage name {stage!r}')
    if scope is not None and (not isinstance(scope, str) or not SCOPE_NAME.fullmatch(scope)):
        raise ReceiptError(f'invalid scope {scope!r}')
    if region is not None and (not isinstance(region, str) or not REGION_ID.fullmatch(region)):
        raise ReceiptError(f'invalid region id {region!r}')


def canonical(obj: Any) -> bytes:
    """Canonical JSON bytes: sorted keys, no whitespace, UTF-8, no NaN/Infinity."""
    try:
        return json.dumps(obj, sort_keys=True, separators=(',', ':'), ensure_ascii=False,
                          allow_nan=False).encode('utf-8')
    except (TypeError, ValueError) as exc:
        raise ReceiptError(f'not canonical JSON: {exc}') from None


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: str | os.PathLike) -> str:
    digest = hashlib.sha256()
    with open(path, 'rb') as fh:
        for block in iter(lambda: fh.read(1 << 20), b''):
            digest.update(block)
    return digest.hexdigest()


def generation(inputs: Iterable[Mapping], upstream: Iterable[Mapping], stage_digest: str,
               params: Mapping) -> str:
    """sha256 of canonical {inputs, upstream, code, params} (rule 1 in the module docstring)."""
    doc = {
        'inputs': sorted([str(i['role']), str(i['sha256'])] for i in inputs),
        'upstream': sorted([str(u['stage']), str(u.get('scope') or ''), str(u['generation'])]
                           for u in upstream),
        'code': {'stage_digest': stage_digest},
        'params': dict(params),
    }
    return sha256_bytes(canonical(doc))


def stage_digest(files: Iterable[tuple[str, str | os.PathLike]]) -> str:
    """sha256 over sorted (label, file sha256) pairs: the code that makes a stage's outputs."""
    rows = sorted([label, sha256_file(path)] for label, path in files)
    if not rows:
        raise ReceiptError('a stage digest needs at least one code file')
    return sha256_bytes(canonical(rows))


def module_code_files(module: Any) -> list[tuple[str, Path]]:
    """A stage module's own file plus its ``CODE_FILES``.

    A ``CODE_FILES`` entry is a dotted module name (``skippercast.relief.support``) or a
    repository-relative path (``scripts/build_bathy_tiles.py``). Labels are names, not
    absolute paths, so the digest is the same in every checkout.
    """
    origin = getattr(module, '__file__', None)
    if not origin:
        raise ReceiptError(f'stage module {module.__name__} has no source file')
    files = [(module.__name__, Path(origin))]
    for entry in getattr(module, 'CODE_FILES', ()):
        if '/' in entry or entry.endswith('.py'):
            path = repo_root() / entry
        else:
            spec = importlib.util.find_spec(entry)
            if spec is None or not spec.origin:
                raise ReceiptError(f'{module.__name__}: CODE_FILES entry {entry!r} not found')
            path = Path(spec.origin)
        if not path.is_file():
            raise ReceiptError(f'{module.__name__}: CODE_FILES entry {entry!r} is not a file')
        files.append((entry, path))
    return files


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def host_facts(path: str | os.PathLike = '/') -> dict:
    """Load and free disk at the time of the attempt (recorded, never hashed)."""
    try:
        load5 = round(os.getloadavg()[1], 2)
    except OSError:
        load5 = None
    return {'load5': load5, 'free_root_gb': round(shutil.disk_usage('/').free / 1e9, 1),
            'free_out_gb': round(shutil.disk_usage(path).free / 1e9, 1)}


def detect_repo_sha() -> str | None:
    try:
        out = subprocess.run(['git', '-C', str(repo_root()), 'rev-parse', 'HEAD'],
                             capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    sha = out.stdout.strip()
    return sha if out.returncode == 0 and re.fullmatch(r'[0-9a-f]{40}', sha) else None


# --- files --------------------------------------------------------------------------------------

def _fsync_dir(path: Path) -> None:
    try:
        fd = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def write_json_atomic(path: Path, doc: Mapping) -> None:
    """Write ``doc`` to ``path`` through ``<path>.tmp-<pid>`` and ``os.replace``."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f'{path.name}.tmp-{os.getpid()}')
    try:
        with open(tmp, 'w', encoding='utf-8') as fh:
            json.dump(doc, fh, indent=1, sort_keys=True, ensure_ascii=False, allow_nan=False)
            fh.write('\n')
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink()
    _fsync_dir(path.parent)


def read_receipt(path: Path) -> dict | None:
    """The receipt at ``path``, ``None`` when absent; :class:`ReceiptError` when unreadable."""
    try:
        text = path.read_text(encoding='utf-8')
    except FileNotFoundError:
        return None
    try:
        doc = json.loads(text)
    except ValueError as exc:
        raise ReceiptError(f'{path.name}: not JSON ({exc})') from None
    if not isinstance(doc, dict):
        raise ReceiptError(f'{path.name}: not a JSON object')
    return doc


def validate_receipt(doc: Mapping, region: str, stage: str, scope: str | None) -> str | None:
    """Why ``doc`` is not a well-formed receipt for (region, stage, scope), or ``None``."""
    if doc.get('schema') != SCHEMA:
        return f'schema is {doc.get("schema")!r}, not {SCHEMA}'
    for key, want in (('region', region), ('stage', stage), ('scope', scope)):
        if doc.get(key) != want:
            return f'{key} is {doc.get(key)!r}, not {want!r}'
    if doc.get('status') not in STATUSES:
        return f'status {doc.get("status")!r}'
    if not isinstance(doc.get('generation'), str) or not HEX64.fullmatch(doc['generation']):
        return 'generation is not 64 hex'
    outputs, upstream = doc.get('outputs'), doc.get('upstream')
    if not isinstance(outputs, list) or not all(
            isinstance(o, dict) and isinstance(o.get('path'), str) and isinstance(o.get('sha256'), str)
            and isinstance(o.get('bytes'), int) for o in outputs):
        return 'outputs malformed'
    if not isinstance(upstream, list) or not all(
            isinstance(u, dict) and isinstance(u.get('stage'), str) and isinstance(u.get('generation'), str)
            for u in upstream):
        return 'upstream malformed'
    if not isinstance(doc.get('attempt'), int) or doc['attempt'] < 1:
        return 'attempt malformed'
    return None


@contextmanager
def _flock(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o644)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            yield False
            return
        try:
            yield True
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


def is_locked(path: Path) -> bool:
    """True while another process runs the stage that owns lock file ``path``."""
    if not path.exists():
        return False
    with _flock(path) as got:
        return not got


# --- a region's stage directory ----------------------------------------------------------------

class Region:
    """``OUT/<region>``: its ``stages/`` receipts and the outputs they name."""

    def __init__(self, out_root: str | os.PathLike, region: str):
        check_names('x', region=region)
        self.id = region
        self.out_root = Path(out_root).expanduser().resolve()
        self.dir = self.out_root / region
        self.stages_dir = self.dir / 'stages'

    def receipt_path(self, stage: str, scope: str | None = None) -> Path:
        check_names(stage, scope)
        return self.stages_dir / (f'{stage}.json' if scope is None else f'{stage}.{scope}.json')

    def lock_path(self, stage: str, scope: str | None = None) -> Path:
        return self.receipt_path(stage, scope).with_suffix('.lock')

    def record(self, path: str | os.PathLike) -> str:
        """How a path is written into a receipt: relative to the region dir when inside it."""
        p = Path(path).resolve()
        try:
            return p.relative_to(self.dir).as_posix()
        except ValueError:
            return str(p)

    def resolve(self, recorded: str) -> Path:
        p = Path(recorded)
        if p.is_absolute():
            return p
        if '..' in p.parts:
            raise ReceiptError(f'recorded path {recorded!r} leaves the region directory')
        return self.dir / p

    def keys(self) -> list[tuple[str, str | None]]:
        """Every (stage, scope) with a receipt file, sorted."""
        found = []
        for path in sorted(self.stages_dir.glob('*.json')):
            stage, _, scope = path.name[:-len('.json')].partition('.')
            try:
                check_names(stage, scope or None)
            except ReceiptError:
                continue
            found.append((stage, scope or None))
        return found


# --- the done rule -----------------------------------------------------------------------------

def _verify_ok(region: Region, doc: Mapping, memo: dict) -> Verdict:
    for out in doc['outputs']:
        try:
            path = region.resolve(out['path'])
        except ReceiptError as exc:
            return Verdict('invalid', str(exc), dict(doc))
        if path.is_symlink() or not path.is_file():
            return Verdict('unproved', f'output missing: {out["path"]}', dict(doc))
        if path.stat().st_size != out['bytes'] or sha256_file(path) != out['sha256']:
            return Verdict('unproved', f'output changed: {out["path"]}', dict(doc))
    for up in doc['upstream']:
        ref = Ref(up['stage'], up.get('scope'))
        try:
            current = read_receipt(region.receipt_path(ref.stage, ref.scope))
        except ReceiptError as exc:
            return Verdict('stale', f'upstream {ref.key} unreadable: {exc}', dict(doc))
        if current is None:
            return Verdict('stale', f'upstream {ref.key} has no receipt', dict(doc))
        if current.get('generation') != up['generation']:
            return Verdict('stale', f'upstream {ref.key} changed (was {up["generation"][:12]}, '
                                    f'now {str(current.get("generation"))[:12]})', dict(doc))
        verdict = check(region, ref.stage, ref.scope, memo=memo)
        if not verdict.done:
            return Verdict('stale', f'upstream {ref.key} not done ({verdict.state})', dict(doc))
    return Verdict('done', f'{len(doc["outputs"])} outputs re-hash; upstream current', dict(doc))


def check(region: Region, stage: str, scope: str | None = None, *, memo: dict | None = None) -> Verdict:
    """Apply the done rule to the receipt of (stage, scope); upstream receipts recursively."""
    memo = {} if memo is None else memo
    key = Ref(stage, scope).key
    if key in memo:
        return memo[key]
    memo[key] = Verdict('invalid', 'upstream cycle')
    memo[key] = verdict = _check_one(region, stage, scope, memo)
    return verdict


def _check_one(region: Region, stage: str, scope: str | None, memo: dict) -> Verdict:
    try:
        doc = read_receipt(region.receipt_path(stage, scope))
    except ReceiptError as exc:
        return Verdict('invalid', str(exc))
    if doc is None:
        return Verdict('missing', 'no receipt')
    problem = validate_receipt(doc, region.id, stage, scope)
    if problem:
        return Verdict('invalid', problem, doc)
    if doc['status'] == 'held':
        return Verdict('held', doc.get('held_reason') or 'held', doc)
    if doc['status'] == 'failed':
        if doc.get('error') == INTERRUPTED and is_locked(region.lock_path(stage, scope)):
            return Verdict('running', f'attempt {doc["attempt"]} running', doc)
        return Verdict('failed', f'attempt {doc["attempt"]}: {doc.get("error") or doc.get("rc")}', doc)
    return _verify_ok(region, doc, memo)


def chain(region: Region) -> list[tuple[str, Verdict]]:
    """Every receipt of a region in upstream-first order, with its verdict."""
    memo: dict = {}
    verdicts = {Ref(s, sc).key: check(region, s, sc, memo=memo) for s, sc in region.keys()}
    needs = {}
    for key, verdict in verdicts.items():
        ups = (verdict.receipt or {}).get('upstream') or []
        needs[key] = {Ref(u.get('stage', ''), u.get('scope')).key for u in ups if isinstance(u, dict)} & set(verdicts)
    order: list[str] = []
    while needs:
        ready = sorted(k for k, deps in needs.items() if not deps - set(order))
        if not ready:  # a cycle: list what is left by name
            ready = sorted(needs)
        for key in ready:
            order.append(key)
            del needs[key]
    return [(key, verdicts[key]) for key in order]


# --- running a stage ---------------------------------------------------------------------------

@dataclass
class StageRun:
    """One stage of one region (and scope), ready for :func:`run_stage`.

    ``plan`` is a :class:`Plan` or a callable that receives the verified upstream receipts
    (``{key: receipt}``) and returns one. ``build(out_dir)`` writes every output into
    ``out_dir`` and may return a dict of metrics (any other return value is ignored). ``target`` (default ``{stage}`` or
    ``{stage}/{scope}``) may use ``{stage}``, ``{scope}``, ``{generation}`` and ``{gen12}``;
    a relative target is under the region directory.
    """
    region: Region
    stage: str
    build: Callable[[Path], Mapping | None]
    code_digest: str
    scope: str | None = None
    upstream: Sequence[Ref] = ()
    plan: Plan | Callable[[dict], Plan] | None = None
    target: str | None = None


def _target(run: StageRun, gen: str) -> Path:
    template = run.target or ('{stage}' if run.scope is None else '{stage}/{scope}')
    text = template.format(stage=run.stage, scope=run.scope or '', generation=gen, gen12=gen[:12])
    path = Path(text)
    if path.is_absolute():
        return path
    if not path.parts or '..' in path.parts or path.parts[0] == 'stages':
        raise ReceiptError(f'invalid target {text!r}')
    return run.region.dir / path


def _collect_outputs(region: Region, built: Path, target: Path) -> list[dict]:
    rows = []
    for path in sorted(built.rglob('*')):
        if path.is_symlink():
            raise ReceiptError(f'output {path.relative_to(built)} is a symlink')
        if path.is_file():
            final = target / path.relative_to(built)
            rows.append({'path': region.record(final), 'sha256': sha256_file(path),
                         'bytes': path.stat().st_size})
    return rows


def _error_text(exc: BaseException) -> str:
    return f'{type(exc).__name__}: {exc}'[:ERROR_CHARS]


def _aside(target: Path, suffix: str) -> Path:
    """A free sibling name ``<target>.<suffix>`` (``-2``, ``-3`` ... appended if taken)."""
    path, n = target.with_name(f'{target.name}.{suffix}'), 1
    while path.exists() or path.is_symlink():
        n += 1
        path = target.with_name(f'{target.name}.{suffix}-{n}')
    return path


def run_stage(run: StageRun, *, clock: Callable[[], datetime] = utc_now,
              host: Callable[..., dict] = host_facts,
              repo_sha: Callable[[], str | None] = detect_repo_sha) -> Result:
    """Run one stage under the receipt rules; a done stage is a no-op (see module docstring)."""
    check_names(run.stage, run.scope, run.region.id)
    region = run.region
    receipt_path = region.receipt_path(run.stage, run.scope)

    def result(state, gen, reason):
        return Result(state, run.stage, run.scope, gen, reason, receipt_path)

    with _flock(region.lock_path(run.stage, run.scope)) as got:
        if not got:
            return result('busy', None, 'another run of this stage holds its lock')
        memo: dict = {}
        upstream_rows, upstream_docs = [], {}
        for ref in run.upstream:
            verdict = check(region, ref.stage, ref.scope, memo=memo)
            if not verdict.done:
                return result('blocked', None, f'upstream {ref.key} not done ({verdict.state}: {verdict.reason})')
            row = {'stage': ref.stage, 'generation': verdict.receipt['generation']}
            if ref.scope is not None:
                row['scope'] = ref.scope
            upstream_rows.append(row)
            upstream_docs[ref.key] = verdict.receipt
        upstream_rows.sort(key=lambda r: (r['stage'], r.get('scope') or ''))
        plan = run.plan(upstream_docs) if callable(run.plan) else (run.plan or Plan())
        inputs = []
        for item in plan.inputs:
            path = Path(item.path)
            if not path.is_file():
                return result('blocked', None, f'input missing: {item.path}')
            inputs.append({'path': region.record(path), 'sha256': sha256_file(path), 'role': str(item.role)})
        params = json.loads(canonical(dict(plan.params)))
        gen = generation(inputs, upstream_rows, run.code_digest, params)
        target = _target(run, gen)

        try:
            prev = read_receipt(receipt_path)
        except ReceiptError:
            prev = None
        if prev is not None and validate_receipt(prev, region.id, run.stage, run.scope):
            prev = None
        # Keep prior generations in the same atomic receipt as the current attempt.
        # Thus a crash cannot advance one without preserving the other.
        history = prev.get('generation_history', {}) if prev else {}
        if not isinstance(history, dict) or any(
                not isinstance(key, str) or not isinstance(doc, dict)
                or validate_receipt(doc, region.id, run.stage, run.scope)
                or doc['generation'] != key for key, doc in history.items()):
            return result('blocked', gen, 'generation history malformed')
        history = dict(history)
        if prev is not None:
            history[prev['generation']] = {k: v for k, v in prev.items() if k != 'generation_history'}
        same = history.get(gen)

        def save(doc):
            write_json_atomic(receipt_path, dict(doc, generation_history=history))

        if same is not None and same['status'] == 'held':
            if prev is not None and prev['generation'] != gen:
                save(same)
            return result('held', gen, same.get('held_reason') or 'held')
        if same is not None and prev is not None and prev['generation'] == gen and same['status'] == 'ok':
            verdict = _verify_ok(region, same, memo)
            if verdict.done:
                return result('done', gen, 'no work: receipt ok, outputs re-hash, upstream current')
        attempt = same['attempt'] + 1 if same is not None else 1

        started = clock()
        base = {
            'schema': SCHEMA, 'region': region.id, 'stage': run.stage, 'scope': run.scope,
            'generation': gen, 'inputs': inputs, 'upstream': upstream_rows,
            'code': {'repo_sha': repo_sha(), 'stage_digest': run.code_digest},
            'params': params, 'target': region.record(target), 'outputs': [],
            'attempt': attempt, 'started': iso(started), 'ended': None, 'rc': None,
            'status': 'failed', 'held_reason': None, 'error': INTERRUPTED,
        }
        region.dir.mkdir(parents=True, exist_ok=True)
        base['host'] = host(region.dir)
        if attempt > MAX_ATTEMPTS:
            reason = f'attempt limit ({MAX_ATTEMPTS}) reached for generation {gen[:12]}'
            save(dict(base, attempt=MAX_ATTEMPTS, status='held',
                                                 held_reason=reason, error=None, ended=iso(started)))
            return result('held', gen, reason)

        stamp = f'{started.astimezone(timezone.utc):%Y%m%dT%H%M%SZ}-a{attempt}-p{os.getpid()}'
        target.parent.mkdir(parents=True, exist_ok=True)
        for stale in sorted(target.parent.glob(f'{glob.escape(target.name)}.tmp-*')):
            if stale.is_dir() and not stale.is_symlink():
                stale.rename(_aside(target, f'failed-{stamp}-recovered-{stale.name.rsplit("-", 1)[-1]}'))
        save(base)  # the attempt is on record before any work starts

        tmp = target.with_name(f'{target.name}.tmp-{os.getpid()}')
        tmp.mkdir()
        failed_dir = _aside(target, f'failed-{stamp}')
        try:
            metrics = run.build(tmp)
            metrics = json.loads(canonical(dict(metrics))) if isinstance(metrics, Mapping) and metrics else None
            outputs = _collect_outputs(region, tmp, target)
        except Held as exc:
            if tmp.exists():
                tmp.rename(failed_dir)
            reason = str(exc) or 'held by the stage'
            save(dict(base, status='held', held_reason=reason, error=None,
                                                 ended=iso(clock()), failed_dir=region.record(failed_dir)))
            return result('held', gen, reason)
        except BaseException as exc:
            if tmp.exists():
                tmp.rename(failed_dir)
            error = _error_text(exc)
            rc = exc.code if isinstance(exc, SystemExit) and isinstance(exc.code, int) and exc.code else 1
            last = attempt >= MAX_ATTEMPTS
            reason = f'{MAX_ATTEMPTS} attempts failed for generation {gen[:12]}: {error}' if last else None
            save(dict(base, status='held' if last else 'failed', held_reason=reason,
                                                 error=error, rc=rc, ended=iso(clock()),
                                                 failed_dir=region.record(failed_dir)))
            if not isinstance(exc, Exception):
                raise
            return result('held' if last else 'failed', gen, reason or error)

        if target.exists() or target.is_symlink():
            target.rename(_aside(target, f'old-{stamp}'))
        tmp.rename(target)
        _fsync_dir(target.parent)
        doc = dict(base, status='ok', rc=0, error=None, ended=iso(clock()), outputs=outputs)
        if metrics:
            doc['metrics'] = metrics
        save(doc)
        return result('ok', gen, f'{len(outputs)} outputs, attempt {attempt}')
