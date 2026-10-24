"""B1d coast-segment-close: archive -> archive-only verify -> operator release.

Owned synthetic temp trees only (pytest tmp_path); no real archive, raw mirror,
hot cache or network. The review chain is the real B1c sign-off fixture
(r1 must_fix -> r2 accept) over a real producer-bound admission graph whose
cached source is byte-identical to its raw mirror copy.
"""
import copy
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from tests._support import ROOT
from tests.gis.test_coast_sign_off_graph import Cycle

pytestmark = pytest.mark.gis
SCRIPTS = ROOT / 'skills/coast-segment-close/scripts'
sys.path.insert(0, str(SCRIPTS))
import close_common  # noqa: E402
import archive_segment  # noqa: E402
import verify_archive  # noqa: E402
import release_hot_cache  # noqa: E402

refs = close_common
validator = sys.modules['validate_coast_receipt']
ledger_module = close_common.coast_ledger
HEAD = dict(created_utc='2026-10-23T00:00:00Z', author_profile='synthetic-closer', author_model='synthetic-closer-model',
            card_id='t_11ed6417', code_commit='5' * 40, skill_commit='5' * 40)
QUEUE = 'queue:synthetic'
ARCHIVE = 'archive:synthetic:close01'


class Closed:
    def __init__(self, tmp, *, accept=True):
        c = Cycle(tmp).round(('flag',))
        assert c.open() == 0
        c.write(c.decisions('must_fix', [True]))
        c.round(('pass',), number=2)
        assert c.open() == 0
        c.write(c.decisions('accept' if accept else 'must_fix', None if accept else [True]))
        self.c = c
        self.tmp = tmp
        self.queue = c.queue
        self.raw = Path(c.bindings['raw:campaign'])
        self.archive = tmp / 'archive-root' / 'synthetic' / 'close01'
        self.archive.mkdir(parents=True)
        self.bindings = dict(c.bindings, **{ARCHIVE: str(self.archive)})
        self.ledger = self.queue / 'ledger.jsonl'
        self.campaign_ledger = self.queue.parent / 'campaign-ledger.jsonl'
        admission = c.instances['admission']
        self.campaign_path = self.queue / admission['campaign']['path']
        self.header = tmp / 'header.json'
        self.header.write_bytes(refs.canonical(HEAD))

    def resolver(self):
        return refs.Resolver(self.bindings, allowed_root_ids=set(self.bindings))

    def archive_now(self):
        return archive_segment.archive(self.resolver(), campaign_path=self.campaign_path, ledger=self.ledger,
                                       campaign_ledger=self.campaign_ledger, head=HEAD, reserve_bytes=0, close_id='close01')

    def archive_only(self):
        only = {ARCHIVE: str(self.archive), 'raw:campaign': str(self.raw)}
        return refs.Resolver(only, allowed_root_ids=set(only))

    def verify(self):
        return verify_archive.verify(self.archive_only(), original_queue_roots={QUEUE: str(self.queue)},
                                     original_raw_roots=None, head=HEAD)

    def write_list(self):
        release = self.verify()
        out = self.queue / 'close/close01/release-list.json'
        out.parent.mkdir(parents=True)
        raw = refs.write_once(out, release)
        return out, refs.sha256(raw), release

    def cli(self, script, *args):
        return subprocess.run([sys.executable, str(ROOT / 'tests/coast_checkout_cli.py'), str(SCRIPTS / script), *map(str, args)],
                              capture_output=True, text=True)


@pytest.fixture
def closed(tmp_path):
    return Closed(tmp_path)


def manifest_of(f):
    return refs.loads((f.archive / close_common.MANIFEST).read_bytes())


def test_archive_order_manifest_and_archived_row(closed):
    f = closed
    before = f.ledger.read_bytes()
    raw_before = {p: p.read_bytes() for p in f.raw.rglob('*') if p.is_file()}
    result = f.archive_now()
    manifest = manifest_of(f)
    files = manifest['files']
    # Every superseded r1 and selected r2 review file is retained, with exact bytes.
    paths = {i['source_ref']['path'] for i in files}
    assert any('review/r01/' in p for p in paths) and any('review/r02/' in p for p in paths)
    for item in files:
        assert item['source_ref']['sha256'] == item['retained_ref']['sha256']
        assert not item['source_ref']['path'].endswith(('ledger.jsonl', close_common.MANIFEST))
    # Cached original identical to the raw mirror maps to raw, never copied.
    cached = [i for i in files if i['source_ref']['path'].startswith('cache/')]
    assert cached and all(i['retained_ref']['root_id'] == 'raw:campaign' for i in cached)
    assert [c['source_ref'] for c in manifest['cache_candidates']] == [i['source_ref'] for i in cached]
    assert manifest['selected_verdicts'][0]['path'].endswith('r02/a01/tier3/verdict.json')
    # Archived row appended last, pinning the manifest; snapshots taken after it.
    rows = ledger_module.verify(f.ledger)
    assert f.ledger.read_bytes().startswith(before)
    assert rows[-1]['kind'] == 'archived' and rows[-1]['manifest'] == result['manifest']
    assert rows[-1]['previous_segment_tip_sha256'] == manifest['original_segment_tip_sha256']
    assert (f.archive / close_common.SEGMENT_SNAPSHOT).read_bytes() == f.ledger.read_bytes()
    assert (f.archive / close_common.CAMPAIGN_SNAPSHOT).read_bytes() == f.campaign_ledger.read_bytes()
    assert raw_before == {p: p.read_bytes() for p in f.raw.rglob('*') if p.is_file()}
    # Every emitted JSON validates with the shared validator.
    validator.validate(manifest, f.resolver(), root_id=ARCHIVE)
    for row in rows + ledger_module.verify(f.campaign_ledger):
        validator.validate(row, f.resolver(), root_id=QUEUE)


