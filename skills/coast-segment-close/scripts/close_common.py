"""Shared close/archive/verify/release logic (offline workflow tooling, not product code).

Closure is the exact set of files the shared GraphValidator reads while it
validates the campaign inventory and EVERY segment ledger row (selected and
superseded), with the explicit raw-provenance envelope union collected from the
admissions those rows pin. Nothing is found by globbing the hot tree.
"""
import argparse
from contextlib import contextmanager
import fcntl
import hashlib
import os
from pathlib import Path
import sqlite3
import stat
import sys
import tempfile

SHARED = Path(__file__).resolve().parents[2] / 'coast-campaign-shared/scripts'
sys.path.insert(0, str(SHARED))
from coast_refs import (REF_KEYS, Resolver, canonical, directory_fd, loads,  # noqa: E402
                        relative_parts, sha256, write_once)
from validate_coast_receipt import GraphValidator, _consistency, validate_schema  # noqa: E402
import coast_ledger  # noqa: E402

HEADER = ('created_utc', 'author_profile', 'author_model', 'card_id', 'code_commit', 'skill_commit')
MANIFEST = 'ARCHIVE-MANIFEST.json'
SEGMENT_SNAPSHOT = 'ledger/segment-ledger.jsonl'
CAMPAIGN_SNAPSHOT = 'ledger/campaign-ledger.jsonl'
STAGE_RESULT = 'coastal-stage-result-v1'
LIMIT = 32 * 1024 * 1024


class Refused(ValueError):
    """Closure/verification/release refusal (exit 3); nothing is released."""


def require(condition, message):
    if not condition:
        raise Refused(message)


def absolute(value):
    path = Path(value)
    if not path.is_absolute() or any(p in ('.', '..') for p in value.split('/')):
        raise argparse.ArgumentTypeError('file arguments must be absolute and normalized')
    return path


def parser(description):
    result = argparse.ArgumentParser(description=description)
    result.add_argument('--roots', required=True, type=absolute, help='Operator root bindings JSON')
    result.add_argument('--allowed-root-id', action='append', required=True,
                        help='Card-admitted namespace; repeat independently of the roots JSON')
    result.add_argument('--original-raw-roots', type=absolute,
                        help="Independently admitted {'raw:campaign': ORIGINAL_ABS_ROOT} (needed when envelopes exist)")
    return result


def load_json(path):
    raw = Path(path).read_bytes()
    require(len(raw) <= LIMIT, 'structured input exceeds 32 MiB')
    return loads(raw)


def header(path):
    value = load_json(path)
    require(isinstance(value, dict) and set(value) == set(HEADER) and all(isinstance(value[k], str) and value[k] for k in HEADER),
            'runtime header must hold exactly ' + ','.join(HEADER))
    return value


def find_root(bindings, prefix):
    found = [k for k in bindings if k.startswith(prefix)]
    require(len(found) == 1, 'exactly one ' + prefix + ' root binding required')
    return found[0]


def locate(bindings, path):
    """Exact (root_id, relative path) for an absolute path inside one binding."""
    path = Path(path)
    matches = [(k, path.relative_to(v).as_posix()) for k, v in bindings.items() if path.is_relative_to(v) and path != Path(v)]
    require(len(matches) == 1, 'file must belong to exactly one admitted root: ' + str(path))
    return matches[0]


def observe(root, relative):
    """No-follow open + fstat + hash of one file under an operator root.

    Returns (Ref-shaped dict without root_id, stat result). Refuses symlinks in
    any component, non-regular leaves and hardlink aliases are reported via
    st_nlink for the caller to judge.
    """
    parts = relative_parts(relative)
    with directory_fd(root) as top:
        fd = os.dup(top)
        try:
            for part in parts[:-1]:
                new = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                os.close(fd)
                fd = new
            leaf = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
            try:
                before = os.fstat(leaf)
                require(stat.S_ISREG(before.st_mode), 'not a regular file: ' + relative)
                digest = hashlib.sha256()
                size = 0
                while chunk := os.read(leaf, 1024 * 1024):
                    digest.update(chunk)
                    size += len(chunk)
                after = os.fstat(leaf)
                require((before.st_ino, before.st_size, before.st_mtime_ns) == (after.st_ino, after.st_size, after.st_mtime_ns),
                        'file changed during observation: ' + relative)
                return dict(path=relative, sha256=digest.hexdigest(), bytes=size), before
            finally:
                os.close(leaf)
        finally:
            os.close(fd)


