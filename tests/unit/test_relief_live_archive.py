"""Offline whole-result checks for the streamed archive and served digest chain."""
import hashlib
from io import BytesIO
import json

import pytest

from skippercast.relief import digests
from skippercast.relief.live_archive import check_archive
from skippercast.relief.pmtiles_v3 import write_pmtiles


SELECTED = ('8/0_0.json', '9/0_0.json', '10/2_0.json')
COORDS = ('8/5/0', '9/0/0', '10/128/0')
INDEX_LIMIT = 1 << 20


def sha(data):
    return hashlib.sha256(data).hexdigest()


def encoded(doc):
    return json.dumps(doc).encode()


@pytest.fixture
def release(tmp_path):
    path = write_pmtiles(tmp_path / 'tiny.pmtiles', {
        (8, 5, 0): b'first-payload',
        (8, 6, 0): b'other-payload',
        (8, 0, 64): b'lower-x-in-higher-block',
        (9, 0, 0): b'zoom-nine',
        (10, 128, 0): b'block-two',
        (10, 640, 0): b'block-ten',
    }.items(), metadata={}, bounds=(-121., 35., -120., 36.), minzoom=8, maxzoom=10,
        center=(8, -120.5, 35.5))
    archive = path.read_bytes()
    index = tmp_path / 'index'
    index.mkdir()
    digests.write_index(BytesIO(archive), index)
    return archive, {p.relative_to(index).as_posix(): p.read_bytes() for p in index.rglob('*.json')}


class Site:
    def __init__(self, release):
        archive, index = release
        self.pointer = dict(region='fixture-bay', sha256=sha(archive), bytes=len(archive),
                            minzoom=8, maxzoom=10, digest_root_sha256=sha(index['root.json']))
        stem = f"tiles/relief/fixture-bay/{self.pointer['sha256']}"
        self.archive = stem + '.pmtiles'
        self.prefix = f"{stem}.digests/{self.pointer['digest_root_sha256']}/"
        self.root = self.prefix + 'root.json'
        self.objects = {self.archive: archive, **{self.prefix + p: data for p, data in index.items()}}
        self.calls = []
        self.closed = []

    def fetch(self, key, *, max_bytes):
        self.calls.append((key, max_bytes))
        data = self.objects.get(key)
        if data is None:
            return None

        def stream():
            try:
                yield data[:127]
                yield data[127:]
                assert len(data) <= max_bytes, 'read again after receiving excess bytes'
            finally:
                self.closed.append(key)

        return stream()

    def run(self, **kwargs):
        return check_archive(self.pointer, self.fetch, **kwargs)

    def expected_calls(self, *keys):
        return [(key, self.pointer['bytes'] if key == self.archive else INDEX_LIMIT) for key in keys]

    def expected_rows(self):
        rows = [row('archive', self.archive), row('root', self.root)]
        for name, coords in zip(SELECTED, COORDS):
            rows += [row('chunk', self.prefix + name), row('tile', f'{self.archive}#{coords}')]
        return rows


def row(check, key, reason=''):
    return dict(check=check, key=key, status='FAIL' if reason else 'PASS', reason=reason)


def reviewed_chunk(release, data):
    archive, index = release
    root = json.loads(index['root.json'])
    root['chunks'][SELECTED[0]] = sha(data)
    return Site((archive, {**index, SELECTED[0]: data, 'root.json': encoded(root)}))


def test_C2_verified_chain_uses_numeric_block_order_and_first_tile(release):
    """C2: String ordering or choosing the globally lowest x samples the wrong block."""
    site = Site(release)
    assert site.run() == site.expected_rows()
    assert site.calls == site.expected_calls(site.archive, site.root, *(site.prefix + p for p in SELECTED))
    assert site.closed == [key for key, _ in site.calls]


