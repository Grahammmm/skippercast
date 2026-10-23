"""Offline integration through the real policy client; never contact source hosts."""
import hashlib
import io
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from skippercast.coastal import prefetch as p
from skippercast.http import DisallowedHost, Session

URL = 'https://data.ngdc.noaa.gov/survey.bag'
DATA = b'abcdefghij'


@pytest.fixture(autouse=True)
def isolated_retry_state(tmp_path, monkeypatch):
    monkeypatch.setattr(p, 'RETRY_STATE', tmp_path / 'shared/retry-state.json')


class Reply(io.BytesIO):
    def __init__(self, status=200, body=b'', headers=None):
        super().__init__(body)
        self.status = status
        self.headers = headers or {}

    def getheaders(self):
        return list(self.headers.items())

    def getheader(self, name):
        return next((v for k, v in self.headers.items() if k.lower() == name.lower()), None)


class Server:
    def __init__(self, *, ignore_range=False, status=None, validator='"v1"', bad_range=False):
        self.calls = []
        self.ignore_range, self.status, self.validator, self.bad_range = ignore_range, status, validator, bad_range
        self.fail_at = None
        self.redirect = None
        self.active = self.max_active = 0

    def factory(self, host, port, addresses, **kwargs):
        server = self
        class Connection:
            def request(self, method, target, headers):
                self.method, self.headers = method, headers
                server.calls.append((host, method, target, headers))
                server.active += 1
                server.max_active = max(server.max_active, server.active)

            def getresponse(self):
                headers = {'Content-Length': str(len(DATA))}
                if server.validator:
                    headers['ETag'] = server.validator
                if server.redirect:
                    return Reply(302, headers={'Location': server.redirect})
                if server.fail_at and len(server.calls) == server.fail_at:
                    raise OSError('synthetic disconnect')
                if server.status:
                    return Reply(server.status, headers={'Retry-After': '60'})
                if self.method == 'HEAD':
                    return Reply(headers=headers)
                if server.ignore_range:
                    return Reply(body=DATA, headers=headers)
                begin, end = map(int, self.headers['Range'].removeprefix('bytes=').split('-'))
                body = DATA[begin:end + 1]
                headers['Content-Length'] = str(len(body))
                headers['Content-Range'] = f'bytes {begin}-{end}/{len(DATA)}' if not server.bad_range else 'bytes 0-0/1'
                return Reply(206, body, headers)

            def close(self):
                server.active -= 1
        return Connection()

    def session(self):
        return p.TransferSession(allowed_hosts=['data.ngdc.noaa.gov', 'pubs.usgs.gov'],
                       resolver=lambda *a, **k: [(2, 1, 6, '', ('93.184.216.34', 443))],
                       connection_factory=self.factory, proxies={}, attempts=1,
                       user_agent='SkipperCast/test coast-campaign-raw-prefetch')


def row(**kwargs):
    return {'source': 'noaa-nos', 'url': URL, 'segments': ['C1'],
            'bytes': len(DATA), 'sha256': hashlib.sha256(DATA).hexdigest(),
            'licence': 'Public domain; not for navigation', **kwargs}


def plan(*rows, unresolved=None):
    return {'schema_version': 1, 'files': list(rows or [row()]), 'unresolved': unresolved or []}


def runner(tmp_path, server, data=None, **kwargs):
    mount = tmp_path / 'disk'
    mount.mkdir(exist_ok=True)
    return p.Prefetch(data or plan(), server.session(), root=mount / 'raw', mount=mount,
                      mirror=tmp_path / 'mirror', status=tmp_path / 'status.json',
                      lock_dir=tmp_path / 'locks', clock=lambda: 1000,
                      disk_usage=lambda _: SimpleNamespace(free=p.RESERVE + 10_000_000),
                      ismount=lambda _: True, **kwargs)


def receipt(run):
    return json.loads((run.root / 'noaa-nos/manifest.jsonl').read_text())


def load(tmp_path, data, session=None):
    path = tmp_path / 'plan.json'
    path.write_text(json.dumps(data))
    return p.load_plan(path, session or Server().session())