class RecordingResolver:
    """Hot-side resolver that records every Ref the shared validator reads."""

    def __init__(self, inner):
        self.inner = inner
        self.bindings = inner.bindings
        self.reads = {}

    def read(self, ref, *, retain=True, reject_structured=False):
        raw = self.inner.read(ref, retain=retain, reject_structured=reject_structured)
        self.reads[canonical(ref)] = dict(ref)
        return raw


class ArchiveResolver:
    """Archive-only resolver (rev4 4.3).

    Original (root_id, path, sha256, bytes) keys resolve ONLY through the manifest
    table to archive/raw bytes. Refs already in an archive/raw namespace read
    those roots directly. No queue/repo binding exists, so there is no hot or
    checkout fallback. Original namespace spellings are independently supplied.
    """

    def __init__(self, inner, files, *, original_queue_roots, original_raw_roots=None):
        for root_id in inner.bindings:
            require(root_id.startswith(('archive:', 'raw:')), 'archive-only resolver accepts archive/raw bindings only')
        require(original_queue_roots and all(k.startswith('queue:') for k in original_queue_roots),
                'original queue roots must be queue namespaces')
        self.inner = inner
        self.table = {}
        for item in files:
            self.table[canonical(item['source_ref'])] = item['retained_ref']
        self.original_queue_roots = dict(original_queue_roots)
        if original_raw_roots is not None:
            self.original_raw_roots = dict(original_raw_roots)
        # validate() checks the receipt namespace is admitted; these values are
        # origin spellings only and are never opened.
        self.bindings = dict(inner.bindings, **{k: Path(v) for k, v in original_queue_roots.items()})
        self.reads = {}

    def read(self, ref, *, retain=True, reject_structured=False):
        require(isinstance(ref, dict) and set(ref) == REF_KEYS, 'typed Ref requires exactly root_id/path/sha256/bytes')
        key = canonical(ref)
        if key in self.table:
            target = self.table[key]
        elif ref['root_id'] in self.inner.bindings:
            target = ref
        else:
            raise Refused('unmapped reference (no retained archive/raw copy): ' + ref['root_id'] + ' ' + ref['path'])
        raw = self.inner.read(target, retain=retain, reject_structured=reject_structured)
        self.reads[key] = dict(ref)
        return raw


def collect_envelopes(resolver, rows):
    """Union of admission sources[*].raw_provenance envelopes (non raw:campaign)
    across every verdict row's context: selected AND superseded evidence."""
    envelopes = {}
    for row in rows:
        if row['kind'] != 'verdict':
            continue
        context = loads(resolver.read(row['context']))
        if row.get('validation_scope') == 'identity_snapshot':
            # The shared graph validates the context/report's diagnostic edges.
            # Its failed admission/run expectations are not scientific inputs.
            continue
        admission = loads(resolver.read(context['admission']))
        for source in admission['sources']:
            for item in source['raw_provenance']:
                if item['root_id'] != 'raw:campaign':
                    envelopes[canonical(item)] = item
    return [envelopes[k] for k in sorted(envelopes)]


@contextmanager
def exclusive_lock(path):
    path = Path(path)
    with directory_fd(path.parent) as parent:
        fd = os.open(path.name, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600, dir_fd=parent)
        try:
            st = os.fstat(fd)
            require(stat.S_ISREG(st.st_mode) and st.st_nlink == 1, 'writer lock must be single-link regular')
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as error:
                raise Refused('exclusive writer lock unavailable: ' + str(path)) from error
            yield
        finally:
            os.close(fd)


