"""Offline CLI controls with an actual PMTiles index and release envelope."""
from collections import Counter
import hashlib
import json
import struct
from unittest.mock import Mock
import zlib

import pytest

from scripts.relief import central_viewport_byte_fit as cli
from skippercast.relief import envelope, package, pmtiles_v3

REGION = 'cambria-san-simeon'
GEN = 'a' * 64
REVIEW = f'{REGION}/review/{GEN}/envelope.json'
SOURCE = 'usgs-3dep-1m-dem'  # Metadata vocabulary only; no source data used.
LIGHT = (8, 41, 100)
SHARED = (8, 41, 101)
HEAVY = (10, 168, 400)
MISSING = (8, 42, 101)


def _png(text):
    def chunk(kind, payload):
        return struct.pack('>I', len(payload)) + kind + payload + struct.pack('>I', zlib.crc32(kind + payload))

    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>2I5B', 256, 256, 8, 2, 0, 0, 0))
            + chunk(b'tEXt', b'Fixture\0' + text)
            + chunk(b'IDAT', zlib.compress(bytes(256 * (1 + 256 * 3)))) + chunk(b'IEND', b''))


def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write(path, doc):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, sort_keys=True), encoding='utf-8')
    return path


def _pin_candidate(root, coords):
    def ref(path):
        return {'path': path.relative_to(root).as_posix(), 'sha256': _sha(path)}

    counts = Counter(z for z, _, _ in coords)
    low, high = min(counts), max(counts)
    digest = _write(root / package.DIGEST_ROOT, {'synthetic': True})
    layers = [ref(root / p) | {'bytes': (root / p).stat().st_size} for p in (package.DIGEST_ROOT, package.ARCHIVE)]
    release = _write(root / f'release/{GEN}/release.json', {
        'schema': package.RELEASE_SCHEMA, 'region': REGION, 'generation': GEN,
        'code_sha': 'c' * 40, 'private': False, 'disclaimer': package.DISCLAIMER,
        'bounds': [-123, 35, -120, 37], 'minzoom': low, 'maxzoom': high,
        'sources': [{'id': SOURCE, 'attribution': 'Synthetic fixture, no survey data', 'rights_class': 'public',
                     'label': 'estimated', 'vertical_datum': 'NAVD88', 'survey_dates': ['2020'],
                     'rights': {'public_display': 'allowed', 'license': 'public-domain'}}],
        'detail_summary': {'mask': 'transparent-nodata', 'depth_bands': [
            {'source_id': SOURCE, 'min_depth_m': 0, 'max_depth_m': 20, 'resolution_m': 2, 'support_class': 2},
        ]},
        'native_support_by_zoom': {
            str(z): {'tiles': counts[z], 'limit_m': 91.44, 'sources': []} for z in range(low, high + 1)
        },
        'layers': layers, 'digest_root_sha256': _sha(digest),
    })
    qa = _write(root / f'qa/{GEN}/qa.json', {'status': 'PASS', 'release_sha256': _sha(release)})
    return _write(root / f'review/{GEN}/envelope.json', {
        'schema': envelope.ENVELOPE_SCHEMA, 'region': REGION, 'generation': GEN,
        'release': ref(release), 'qa': ref(qa), 'layers': layers,
    })