def test_real_session_ranges_mirrors_status_and_verified_skip(tmp_path, monkeypatch):
    monkeypatch.setattr(p, 'RANGE_BYTES', 4)
    server = Server()
    run = runner(tmp_path, server)
    assert run.run() == 0
    assert server.max_active == 1
    assert [c[3].get('Range') for c in server.calls] == [None, 'bytes=0-3', 'bytes=4-7', 'bytes=8-9']
    manifest = receipt(run)
    assert Path(manifest['path']).read_bytes() == DATA
    assert manifest['bytes'] == len(DATA) and manifest['sha256'] == hashlib.sha256(DATA).hexdigest()
    assert manifest['etag'] == '"v1"' and manifest['fetched_at'] and manifest['licence']
    assert (run.mirror / 'noaa-nos.jsonl').read_bytes() == (run.root / 'noaa-nos/manifest.jsonl').read_bytes()
    status = json.loads(run.status.read_text())
    assert status['state'] == 'complete'
    assert status['sources']['noaa-nos'] == {'files_done': 1, 'files_total': 1, 'bytes': 10, 'errors': []}
    server.calls.clear()
    (run.mirror / 'noaa-nos.jsonl').write_text('stale mirror')
    assert runner(tmp_path, server).run() == 0
    assert not server.calls
    assert json.loads((run.mirror / 'noaa-nos.jsonl').read_text()) == manifest


def test_interrupted_pass_resumes_after_persisted_cooldown(tmp_path, monkeypatch):
    monkeypatch.setattr(p, 'RANGE_BYTES', 4)
    server = Server()
    server.fail_at = 3
    run = runner(tmp_path, server)
    assert run.run() == 75
    partial = run.root / 'noaa-nos' / (p.filename(row()) + '.part')
    assert partial.read_bytes() == DATA[:4]
    server.calls.clear()
    server.fail_at = None
    assert runner(tmp_path, server).run() == 75
    assert not server.calls
    next_run = runner(tmp_path, server)
    next_run.clock = lambda: 2000
    assert next_run.run() == 0
    assert server.calls[1][3]['Range'] == 'bytes=4-7'
    assert Path(receipt(next_run)['path']).read_bytes() == DATA


def test_crash_during_append_recovers_only_verified_prefix(tmp_path, monkeypatch):
    monkeypatch.setattr(p, 'RANGE_BYTES', 4)
    server = Server()
    server.fail_at = 3
    run = runner(tmp_path, server)
    assert run.run() == 75
    partial = run.root / 'noaa-nos' / (p.filename(row()) + '.part')
    with partial.open('ab') as stream:
        stream.write(b'half-appended-chunk')
    server.fail_at = None
    run = runner(tmp_path, server)
    run.clock = lambda: 2000
    assert run.run() == 0
    assert Path(receipt(run)['path']).read_bytes() == DATA


@pytest.mark.parametrize('ignore_range,validator', [(True, '"v1"'), (False, None)])
def test_full_entity_fallback(tmp_path, monkeypatch, ignore_range, validator):
    monkeypatch.setattr(p, 'RANGE_BYTES', 4)
    server = Server(ignore_range=ignore_range, validator=validator)
    run = runner(tmp_path, server)
    assert run.run() == 0
    assert Path(receipt(run)['path']).read_bytes() == DATA
    assert len(server.calls) == 2


class Replaced(Server):
    """Serves `old` for the HEAD and first GET, then the publisher swaps in `new`."""

    def __init__(self, old, new):
        super().__init__()
        self.old, self.new = old, new

    def factory(self, host, port, addresses, **kwargs):
        server = self

        class Connection:
            def request(self, method, target, headers):
                self.method, self.headers = method, headers
                server.calls.append((host, method, target, headers))

            def getresponse(self):
                body, extra = server.old if len(server.calls) <= 2 else server.new
                headers = {'Content-Length': str(len(body)), **extra}
                if self.method == 'HEAD':
                    return Reply(headers=headers)
                begin, end = map(int, self.headers['Range'].removeprefix('bytes=').split('-'))
                part = body[begin:end + 1]
                return Reply(206, part, {**headers, 'Content-Length': str(len(part)),
                                         'Content-Range': f'bytes {begin}-{end}/{len(body)}'})

            def close(self):
                pass
        return Connection()