def check_store_idle(root):
    """Read a private SQLite snapshot; never open Store or the source DB in SQLite.

    The real controller lock and operator-exclusive ownership cover the copy.
    Any leases (including expired ones) or unsafe/claimable cache consumers refuse.
    SQLite may recover/create sidecars ONLY in the private temporary copy.
    """
    relative = 'var/coastal/coordinator.sqlite'
    db = Path(root) / relative
    if not db.exists() and not db.is_symlink():
        return  # no Store has ever been installed (e.g. accepted held-only work)
    observed = {}
    with tempfile.TemporaryDirectory(prefix='coast-close-store-') as tmp:
        for suffix in ('', '-wal', '-shm', '-journal'):
            path = Path(str(db) + suffix)
            if not path.exists() and not path.is_symlink():
                continue
            ident, st = observe(root, relative + suffix)
            require(st.st_nlink == 1, 'Store snapshot hardlink alias')
            ref = dict(root_id='queue:snapshot', **ident)
            raw = Resolver({'queue:snapshot': str(root)}, allowed_root_ids={'queue:snapshot'}).read(ref)
            (Path(tmp) / ('coordinator.sqlite' + suffix)).write_bytes(raw)
            observed[suffix] = (ident, st.st_dev, st.st_ino, st.st_mtime_ns)
        for suffix, expected in observed.items():
            ident, st = observe(root, relative + suffix)
            require((ident, st.st_dev, st.st_ino, st.st_mtime_ns) == expected, 'Store changed during quiescence preflight')
        try:
            db_copy = sqlite3.connect(str(Path(tmp) / 'coordinator.sqlite'))
            try:
                db_copy.execute('PRAGMA query_only=ON')
                require(not db_copy.execute('SELECT 1 FROM leases LIMIT 1').fetchone(),
                        'leases present (expired or unexpired); attended recovery required')
                for state, stage in db_copy.execute('SELECT state, stage FROM jobs'):
                    require(state in {'queued', 'done', 'held', 'failed_terminal', 'cancelled'},
                            'active or unsafe cache consumer state: ' + str(state))
                    require(state != 'queued' or stage == 'render', 'pending admission/cache consumer: ' + str(stage))
            finally:
                db_copy.close()
        except sqlite3.Error as error:
            raise Refused('unclassifiable Store snapshot: ' + str(error)) from error


@contextmanager
def quiescent(root):
    """Existing PC9 ownership assertion excludes other writers/admissions.

    Locks alone cannot exclude uncooperative writers; the operator must supply
    the SAME assertion as bridge_run. Never infer exclusive ownership from idle.
    """
    root = Path(root)
    require(os.environ.get('COAST_EXCLUSIVE_WRITER') == str(root),
            'current operator exclusive writer assertion absent (controllers/admissions/consumers)')
    controller = root / 'var/coastal'
    with directory_fd(root) as top:
        parent = os.dup(top)
        try:
            for part in ('var', 'coastal'):
                try:
                    os.mkdir(part, 0o700, dir_fd=parent)
                except FileExistsError:
                    pass
                child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
                os.close(parent)
                parent = child
        finally:
            os.close(parent)
    with exclusive_lock(controller / 'coordinator.lock'), exclusive_lock(root / 'close.lock'):
        check_store_idle(root)
        yield


def archive_metrics(manifest):
    """Logical unique-byte categories, not physical disk allocation or throughput."""
    buckets = {k: {} for k in ('raw_equivalent', 'derived', 'products', 'metadata')}
    for item in manifest['files']:
        src, dst = item['source_ref'], item['retained_ref']
        if src['path'].startswith('cache/'):
            category = 'raw_equivalent' if dst['root_id'].startswith('raw:') else 'derived'
        else:
            category = 'products' if src['path'].startswith('var/coastal/jobs/') else 'metadata'
        buckets[category][(dst['root_id'], dst['path'], dst['sha256'], dst['bytes'])] = dst['bytes']
    return dict(schema='coast-close-metrics-v1',
                archived_bytes={k: sum(v.values()) for k, v in buckets.items()},
                proposed_release_bytes=sum(c['size'] for c in manifest['cache_candidates']),
                peak_hot_cache=dict(status='unavailable', bytes=None,
                                    reason='No campaign-wide high-water telemetry is pinned; close-time candidates are not a historical peak.'))


def selected_verdicts(rows):
    """Latest verdict row per plan, in plan_sha256 order."""
    latest = {}
    for row in rows:
        if row['kind'] != 'verdict':
            continue
        order = (row['review_round'], row['attempt'], row['seq'])
        current = latest.get(row['plan_sha256'])
        if current is None or order > (current['review_round'], current['attempt'], current['seq']):
            latest[row['plan_sha256']] = row
    return [latest[k] for k in sorted(latest)]