def test_C1_same_size_payload_tamper_fails_archive_then_isolated_tile_check(release):
    """C1: A header-only check accepts a changed payload; C2 must detect it independently."""
    site = Site(release)
    archive = release[0]
    tampered = archive.replace(b'first-payload', b'Xirst-payload')
    assert tampered != archive and tampered[:127] == archive[:127] and len(tampered) == len(archive)
    site.objects[site.archive] = tampered
    assert site.run() == [row('archive', site.archive, 'sha256')]
    assert site.calls == site.expected_calls(site.archive)

    site.calls.clear()
    expected = site.expected_rows()
    expected[3] = row('tile', f'{site.archive}#8/5/0', 'sha256')
    assert site.run(_verify_archive_hash=False) == expected
    assert site.calls == site.expected_calls(site.archive, site.root, *(site.prefix + p for p in SELECTED))


@pytest.mark.parametrize('verify', [True, False], ids=['verify', 'skip-comparison'])
def test_C1_archive_overflow_stops_stream_even_when_comparison_disabled(release, verify):
    """C1: A fetcher's byte hint or test flag cannot replace the verifier's cap."""
    site = Site(release)
    site.objects[site.archive] += b'!'
    assert site.run(_verify_archive_hash=verify) == [row('archive', site.archive, 'oversize')]
    assert site.calls == site.expected_calls(site.archive)
    assert site.closed == [site.archive]


def test_C1_short_stream_fails_size_even_with_matching_sha(release):
    """C1: A hash-only verifier ignores the reviewed byte count."""
    site = Site(release)
    site.pointer['bytes'] = len(release[0]) + 1
    assert site.run() == [row('archive', site.archive, 'size')]
    assert site.calls == site.expected_calls(site.archive)


def test_C2_byte_matching_but_unreadable_archive_cannot_prove_tiles(release):
    """C2: Matching pointer bytes alone cannot certify a malformed PMTiles directory."""
    archive, index = release
    site = Site((b'!' + archive[1:], index))
    assert site.run() == [row('archive', site.archive, 'invalid')]
    assert site.calls == site.expected_calls(site.archive)


@pytest.mark.parametrize('depth', ['archive', 'root', 'chunk'])
def test_C3_missing_fetch_is_a_fail_without_a_false_descendant_pass(release, depth):
    """C3: A 404 is visible, and dependent checks do not appear as PASS."""
    site = Site(release)
    chunk = site.prefix + SELECTED[0]
    expected = site.expected_rows()
    start = {'archive': 0, 'root': 1, 'chunk': 2}[depth]
    key = (site.archive, site.root, chunk)[start]
    calls = [site.archive, site.root, *(site.prefix + p for p in SELECTED)]
    if depth != 'chunk':
        calls = calls[:start + 1]
    tail = expected[4:] if depth == 'chunk' else []
    del site.objects[key]
    assert site.run() == expected[:start] + [row(depth, key, 'missing')] + tail
    assert site.calls == site.expected_calls(*calls)


@pytest.mark.parametrize('depth', ['root', 'chunk'])
@pytest.mark.parametrize('reason', ['sha256', 'oversize'])
def test_C2_index_object_bytes_are_authenticated_and_capped(release, depth, reason):
    """C2: Re-serialized or oversized index objects must not authorize a tile."""
    site = Site(release)
    key = site.root if depth == 'root' else site.prefix + SELECTED[0]
    site.objects[key] += b' ' if reason == 'sha256' else b' ' * INDEX_LIMIT
    fail = row(depth, key, reason)
    expected = site.expected_rows()
    if depth == 'root':
        assert site.run() == [expected[0], fail]
        assert site.calls == site.expected_calls(site.archive, site.root)
    else:
        assert site.run() == expected[:2] + [fail] + expected[4:]
        assert site.calls == site.expected_calls(site.archive, site.root, *(site.prefix + p for p in SELECTED))