@pytest.mark.parametrize('old,new', [
    ({'ETag': 'W/"v1"', 'Last-Modified': 'Wed, 21 Oct 2026 07:28:00 GMT'},
     {'ETag': 'W/"v2"', 'Last-Modified': 'Wed, 21 Oct 2026 07:28:00 GMT'}),
    ({'Last-Modified': 'Wed, 21 Oct 2026 07:28:00 GMT'}, {'Last-Modified': 'Wed, 21 Oct 2026 07:28:00 GMT'}),
    ({}, {}),
])
def test_ranges_never_stitched_without_strong_etag(tmp_path, monkeypatch, old, new):
    # A weak ETag or Last-Modified (1 s resolution) is not byte identity: one full GET, never two versions.
    monkeypatch.setattr(p, 'RANGE_BYTES', 4)
    server = Replaced((b'AAAAAAAAAA', old), (b'BBBBBBBBBB', new))
    run = runner(tmp_path, server, plan(row(sha256=None)))
    assert run.run() == 0
    assert [c[3].get('Range') for c in server.calls] == [None, 'bytes=0-9']
    assert all('If-Range' not in c[3] for c in server.calls)
    assert Path(receipt(run)['path']).read_bytes() == b'AAAAAAAAAA'


@pytest.mark.parametrize('new', [{'ETag': '"v2"'}, {'ETag': '"v1"', 'Last-Modified': 'Thu, 22 Oct 2026 00:00:00 GMT'},
                                 {'ETag': 'W/"v1"'}])
def test_any_etag_or_last_modified_change_mid_transfer_holds(tmp_path, monkeypatch, new):
    monkeypatch.setattr(p, 'RANGE_BYTES', 4)
    old = {'ETag': '"v1"', 'Last-Modified': 'Wed, 21 Oct 2026 07:28:00 GMT'}
    server = Replaced((b'AAAAAAAAAA', old), (b'BBBBBBBBBB', new))
    run = runner(tmp_path, server, plan(row(sha256=None)))
    assert run.run() == 2
    assert not (run.root / 'noaa-nos' / p.filename(row())).exists()


@pytest.mark.parametrize('status,delay', [(429, 900), (500, 86400), (503, 86400), (502, 900), (599, 900)])
def test_http_failures_park_entire_host_across_restarts(tmp_path, status, delay):
    server = Server(status=status)
    data = plan(row(), row(url=URL + '?second'))
    run = runner(tmp_path, server, data)
    assert run.run() == 75
    assert len(server.calls) == 1
    retry = json.loads(run.retry_state.read_text())['data.ngdc.noaa.gov']
    assert retry['retry_at'] == 1000 + delay
    assert runner(tmp_path, server, data).run() == 75
    assert len(server.calls) == 1


def test_redirect_policy_refuses_unknown_and_parked_target(tmp_path):
    server = Server()
    server.redirect = 'https://evil.example/file'
    run = runner(tmp_path, server)
    assert run.run() == 2
    assert len(server.calls) == 1
    server.calls.clear()
    server.redirect = 'https://pubs.usgs.gov/file'
    p.atomic_json(run.mirror / 'retry-state.json', {'pubs.usgs.gov': {'retry_at': 3000}})
    assert runner(tmp_path, server).run() == 75
    assert len(server.calls) == 1


@pytest.mark.parametrize('change', ['checksum', 'range', 'size'])
def test_mismatch_never_promotes(tmp_path, change):
    server = Server(bad_range=change == 'range')
    record = row()
    if change == 'checksum':
        record['sha256'] = '0' * 64
    if change == 'size':
        record['bytes'] += 1
    run = runner(tmp_path, server, plan(record))
    assert run.run() == 2
    assert not (run.root / 'noaa-nos' / p.filename(record)).exists()
    assert not (run.root / 'noaa-nos/manifest.jsonl').read_text()


def test_disk_and_mount_stop_without_source_request(tmp_path):
    server = Server()
    run = runner(tmp_path, server)
    run.disk_usage = lambda _: SimpleNamespace(free=p.RESERVE - 1)
    with pytest.raises(p.CapacityError):
        run.run()
    assert not server.calls
    assert json.loads(run.status.read_text())['state'] == 'stopped'
    run.disk_usage = lambda _: SimpleNamespace(free=p.RESERVE + 100)
    run.ismount = lambda _: False
    with pytest.raises(p.CapacityError):
        run.run()
    assert not server.calls


def test_mid_transfer_capacity_stop_not_retried_or_parked(tmp_path):
    server = Server()
    run = runner(tmp_path, server)
    original = run.guard
    def guard(size=0):
        if size and len(server.calls) >= 2:
            raise p.CapacityError('synthetic reserve reached')
        return original(size)
    run.guard = guard
    with pytest.raises(p.CapacityError):
        run.run()
    assert len(server.calls) == 2
    assert not run.state