def check_inventory(resolver, campaign, rows):
    """Frozen inventory closure (rev4 4.2): every plan's latest verdict is accept,
    and every intended window is map_done or held in an accepted population."""
    require(not any(r['kind'] == 'archived' for r in rows), 'segment already has an archived row; corrections need a new close')
    selected = selected_verdicts(rows)
    require(selected, 'no verdict rows: inventory is pending')
    covered, unfinished = set(), set()
    for row in selected:
        require(row['verdict'] == 'accept', 'latest verdict for plan ' + row['plan_id'] + ' is ' + row['verdict'] + ', not accept')
        require(row['campaign_segment_id'] == campaign['campaign_segment_id'], 'verdict row belongs to another campaign segment')
        verdict = loads(resolver.read(row['verdict_file']))
        population = verdict['population']
        require(population is not None, 'accepted verdict lacks a population')
        covered |= set(population['map_done']) | set(population['held'])
        unfinished |= set(population['unfinished'])
    intended = set(campaign['intended_windows'])
    require(intended <= covered, 'intended windows not closed by an accepted verdict: ' + ','.join(sorted(intended - covered)))
    require(not (intended & unfinished), 'unfinished intended windows remain')
    return selected


def execution_receipts(graph, head, lookup):
    """coast-native-execution-v1 documents for every stage result the graph
    reached. job.json/logs are bound by the shared native_execution identity
    checks (job/result identity, lease path, owned outputs), not trusted."""
    results = sorted({key[0] for key in graph.verified if key[2] == STAGE_RESULT})
    receipts = []
    for key in results:
        result = loads(key)
        require(result['path'].endswith('/output/result.json'), 'stage result outside its job output directory')
        directory = result['path'].removesuffix('/output/result.json')
        job = lookup(result['root_id'], directory + '/job.json')
        logs = [lookup(result['root_id'], directory + '/' + name) for name in ('stdout.log', 'stderr.log')]
        receipts.append(dict(schema='coast-native-execution-v1', **head, job=job, result=result, logs=logs))
    return receipts


def traverse(resolver, documents, *, root_id, envelopes, head, lookup):
    """Validate root documents and derived execution receipts in one graph."""
    graph = GraphValidator(resolver, raw_provenance=envelopes)
    for document in documents:
        graph.document(document, root_id=root_id)
    for receipt in execution_receipts(graph, head, lookup):
        graph.document(receipt, root_id=root_id)
    return graph


def excluded(ref):
    parts = ref['path'].split('/')
    return 'runner' in parts or parts[-1].endswith(('.lease', '.sqlite', '.sqlite-wal', '.sqlite-shm', '.lock'))


def retained_path(ref):
    root_id, path = ref['root_id'], ref['path']
    if root_id.startswith('repo:'):
        return 'config/' + root_id.split(':', 1)[1] + '/' + path
    if path.split('/')[0] == 'cache':
        return 'inputs/' + ref['sha256'] + '/' + path.split('/')[-1]
    return 'queue/' + root_id.split(':', 1)[1] + '/' + path


def write_retained(archive_root, relative, raw):
    parts = relative_parts(relative)
    with directory_fd(archive_root) as top:
        parent = os.dup(top)
        try:
            for part in parts[:-1]:
                try:
                    os.mkdir(part, 0o700, dir_fd=parent)
                except FileExistsError:
                    pass
                child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
                os.close(parent)
                parent = child
            fd = os.open(parts[-1], os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=parent)
            try:
                view = memoryview(raw)
                while view:
                    size = os.write(fd, view)
                    require(size > 0, 'short retained-file write')
                    view = view[size:]
                os.fsync(fd)
                os.fsync(parent)
            finally:
                os.close(fd)
        finally:
            os.close(parent)


def archive_ref(inner, archive_id, relative):
    ident, _ = observe(inner.bindings[archive_id], relative)
    ref = dict(root_id=archive_id, **ident)
    inner.read(ref, retain=False)
    return ref