def test_archive_refuses_second_close_and_nonempty_destination(closed):
    f = closed
    f.archive_now()
    with pytest.raises(close_common.Refused, match='already has an archived row|new and empty'):
        f.archive_now()


def test_archive_refuses_unaccepted_latest_verdict(tmp_path):
    f = Closed(tmp_path, accept=False)
    before = f.ledger.read_bytes()
    with pytest.raises(close_common.Refused, match='is must_fix, not accept'):
        f.archive_now()
    assert f.ledger.read_bytes() == before
    assert not any(f.archive.iterdir())


def test_archive_refuses_pending_inventory_window(closed):
    f = closed
    campaign = refs.loads(f.campaign_path.read_bytes())
    campaign['intended_windows'] = campaign['intended_windows'] + ['source/missing#' + '0' * 64 + '#9']
    pending = f.queue / 'campaign-pending.json'
    pending.write_bytes(refs.canonical(campaign))
    with pytest.raises(close_common.Refused, match='intended windows not closed'):
        archive_segment.archive(f.resolver(), campaign_path=pending, ledger=f.ledger, campaign_ledger=f.campaign_ledger,
                                head=HEAD, reserve_bytes=0, close_id='close01')


def test_archive_refuses_insufficient_capacity(closed):
    f = closed
    with pytest.raises(close_common.Refused, match='insufficient archive capacity'):
        archive_segment.archive(f.resolver(), campaign_path=f.campaign_path, ledger=f.ledger, campaign_ledger=f.campaign_ledger,
                                head=HEAD, reserve_bytes=10**18, close_id='close01')
    assert ledger_module.verify(f.ledger)[-1]['kind'] == 'verdict'


def test_verify_cli_with_hot_tree_unavailable(closed):
    f = closed
    f.archive_now()
    only = {ARCHIVE: str(f.archive), 'raw:campaign': str(f.raw)}
    roots = f.tmp / 'archive-roots.json'
    roots.write_bytes(refs.canonical(only))
    origins = f.tmp / 'origins.json'
    origins.write_bytes(refs.canonical({QUEUE: str(f.queue)}))
    out = f.tmp / 'out' / 'release-list.json'
    out.parent.mkdir()
    hidden = f.queue.with_name('queue-hidden')
    f.queue.rename(hidden)  # the ENTIRE hot tree is unreadable during verification
    try:
        done = f.cli('verify_archive.py', '--roots', roots, '--allowed-root-id', ARCHIVE, '--allowed-root-id', 'raw:campaign',
                     '--archive', f.archive, '--forbid', f.queue, '--original-queue-roots', origins, '--header', f.header, '--out', out)
    finally:
        hidden.rename(f.queue)
    assert done.returncode == 0, done.stderr
    printed = json.loads(done.stdout)
    assert printed['sha256'] == refs.sha256(out.read_bytes()) and printed['authorization'] is False
    release = refs.loads(out.read_bytes())
    assert release['total_files'] == len(manifest_of(f)['cache_candidates']) >= 1
    validator.validate(release, f.resolver(), root_id=QUEUE)


def test_verify_refuses_forbidden_overlap(closed):
    f = closed
    f.archive_now()
    roots = f.tmp / 'bad-roots.json'
    roots.write_bytes(refs.canonical({ARCHIVE: str(f.archive), 'raw:campaign': str(f.raw), QUEUE: str(f.queue)}))
    done = f.cli('verify_archive.py', '--roots', roots, '--allowed-root-id', ARCHIVE, '--allowed-root-id', 'raw:campaign',
                 '--allowed-root-id', QUEUE, '--archive', f.archive, '--forbid', f.queue,
                 '--original-queue-roots', f.header, '--header', f.header, '--out', f.tmp / 'never.json')
    assert done.returncode == 3 and 'archive/raw only' in done.stderr
    assert not (f.tmp / 'never.json').exists()