def test_checkpoint_atomic_replacement_preserves_disk_reserve(tmp_path):
    run = runner(tmp_path, Server())
    run.disk_usage = lambda _: SimpleNamespace(free=p.RESERVE + 1)
    path = run.root / 'checkpoint.json'
    with pytest.raises(p.CapacityError):
        run.checkpoint(path, {'bytes': 10})
    assert not path.exists()


def test_corrupted_final_preserved_and_not_retried(tmp_path):
    server = Server()
    run = runner(tmp_path, server)
    assert run.run() == 0
    final = Path(receipt(run)['path'])
    final.write_bytes(b'corrupted!')
    server.calls.clear()
    assert runner(tmp_path, server).run() == 2
    assert not server.calls and final.read_bytes() == b'corrupted!'


def test_lock_excludes_second_process_and_symlink_refused(tmp_path):
    server = Server()
    run = runner(tmp_path, server)
    with run.lock(), pytest.raises(p.Hold, match='Another prefetch'):
        runner(tmp_path, server).run()
    run.root.symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(p.Hold, match='Symlink'):
        run.run()
    assert not server.calls


def test_dry_run_deduplicates_shared_sources_in_campaign_order(tmp_path):
    data = plan(row(segments=['N7']), row(segments=['C2']),
                row(url=URL + '?other', segments=['C1'], bytes=None, sha256=None))
    checked = load(tmp_path, data)
    report = p.dry_run(checked)
    assert len(report['files']) == 2
    assert report['files'][1]['segments'] == ['C2', 'N7']
    assert report['segments']['C1']['total_bytes'] is None
    assert report['segments']['C2']['total_bytes'] == 10
    assert report['segments']['N7']['total_bytes'] == 0
    assert not (tmp_path / 'status.json').exists()


@pytest.mark.parametrize('update', [dict(source='../escape'), dict(source='UPPER'),
                                    dict(segments=['other']), dict(bytes=-1), dict(bytes=True),
                                    dict(sha256='invalid'), dict(licence=''),
                                    dict(url='http://data.ngdc.noaa.gov/a'),
                                    dict(url='https://evil.example/a'),
                                    dict(url='https://data.ngdc.noaa.gov/a#fragment')])
def test_bad_inventory_is_refused_before_io(tmp_path, update):
    with pytest.raises((p.Hold, DisallowedHost)):
        load(tmp_path, plan(row(**update)))


def test_duplicate_conflicting_hash_refused(tmp_path):
    with pytest.raises(p.Hold, match='Conflicting duplicate'):
        load(tmp_path, plan(row(), row(sha256='0' * 64)))


def test_empty_plan_cannot_report_complete(tmp_path):
    with pytest.raises(p.Hold, match='Empty inventory'):
        load(tmp_path, {'schema_version': 1, 'files': [], 'unresolved': []})


def test_incomplete_inventory_is_never_complete(tmp_path):
    server = Server()
    data = plan(unresolved=[{'source': 'gebco', 'reason': 'subset URL pending'}])
    run = runner(tmp_path, server, data)
    with pytest.raises(p.Hold, match='Inventory unresolved'):
        run.run()
    assert not server.calls
    assert run.run(allow_incomplete=True) == 2
    assert json.loads(run.status.read_text())['state'] == 'incomplete'
    assert not p.dry_run(data)['inventory_complete']


def test_metadata_preflight_fills_size_without_downloading(tmp_path):
    server = Server()
    run = runner(tmp_path, server, plan(row(bytes=None, sha256=None)))
    output = tmp_path / 'sized.json'
    assert run.probe_sizes(output) == 0
    result = json.loads(output.read_text())
    assert result['files'][0]['bytes'] == len(DATA)
    assert result['files'][0]['size_etag'] == '"v1"'
    assert [c[1] for c in server.calls] == ['HEAD']
    assert not run.root.exists()
    assert json.loads(run.status.read_text())['state'] == 'inventory-review-required'
    assert p.dry_run(result)['segments']['C1']['total_bytes'] == len(DATA)


def test_preflight_preserves_pin_and_records_mismatch(tmp_path):
    server = Server()
    run = runner(tmp_path, server, plan(row(bytes=100)))
    output = tmp_path / 'sized.json'
    assert run.probe_sizes(output) == 2
    result = json.loads(output.read_text())
    assert result['files'][0]['bytes'] == 100
    assert 'differs' in result['unresolved'][0]['reason']