def verify_closed(inner, *, archive_id, original_queue_roots, original_raw_roots):
    """Archive-only verification; returns (manifest, manifest_ref, snapshots, graph).

    Reads ONLY archive/raw bindings in ``inner``. Refuses on any chain, pin,
    inventory, verdict, mapping or graph failure.
    """
    manifest_ref = archive_ref(inner, archive_id, MANIFEST)
    manifest = loads(inner.read(manifest_ref))
    validate_schema(manifest)
    _consistency(manifest)
    require(manifest['schema'] == 'coast-archive-manifest-v1', 'not an archive manifest')
    queue_id = 'queue:' + manifest['campaign_segment_id']
    require(queue_id in original_queue_roots, 'missing original queue root for the campaign segment')
    require(archive_id == 'archive:' + manifest['campaign_segment_id'] + ':' + manifest['close_id'], 'archive root id differs from manifest close')
    segment_ref = archive_ref(inner, archive_id, SEGMENT_SNAPSHOT)
    campaign_ref = archive_ref(inner, archive_id, CAMPAIGN_SNAPSHOT)
    segment_raw, segment_rows = inner.read(segment_ref), None
    try:
        segment_rows = coast_ledger.verify_bytes(segment_raw)
        campaign_raw = inner.read(campaign_ref)
        campaign_rows = coast_ledger.verify_bytes(campaign_raw)
    except ValueError as error:
        raise Refused('ledger snapshot chain invalid: ' + str(error)) from error
    require(segment_rows and segment_rows[-1]['kind'] == 'archived' and segment_rows[-1]['close_id'] == manifest['close_id'],
            'segment snapshot must end with this close archived row')
    archived = segment_rows[-1]
    archived_line = segment_raw.splitlines(keepends=True)[-1]
    require(archived['manifest'] == manifest_ref, 'archived row does not pin this manifest')
    lines = segment_raw.splitlines(keepends=True)
    previous = sha256(lines[-2]) if len(lines) > 1 else coast_ledger.GENESIS
    require(previous == manifest['original_segment_tip_sha256'] == archived['previous_segment_tip_sha256'],
            'segment ledger tip changed between manifest and archived row')
    require(campaign_rows and campaign_rows[-1]['kind'] == 'archived' and campaign_rows[-1]['segment_row_sha256'] == sha256(archived_line),
            'campaign snapshot must end with the index of this archived row')
    clines = campaign_raw.splitlines(keepends=True)
    cprevious = sha256(clines[-2]) if len(clines) > 1 else coast_ledger.GENESIS
    require(cprevious == manifest['original_campaign_tip_sha256'] == archived['previous_campaign_tip_sha256'],
            'campaign ledger tip changed between manifest and archived row')
    resolver = ArchiveResolver(inner, manifest['files'], original_queue_roots=original_queue_roots,
                               original_raw_roots=original_raw_roots)
    campaign = loads(resolver.read(manifest['inventory']))
    validate_schema(campaign)
    require(campaign['schema'] == 'coast-campaign-v1' and campaign['campaign_segment_id'] == manifest['campaign_segment_id'],
            'inventory is not this campaign segment')
    selected = check_inventory(resolver, campaign, segment_rows[:-1])
    require([r['verdict_file'] for r in selected] == manifest['selected_verdicts'], 'manifest selected verdicts differ from latest ledger verdicts')
    envelopes = collect_envelopes(resolver, segment_rows)
    by_path = {}
    for item in manifest['files']:
        by_path.setdefault((item['source_ref']['root_id'], item['source_ref']['path']), []).append(item['source_ref'])
    def lookup(root_id, path):
        found = by_path.get((root_id, path), [])
        require(len(found) == 1, 'missing or ambiguous retained execution file: ' + path)
        return found[0]
    head = {k: manifest[k] for k in HEADER}
    try:
        graph = traverse(resolver, [campaign] + segment_rows + campaign_rows, root_id=queue_id,
                         envelopes=envelopes, head=head, lookup=lookup)
    except Refused:
        raise
    except (ValueError, KeyError, TypeError, OSError) as error:
        raise Refused('archive-only graph closure failed: ' + str(error)) from error
    return dict(manifest=manifest, manifest_ref=manifest_ref, segment_ref=segment_ref, campaign_ref=campaign_ref,
                segment_tip=sha256(lines[-1]), campaign_tip=sha256(clines[-1]), resolver=resolver, graph=graph,
                queue_id=queue_id, envelopes=envelopes)


def release_candidates(manifest):
    table = {canonical(i['source_ref']): i['retained_ref'] for i in manifest['files']}
    return [dict(source_ref=c['source_ref'], raw_or_retained=table[canonical(c['source_ref'])],
                 device=c['device'], inode=c['inode'], size=c['size'], mtime_ns=c['mtime_ns'])
            for c in manifest['cache_candidates']]


def finish(main):
    try:
        return main()
    except (Refused, ValueError, OSError, KeyError, TypeError) as error:
        print('REFUSED: ' + str(error), file=sys.stderr)
        return 3