def deleted_product(f):
    manifest = manifest_of(f)
    target = next(i for i in manifest['files'] if i['retained_ref']['root_id'] == ARCHIVE
                  and i['source_ref']['path'].endswith('tier3/verdict.json'))
    (f.archive / target['retained_ref']['path']).unlink()


def latest_must_fix(f):
    # A later must_fix verdict row for the same plan (r3) becomes the latest.
    rows = ledger_module.verify(f.archive / close_common.SEGMENT_SNAPSHOT)
    row = {k: v for k, v in rows[1].items() if k not in ('seq', 'prev_row_sha256')}
    row.update(review_round=3, verdict='must_fix')
    raw = (f.archive / close_common.SEGMENT_SNAPSHOT).read_bytes()
    lines = raw.splitlines(keepends=True)
    archived = lines.pop()
    row = dict(row, seq=len(lines) + 1, prev_row_sha256=refs.sha256(lines[-1]))
    lines.append(refs.canonical(row))
    archived_row = dict(refs.loads(archived), seq=len(lines) + 1, prev_row_sha256=refs.sha256(lines[-1]))
    lines.append(refs.canonical(archived_row))
    (f.archive / close_common.SEGMENT_SNAPSHOT).write_bytes(b''.join(lines))


def altered_ledger_line(f):
    path = f.archive / close_common.SEGMENT_SNAPSHOT
    raw = path.read_bytes()
    path.write_bytes(raw.replace(b'"verdict":"must_fix"', b'"verdict":"accept"', 1))


def unmapped_reference(f):
    manifest_path = f.archive / close_common.MANIFEST
    manifest = manifest_of(f)
    manifest['files'] = [i for i in manifest['files'] if not i['source_ref']['path'].endswith('tier1/flagged-windows.json')]
    os.chmod(manifest_path, 0o600)
    manifest_path.write_bytes(refs.canonical(manifest))


def missing_raw(f):
    for path in f.raw.rglob('*'):
        if path.is_file():
            path.rename(path.with_name(path.name + '.moved'))
            return


@pytest.mark.parametrize('mutate,reason', [
    (deleted_product, 'reference|No such file'),
    (latest_must_fix, 'must_fix, not accept|archived row|chain|snapshot'),
    (altered_ledger_line, 'chain invalid'),
    (unmapped_reference, 'unmapped reference|archived row does not pin'),
    (missing_raw, 'No such file|reference'),
])
def test_verify_refuses_and_writes_no_list(closed, mutate, reason):
    f = closed
    f.archive_now()
    f.verify()  # positive control on the same archive
    mutate(f)
    with pytest.raises((close_common.Refused, ValueError, OSError), match=reason):
        f.verify()


def test_latest_must_fix_refusal_is_the_verdict_gate(closed):
    """Isolate the gate: chain and pins stay valid, only the latest verdict differs."""
    f = closed
    f.archive_now()
    latest_must_fix(f)
    rows = ledger_module.verify(f.archive / close_common.SEGMENT_SNAPSHOT)  # chain still valid
    selected = close_common.selected_verdicts(rows[:-1])
    assert selected[0]['verdict'] == 'must_fix'
    with pytest.raises(close_common.Refused, match='is must_fix, not accept'):
        close_common.check_inventory(f.resolver(), refs.loads(f.campaign_path.read_bytes()), rows[:-1])


# ---------------------------------------------------------------- release

def release_args(f, out, digest, *, execute=True):
    return dict(list_path=out, expected_sha256=digest, execute=execute, ledger=f.ledger,
                campaign_ledger=f.campaign_ledger, original_raw_roots=None, head=HEAD)


def cache_files(f):
    return sorted(p for p in (f.queue / 'cache').rglob('*') if p.is_file())


def test_release_refuses_without_execute(closed):
    f = closed
    f.archive_now()
    out, digest, _ = f.write_list()
    before = cache_files(f)
    roots = f.tmp / 'hot-roots.json'
    roots.write_bytes(refs.canonical(f.bindings))
    done = f.cli('release_hot_cache.py', '--roots', roots, *[a for k in f.bindings for a in ('--allowed-root-id', k)],
                 '--list', out, '--expected-list-sha256', digest, '--ledger', f.ledger, '--campaign-ledger', f.campaign_ledger,
                 '--header', f.header)
    assert done.returncode == 3 and 'without --execute' in done.stderr
    assert cache_files(f) == before and not out.with_name('release-receipt.json').exists()


def outside_cache(f, release):
    release['candidates'][0]['source_ref'] = dict(release['candidates'][0]['source_ref'], path='plans/plan01/plan.json')


def changed_cache(f, release):
    path = f.queue / release['candidates'][0]['source_ref']['path']
    os.utime(path, ns=(1, 1))