@pytest.mark.parametrize('change', ['validator', 'corrupt-prefix', 'redirect'])
def test_resume_refuses_changed_identity_or_corrupt_partial(tmp_path, monkeypatch, change):
    monkeypatch.setattr(p, 'RANGE_BYTES', 4)
    server = Server()
    server.fail_at = 3
    run = runner(tmp_path, server)
    assert run.run() == 75
    partial = run.root / 'noaa-nos' / (p.filename(row()) + '.part')
    meta_path = partial.with_name(partial.name + '.json')
    if change == 'validator':
        server.validator = '"v2"'
    elif change == 'corrupt-prefix':
        partial.write_bytes(b'xxxx')
    else:
        meta = json.loads(meta_path.read_text())
        meta['final_url'] = 'https://pubs.usgs.gov/old-target'
        meta_path.write_text(json.dumps(meta))
    server.calls.clear()
    server.fail_at = None
    run = runner(tmp_path, server)
    run.clock = lambda: 2000
    before = partial.read_bytes()
    assert run.run() == 2
    assert [c[1] for c in server.calls] == ['HEAD']
    assert partial.read_bytes() == before


def test_retry_after_longer_than_default_is_not_capped(tmp_path):
    run = runner(tmp_path, Server())
    with pytest.raises(p.Parked):
        run.park('data.ngdc.noaa.gov', 'outage', 503, {'Retry-After': '172800'})
    assert run.state['data.ngdc.noaa.gov']['retry_at'] == 173800


def test_noaa_s3_outage_also_parks_until_next_day(tmp_path):
    run = runner(tmp_path, Server())
    host = 'noaa-ocs-nationalbathymetry-pds.s3.amazonaws.com'
    with pytest.raises(p.Parked):
        run.park(host, 'outage', 500)
    assert run.state[host]['retry_at'] == 87400


def test_large_error_body_is_never_read_or_buffered():
    class ErrorReply:
        status = 503
        def read(self, *args):
            raise AssertionError('must not read error body under a raw-file byte ceiling')
    assert p.TransferSession()._read(ErrorReply(), 10**12, None, None) == (b'', 0)


def test_cli_dry_run_is_network_free(tmp_path, monkeypatch, capsys):
    path = tmp_path / 'plan.json'
    path.write_text(json.dumps(plan()))
    def no_network(*args, **kwargs):
        raise AssertionError('dry-run contacted source')
    monkeypatch.setattr(Session, 'request', no_network)
    assert p.main(['--plan', str(path), '--dry-run']) == 0
    output = json.loads(capsys.readouterr().out)
    assert output['segments']['C1']['total_bytes'] == len(DATA)


@pytest.mark.parametrize('side', ['before', 'after'])
def test_first_checkpoint_crash_recovers_on_clean_restart(tmp_path, side):
    server = Server()
    run = runner(tmp_path, server)
    checkpoint = run.checkpoint
    def crash(path, data):
        assert data['bytes'] == 0
        if side == 'after':
            checkpoint(path, data)
        raise OSError('synthetic initial checkpoint interruption')
    run.checkpoint = crash
    assert run.run() == 2
    partial = run.root / 'noaa-nos' / (p.filename(row()) + '.part')
    assert partial.stat().st_size == 0
    assert partial.with_name(partial.name + '.json').exists() == (side == 'after')
    server.calls.clear()
    restarted = runner(tmp_path, server)
    assert restarted.run() == 0
    assert [call[1] for call in server.calls] == ['HEAD', 'GET']
    assert Path(receipt(restarted)['path']).read_bytes() == DATA
    assert (restarted.mirror / 'noaa-nos.jsonl').read_bytes() == (restarted.root / 'noaa-nos/manifest.jsonl').read_bytes()


@pytest.mark.parametrize('case', ['nonempty-unreceipted', 'empty-invalid-receipt', 'empty-changed-identity'])
def test_initial_recovery_never_discards_suspect_bytes_or_receipts(tmp_path, case):
    server = Server()
    run = runner(tmp_path, server)
    directory = run.root / 'noaa-nos'
    directory.mkdir(parents=True)
    partial = directory / (p.filename(row()) + '.part')
    partial.write_bytes(b'preserve' if case == 'nonempty-unreceipted' else b'')
    meta = partial.with_name(partial.name + '.json')
    if case == 'empty-invalid-receipt':
        p.atomic_json(meta, {})
    elif case == 'empty-changed-identity':
        p.atomic_json(meta, {'url': URL, 'total': len(DATA), 'final_url': URL,
                            'bytes': 0, 'sha256': hashlib.sha256(b'').hexdigest(), 'validator': '"old"'})
    before = partial.read_bytes()
    assert run.run() == 2
    assert [c[1] for c in server.calls] == ['HEAD']
    assert partial.read_bytes() == before