@pytest.mark.parametrize('root', [b'{}', b'{"chunks":{"../escape.json":"' + b'0' * 64 + b'"}}',
                                 b'{"chunks":{"8/4_0.json":"' + b'0' * 64 + b'"}}'],
                         ids=['shape', 'path', 'grid'])
def test_C2_authenticated_root_must_be_a_staged_inventory(release, root):
    """C2: Even reviewed root bytes cannot select a non-staged chunk key."""
    archive, index = release
    site = Site((archive, {**index, 'root.json': root}))
    assert site.run() == [row('archive', site.archive), row('root', site.root, 'invalid')]
    assert site.calls == site.expected_calls(site.archive, site.root)


def test_C2_unlisted_zoom_reports_missing_without_fetch(release):
    """C2: Iterating only listed zooms silently omits a missing sample."""
    archive, index = release
    root = json.loads(index['root.json'])
    del root['chunks'][SELECTED[1]]
    site = Site((archive, {**index, 'root.json': encoded(root)}))
    expected = site.expected_rows()
    assert site.run() == expected[:4] + [row('chunk', site.prefix + '9/', 'missing')] + expected[6:]
    assert site.calls == site.expected_calls(site.archive, site.root, site.prefix + SELECTED[0], site.prefix + SELECTED[2])


@pytest.mark.parametrize('data', [b'[]', encoded([[64, 0, '0' * 64]])], ids=['empty', 'wrong-block'])
def test_C2_authenticated_chunk_must_supply_a_sample(release, data):
    """C2: A chunk hash by itself does not prove a sample row exists in that block."""
    site = reviewed_chunk(release, data)
    expected = site.expected_rows()
    assert site.run() == expected[:2] + [row('chunk', site.prefix + SELECTED[0], 'invalid')] + expected[4:]
    assert site.calls == site.expected_calls(site.archive, site.root, *(site.prefix + p for p in SELECTED))


@pytest.mark.parametrize('missing', ['coordinate', 'block'])
def test_C2_authenticated_sample_must_exist_locally_at_same_coordinates(release, missing):
    """C2: Matching a digest at the wrong coordinate or trusting served rows is not proof."""
    archive, index = release
    digest = sha(b'first-payload')
    if missing == 'coordinate':
        site = reviewed_chunk(release, encoded([[4, 0, digest]]))
        expected = site.expected_rows()
        expected[3] = row('tile', f'{site.archive}#8/4/0', 'missing')
        names = SELECTED
    else:
        # Point the served root at a block that the local archive never contained.
        root = json.loads(index['root.json'])
        del root['chunks'][SELECTED[0]], root['chunks']['8/0_1.json']
        data = encoded([[64, 0, digest]])
        name = '8/1_0.json'
        root['chunks'][name] = sha(data)
        site = Site((archive, {**index, name: data, 'root.json': encoded(root)}))
        expected = site.expected_rows()
        expected[2:4] = [row('chunk', site.prefix + name), row('tile', f'{site.archive}#8/64/0', 'missing')]
        names = (name, *SELECTED[1:])
    assert site.run() == expected
    assert site.calls == site.expected_calls(site.archive, site.root, *(site.prefix + p for p in names))


@pytest.mark.parametrize('budget, index, missing', [
    (0, 0, False), (1, 1, False), (3, 4, False), (3, 3, True), (5, None, False),
])
def test_C3_request_budget_never_returns_silent_partial_results(release, budget, index, missing):
    """C3: Budget counts requests, not rows or local tile reads; equality is allowed."""
    site = Site(release)
    expected = site.expected_rows()
    if missing:
        chunk = site.prefix + SELECTED[0]
        del site.objects[chunk]
        expected[2:4] = [row('chunk', chunk, 'missing')]
    if index is not None:
        target = expected[index]
        expected = expected[:index] + [row(target['check'], target['key'], 'budget')]
    keys = [site.archive, site.root, *(site.prefix + p for p in SELECTED)]
    assert site.run(budget=budget) == expected
    assert site.calls == site.expected_calls(*keys[:budget])