def hardlinked_cache(f, release):
    path = f.queue / release['candidates'][0]['source_ref']['path']
    os.link(path, f.queue / 'alias.bin')


def symlinked_parent(f, release):
    path = f.queue / release['candidates'][0]['source_ref']['path']
    real = path.parent.with_name(path.parent.name + '-real')
    path.parent.rename(real)
    path.parent.symlink_to(real, target_is_directory=True)


def failed_observation(f, release):
    release['validation_observations'][0]['observed'] = '0' * 64


def ledger_written_after_close(f, release):
    # A chain-VALID later write (new idempotency key, correct seq and previous-line
    # hash), so the refusal must come from the frozen-tip check, not chain repair.
    raw = f.ledger.read_bytes()
    lines = raw.splitlines(keepends=True)
    row = next(r for r in map(json.loads, lines) if r['kind'] == 'verdict')
    row = dict(row, seq=len(lines) + 1, prev_row_sha256=refs.sha256(lines[-1]), attempt=row['attempt'] + 7)
    f.ledger.write_bytes(raw + refs.canonical(row))
    ledger_module.verify(f.ledger)


@pytest.mark.parametrize('mutate,reason', [
    (outside_cache, 'differ from the verified|outside <segment>/cache/'),
    (changed_cache, 'identity changed'),
    (hardlinked_cache, 'hardlink'),
    (symlinked_parent, 'Not a directory|Too many levels|symlink|ELOOP'),
    (failed_observation, 'failed observation'),
    (ledger_written_after_close, 'hot ledger changed after close'),
])
def test_release_preflight_refusals_keep_every_cache_file(closed, mutate, reason):
    f = closed
    f.archive_now()
    out, digest, release = f.write_list()
    mutated = copy.deepcopy(release)
    mutate(f, mutated)
    if mutated != release:  # list edited -> re-post the SHA of the edited list
        out.unlink()
        raw = refs.write_once(out, mutated)
        digest = refs.sha256(raw)
    present = {p: p.stat().st_ino for p in (f.queue / 'cache').rglob('*') if p.is_file() or p.is_symlink()}
    with pytest.raises((close_common.Refused, ValueError, OSError), match=reason):
        release_hot_cache.release(f.bindings, **release_args(f, out, digest))
    assert all(p.exists() for p in present)
    assert not out.with_name('release-receipt.json').exists()


def test_release_refuses_wrong_posted_sha(closed):
    f = closed
    f.archive_now()
    out, digest, _ = f.write_list()
    with pytest.raises(close_common.Refused, match='independently posted SHA'):
        release_hot_cache.release(f.bindings, **release_args(f, out, '0' * 64))
    assert cache_files(f)


def test_release_unlinks_listed_files_and_writes_receipt(closed):
    f = closed
    f.archive_now()
    out, digest, release = f.write_list()
    listed = {f.queue / c['source_ref']['path'] for c in release['candidates']}
    others = {p: p.read_bytes() for p in f.queue.rglob('*') if p.is_file() and p not in listed}
    raw_before = {p: p.read_bytes() for p in f.raw.rglob('*') if p.is_file()}
    archive_before = {p: p.read_bytes() for p in f.archive.rglob('*') if p.is_file()}
    receipt, target = release_hot_cache.release(f.bindings, **release_args(f, out, digest))
    assert receipt['status'] == 'complete' and receipt['failure'] is None and receipt['remaining'] == []
    assert {f.queue / r['path'] for r in receipt['released']} == listed
    assert not any(p.exists() for p in listed)
    assert all(p.parent.is_dir() for p in listed)  # files only, never directories
    assert others == {p: p.read_bytes() for p in others}
    assert raw_before == {p: p.read_bytes() for p in f.raw.rglob('*') if p.is_file()}
    assert archive_before == {p: p.read_bytes() for p in f.archive.rglob('*') if p.is_file()}
    schema = refs.loads((ROOT / 'skills/coast-segment-close/schemas/release-receipt.schema.json').read_bytes())
    from jsonschema import Draft202012Validator
    Draft202012Validator(schema).validate(refs.loads(target.read_bytes()))


def test_release_reports_honest_partial(closed, monkeypatch):
    f = closed
    f.archive_now()
    out, digest, release = f.write_list()
    def broken(root, candidate):
        raise OSError('synthetic I/O failure after preflight')
    monkeypatch.setattr(release_hot_cache, 'unlink_checked', broken)
    receipt, _ = release_hot_cache.release(f.bindings, **release_args(f, out, digest))
    assert receipt['status'] == 'partial' and receipt['released'] == []
    assert receipt['failure']['error'] == 'synthetic I/O failure after preflight'
    assert len(receipt['remaining']) == len(release['candidates'])
    assert cache_files(f)