def test_preflight_and_download_share_cooldowns_across_mirrors(tmp_path):
    server = Server(status=503)
    first = runner(tmp_path, server)
    assert first.probe_sizes(tmp_path / 'sized.json') == 2
    server.calls.clear()
    server.status = None
    second = runner(tmp_path, server)
    second.mirror = tmp_path / 'different-mirror'
    assert second.run() == 75
    assert not server.calls
    # A long-lived preflight instance must reload another process's new hold.
    third = runner(tmp_path, server)
    third.mirror = tmp_path / 'third-mirror'
    assert third.probe_sizes(tmp_path / 'sized-again.json') == 2
    assert not server.calls
    third.request('HEAD', 'https://pubs.usgs.gov/fixture', max_bytes=0)
    assert [c[0] for c in server.calls] == ['pubs.usgs.gov']


def test_concurrent_parking_merges_hosts_and_never_shortens_holds(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    barrier = Barrier(2)
    runs = [runner(tmp_path, Server()), runner(tmp_path, Server())]
    hosts = ['data.ngdc.noaa.gov', 'pubs.usgs.gov']
    def park(index):
        barrier.wait(timeout=5)
        with pytest.raises(p.Parked):
            runs[index].park(hosts[index], 'synthetic outage', 503)
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(park, range(2)))
    state = p.read_json(runs[0].retry_state)
    assert set(state) == set(hosts)
    assert state[hosts[0]]['retry_at'] == 87400
    assert state[hosts[1]]['retry_at'] == 1900
    with pytest.raises(p.Parked):
        runs[1].park(hosts[0], 'shorter transport hold')
    newer = p.read_json(runs[0].retry_state)
    assert newer[hosts[0]]['retry_at'] == 87400
    assert newer[hosts[0]]['failures'] == 2
    assert newer[hosts[1]] == state[hosts[1]]


def test_legacy_import_is_network_free_additive_and_preserves_originals(tmp_path, monkeypatch, capsys):
    paths = [tmp_path / 'snapshot-a/state.json', tmp_path / 'snapshot-b/state.json']
    p.atomic_json(paths[0], {'data.ngdc.noaa.gov': {'retry_at': 10000, 'failures': 2}})
    p.atomic_json(paths[1], {'data.ngdc.noaa.gov': {'retry_at': 2000, 'failures': 1},
                           'pubs.usgs.gov': {'retry_at': 3000}})
    originals = [path.read_bytes() for path in paths]
    def no_network(*args, **kwargs):
        raise AssertionError('migration contacted source')
    monkeypatch.setattr(Session, 'request', no_network)
    assert p.main(['--import-retry-state', str(paths[0]), '--import-retry-state', str(paths[1])]) == 0
    state = json.loads(capsys.readouterr().out)['parked_hosts']
    assert state['data.ngdc.noaa.gov']['retry_at'] == 10000
    assert state['pubs.usgs.gov']['retry_at'] == 3000
    assert [path.read_bytes() for path in paths] == originals
    run = runner(tmp_path, Server())
    with pytest.raises(p.Parked):
        run.request('HEAD', URL, max_bytes=0)


def test_request_and_parking_are_one_cross_instance_transaction(tmp_path, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    entered, release, waiting = Event(), Event(), Event()
    calls = []
    def request(self, method, url, **kwargs):
        calls.append(url)
        entered.set()
        assert release.wait(timeout=5)
        return SimpleNamespace(status=503, headers={})
    monkeypatch.setattr(p.TransferSession, 'request', request)
    a, b = runner(tmp_path, Server()), runner(tmp_path, Server())
    def first():
        with pytest.raises(p.Parked):
            a.request('HEAD', URL, max_bytes=0)
    def second():
        waiting.set()
        with pytest.raises(p.Parked):
            b.request('HEAD', URL, max_bytes=0)
    with ThreadPoolExecutor(max_workers=2) as pool:
        one = pool.submit(first)
        assert entered.wait(timeout=5)
        two = pool.submit(second)
        assert waiting.wait(timeout=5)
        release.set()
        one.result(timeout=5)
        two.result(timeout=5)
    assert calls == [URL]
    assert p.read_json(a.retry_state)['data.ngdc.noaa.gov']['retry_at'] == 87400