@pytest.fixture
def candidate(tmp_path, monkeypatch):
    # Use the real writer with a smaller root limit so a tiny fixture exercises leaves.
    monkeypatch.setattr(pmtiles_v3, '_ROOT_LIMIT', 64)
    light = _png(b'light')
    heavy = _png(b'x' * 810_000)  # A valid ancillary chunk makes one visible PNG heavy.
    payloads = {LIGHT: light, SHARED: light, HEAVY: heavy}
    payloads.update({(8, 44 + i % 8, 100 + i // 8): _png(b'o' * (13 + i * i)) for i in range(40)})
    archive = pmtiles_v3.write_pmtiles(tmp_path / REGION / package.ARCHIVE, payloads.items(), metadata={},
                                      bounds=(-123, 35, -120, 37), minzoom=8, maxzoom=10, center=(8, -121, 36))
    return archive, _pin_candidate(tmp_path / REGION, payloads), payloads


def _argv(root, desktop=(LIGHT, SHARED), phone=(HEAVY,), review=REVIEW):
    def tokens(coords):
        return [coord if isinstance(coord, str) else '/'.join(map(str, coord)) for coord in coords]

    return ['--scratch-root', str(root), '--region', REGION, '--envelope', str(review),
            '--desktop', *tokens(desktop), '--phone', *tokens(phone)]


def test_addressed_bytes_not_archive_mean_or_unique_blob_bytes(candidate, tmp_path, capsys):
    """A whole-archive mean hides the heavy tile; deduplicating blob offsets undercounts desktop."""
    archive, review, payloads = candidate
    raw = archive.read_bytes()
    leaf_bytes, stored_tile_bytes, addressed = struct.unpack_from('<Q8xQQ', raw, 48)
    assert leaf_bytes > 0  # The real reader must follow a leaf pointer.
    assert addressed == len(payloads)
    assert stored_tile_bytes * 15 < 800_000 * addressed  # Even the worst-case phone mean estimate fits.
    assert len(payloads[HEAVY]) > 800_000
    assert cli.main(_argv(tmp_path, desktop=(SHARED, LIGHT), review=review)) == 1
    out, err = capsys.readouterr()
    assert not err
    report = json.loads(out)
    assert (report['region'], report['generation'], report['envelope_sha256']) == (REGION, GEN, _sha(review))
    assert report['views'] == {
        'desktop': dict(window=[list(LIGHT), list(SHARED)], measured_bytes=len(payloads[LIGHT]) + len(payloads[SHARED]),
                        cap_bytes=1_600_000, missing_tiles=[], status='FIT'),
        'phone': dict(window=[list(HEAVY)], measured_bytes=len(payloads[HEAVY]), cap_bytes=800_000,
                      missing_tiles=[], status='OVER'),
    }
    assert cli.main(_argv(tmp_path)) == 1  # Same bytes through a relative input path and reordered window.
    assert capsys.readouterr() == (out, '')


def test_missing_address_cannot_be_a_zero_byte_fit(candidate, tmp_path, capsys):
    """Dropping an unaddressed tile from a sum would incorrectly pass a partial view."""
    _, _, payloads = candidate
    assert cli.main(_argv(tmp_path, phone=(MISSING, LIGHT))) == 2
    out, err = capsys.readouterr()
    assert not err
    assert json.loads(out)['views']['phone'] == dict(
        window=[list(LIGHT), list(MISSING)], measured_bytes=len(payloads[LIGHT]), cap_bytes=800_000,
        missing_tiles=[list(MISSING)], status='INCOMPLETE',
    )


@pytest.mark.parametrize(('device', 'zoom', 'why'), [
    ('desktop', 7, 'outside release range'),
    ('phone', 11, 'outside release range'),
    ('phone', 9, 'declares zero tiles'),
])
def test_unserved_candidate_zoom_is_invalid_not_incomplete(
    candidate, tmp_path, capsys, monkeypatch, device, zoom, why,
):
    """Checking only the generic tile grid makes a wrong camera look like missing tiles."""
    extract = Mock(wraps=cli._payload_lengths)
    monkeypatch.setattr(cli, '_payload_lengths', extract)
    window = ((zoom, 41, 100),)
    args = _argv(tmp_path, desktop=window) if device == 'desktop' else _argv(tmp_path, phone=window)
    assert cli.main(args) == 2
    out, err = capsys.readouterr()
    assert not out and err.startswith(f'invalid: {device}: requested zoom z{zoom}')
    assert why in err and 'z8–z10' in err
    extract.assert_not_called()


def test_pinned_mutation_refused_before_index_evaluation(candidate, tmp_path, capsys):
    """Trusting just the layer path/size, or decoding before pin verification, misses this refusal."""
    archive, _, _ = candidate
    with archive.open('r+b') as file:
        file.write(b'X')  # Same length, now also invalid PMTiles magic.
    assert cli.main(_argv(tmp_path)) == 2
    out, err = capsys.readouterr()
    assert not out and f'layer hash or size changed: {package.ARCHIVE}' in err


@pytest.mark.parametrize(('phone', 'why'), [
    (('8/41/100', '08/041/100'), 'repeated tile address'),
    (('8/41/100', '9/42/100'), 'mixed zooms'),
    (tuple(f'8/{x}/100' for x in range(16)), 'expected 1–15 tile addresses'),
    (('8/256/100',), 'outside the PMTiles tile grid'),
])
def test_invalid_windows_refuse_before_opening_input(tmp_path, capsys, phone, why):
    """Counting duplicates, mixed scales, too many tiles, or invalid coordinates means a false view."""
    assert cli.main(_argv(tmp_path, phone=phone)) == 2
    out, err = capsys.readouterr()
    assert not out and why in err


@pytest.mark.parametrize('absolute', [True, False])
def test_envelope_cannot_escape_scratch(tmp_path, capsys, absolute):
    """An absolute-path escape or a symlink could make the checker read outside scratch."""
    scratch = tmp_path / 'scratch'
    scratch.mkdir()
    outside = _write(tmp_path / REVIEW, {})
    (scratch / REGION).symlink_to(tmp_path / REGION, target_is_directory=True)
    assert cli.main(_argv(scratch, review=outside if absolute else REVIEW)) == 2
    out, err = capsys.readouterr()
    assert not out and ('inside the scratch root' if absolute else 'symlink in artifact path') in err


@pytest.mark.parametrize('limit', ['bytes', 'tiles'])
def test_archive_limits_refuse_unbounded_index_evaluation(candidate, tmp_path, capsys, limit):
    """A bounded CLI window does not bound the archive mmap or the full address table."""
    archive, _, payloads = candidate
    if limit == 'bytes':
        with archive.open('r+b') as file:
            file.truncate(1_500_000_001)  # Sparse and refused before hashing.
        why = 'archive size outside'
    else:
        with archive.open('r+b') as file:
            file.seek(72)
            file.write(struct.pack('<Q', cli.MAX_ADDRESSED_TILES + 1))
        _pin_candidate(tmp_path / REGION, payloads)
        why = 'addressed tile count outside'
    assert cli.main(_argv(tmp_path)) == 2
    out, err = capsys.readouterr()
    assert not out and why in err


def _hostile_archive(root, entries, addressed):
    """Pinned one-blob archive whose root directory is replaced by ``entries`` (tile id, offset, length, run)."""
    blob = _png(b'only')
    path = pmtiles_v3.write_pmtiles(root / REGION / package.ARCHIVE, [(LIGHT, blob)], metadata={},
                                    bounds=(-123, 35, -120, 37), minzoom=8, maxzoom=8, center=(8, -121, 36))
    raw = path.read_bytes()
    header = list(struct.unpack_from('<11Q', raw, 8))
    old_root = header[1]
    root_dir = pmtiles_v3._directory(entries)
    shift = len(root_dir) - old_root
    header[1], header[2], header[4], header[6], header[8] = len(root_dir), header[2] + shift, header[4] + shift, \
        header[6] + shift, addressed
    path.write_bytes(raw[:8] + struct.pack('<11Q', *header) + raw[96:127] + root_dir + raw[127 + old_root:])
    _pin_candidate(root / REGION, (LIGHT,))
    return len(blob)


def test_directory_run_cannot_outgrow_header_count(tmp_path, capsys):
    """A header saying one tile must stop a 250,001-tile run before it is expanded, not after decoding it."""
    tid = pmtiles_v3._tile_id(*LIGHT)
    size = _hostile_archive(tmp_path, [(tid, 0, len(_png(b'only')), cli.MAX_ADDRESSED_TILES + 1)], addressed=1)
    assert size
    assert cli.main(_argv(tmp_path, desktop=(LIGHT,), phone=(LIGHT,))) == 2
    out, err = capsys.readouterr()
    assert not out and 'directory runs address more than 1 tiles' in err


def test_index_failure_after_tile_views_still_exits_invalid_input(tmp_path, capsys):
    """A bad later directory row leaves earlier tile views alive; unmapping must not raise BufferError."""
    tid = pmtiles_v3._tile_id(*LIGHT)
    length = len(_png(b'only'))
    _hostile_archive(tmp_path, [(tid, 0, length, 1), (tid + 1, length, length, 1)], addressed=2)
    assert cli.main(_argv(tmp_path, desktop=(LIGHT,), phone=(LIGHT,))) == 2
    out, err = capsys.readouterr()
    assert not out and 'cannot read PMTiles index: tile payload span outside declared tile data' in err
