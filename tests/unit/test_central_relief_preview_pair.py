"""Consume disposable, byte-bound PMTiles archives through the real preview CLI."""
from base64 import b64decode
from hashlib import sha256
import json
import re
import struct
import zlib

import pytest

from scripts.relief import central_relief_preview_pair as preview
from skippercast.relief import envelope, package
from skippercast.relief.pmtiles_v3 import write_pmtiles

REGION = 'big-sur-coast'
ADDRESS = (8, 41, 99)
NEIGHBOR = (8, 41, 98)
BOUNDS = (-122, 35, -121, 37)
RIGHTS = {'public_display': 'allowed', 'license': 'public-domain'}


def _png(rgb):
    def chunk(kind, payload):
        data = kind + payload
        return struct.pack('>I', len(payload)) + data + struct.pack('>I', zlib.crc32(data))

    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', 256, 256, 8, 2, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress((b'\x00' + bytes(rgb) * 256) * 256)) + chunk(b'IEND', b''))


def _write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


@pytest.fixture
def make_package(tmp_path, monkeypatch):
    # Only the fake source catalog is substituted; the tracked schema, envelope
    # verification, archive writer and QA reader are all real.
    _write(tmp_path / 'catalog/sources.json', json.dumps({'sources': [
        {'id': 'fixture-grid', 'review_status': 'approved', 'rights': RIGHTS},
    ]}).encode())
    monkeypatch.setattr(envelope, 'repo_root', lambda: tmp_path)

    def build(side, code, tiles, region=REGION):
        root = tmp_path / side / region
        generation = code * 64

        def ref(path):
            return {'path': path.relative_to(root).as_posix(), 'sha256': sha256(path.read_bytes()).hexdigest()}

        archive = write_pmtiles(root / package.ARCHIVE, tiles.items(), metadata={}, bounds=BOUNDS,
                                minzoom=8, maxzoom=8, center=(8, -121.5, 36))
        digest = root / package.DIGEST_ROOT
        _write(digest, b'{"synthetic":true}')
        layers = [ref(path) | {'bytes': path.stat().st_size} for path in sorted((archive, digest))]
        release = root / 'release' / generation / 'release.json'
        _write(release, json.dumps({
            'schema': package.RELEASE_SCHEMA, 'region': region, 'generation': generation,
            'code_sha': code * 40, 'private': False, 'disclaimer': package.DISCLAIMER,
            'bounds': BOUNDS, 'minzoom': 8, 'maxzoom': 8, 'layers': layers,
            'digest_root_sha256': ref(digest)['sha256'],
            'sources': [{'id': 'fixture-grid', 'attribution': 'Synthetic grid', 'rights_class': 'public',
                         'label': 'estimated', 'vertical_datum': 'NAVD88', 'survey_dates': ['2020'], 'rights': RIGHTS}],
            'detail_summary': {'mask': 'transparent-nodata', 'depth_bands': [
                {'source_id': 'fixture-grid', 'min_depth_m': 0, 'max_depth_m': 20,
                 'resolution_m': 2, 'support_class': 2},
            ]},
            'native_support_by_zoom': {'8': {'tiles': len(tiles), 'limit_m': 91.44, 'sources': []}},
        }).encode())
        qa = root / 'qa' / generation / 'qa.json'
        _write(qa, json.dumps({'status': 'PASS', 'release_sha256': ref(release)['sha256']}).encode())
        review = root / 'review' / generation / 'envelope.json'
        _write(review, json.dumps({'schema': envelope.ENVELOPE_SCHEMA, 'region': region, 'generation': generation,
                                  'release': ref(release), 'qa': ref(qa), 'layers': layers}).encode())
        return review

    return build


def _run(tmp_path, left, right, output='pair.html'):
    return preview.main(['--scratch-root', str(tmp_path), '--region', REGION,
                         '--xyz', *map(str, ADDRESS), '--candidate-envelope', str(left),
                         '--comparator-envelope', str(right), '--output', output])


def _panels(tmp_path):
    document = (tmp_path / 'pair.html').read_text(encoding='utf-8')
    return document, re.findall(r'<section>(.*?)</section>', document, re.DOTALL)


def _images(panel):
    return [b64decode(data, validate=True) for data in re.findall(r'src="data:image/png;base64,([^"]+)"', panel)]


def test_exact_xyz_pane_bytes_order_and_identity(tmp_path, make_package):
    # Catches swapping panes, transposing XYZ, or taking the first tile instead of the chosen address.
    red, green, blue = (_png(rgb) for rgb in ((255, 0, 0), (0, 255, 0), (0, 0, 255)))
    left = make_package('candidate', 'a', {NEIGHBOR: blue, ADDRESS: red})
    right = make_package('comparator', 'b', {NEIGHBOR: blue, ADDRESS: green})
    assert _run(tmp_path, left, right.relative_to(tmp_path)) == 0
    document, (candidate, comparator) = _panels(tmp_path)
    assert '<h2>Candidate</h2>' in candidate and '<h2>Comparator</h2>' in comparator
    assert _images(candidate) == [red] and _images(comparator) == [green]
    for panel, path, code in ((candidate, left, 'a'), (comparator, right, 'b')):
        assert code * 40 in panel
        assert sha256(path.read_bytes()).hexdigest() in panel
        assert sha256((path.parents[2] / package.ARCHIVE).read_bytes()).hexdigest() in panel
    assert 'XYZ (z/x/y) 8/41/99' in document
    assert 'neither panel independently proves measured coverage' in document
    assert document.count('src=') == 2 and 'http://' not in document and 'https://' not in document


def test_missing_address_does_not_borrow_neighbor(tmp_path, make_package):
    # Catches filling a missing comparator address with a nearby tile or the candidate tile.
    red, blue = _png((255, 0, 0)), _png((0, 0, 255))
    left = make_package('candidate', 'a', {ADDRESS: red})
    right = make_package('comparator', 'b', {NEIGHBOR: blue})
    assert _run(tmp_path, left, right) == 0
    _, (candidate, comparator) = _panels(tmp_path)
    assert _images(candidate) == [red] and not _images(comparator)
    assert '<h2>Comparator</h2>' in comparator and 'Tile absent at the selected XYZ address' in comparator


def test_verified_other_central_region_refused(tmp_path, make_package, capsys):
    # Catches validating each envelope separately but silently comparing different Central regions.
    tiles = {ADDRESS: _png((255, 0, 0))}
    left = make_package('candidate', 'a', tiles)
    right = make_package('comparator', 'b', tiles, region='monterey-point-sur')
    assert envelope.verify_artifacts(right).release['region'] == 'monterey-point-sur'
    with pytest.raises(SystemExit, match='^2$'):
        _run(tmp_path, left, right)
    assert 'envelope must belong to selected Central region big-sur-coast' in capsys.readouterr().err
    assert not (tmp_path / 'pair.html').exists()


def test_changed_archive_refused_even_with_a_valid_replacement_png(tmp_path, make_package, capsys):
    # Catches rendering an archive that parses correctly but is not bound to its envelope.
    red, green = _png((255, 0, 0)), _png((0, 255, 0))
    left = make_package('candidate', 'a', {ADDRESS: red})
    right = make_package('comparator', 'b', {ADDRESS: green})
    archive = right.parents[2] / package.ARCHIVE
    archive.write_bytes((left.parents[2] / package.ARCHIVE).read_bytes())
    with pytest.raises(SystemExit, match='^2$'):
        _run(tmp_path, left, right)
    assert 'layer hash or size changed' in capsys.readouterr().err
    assert not (tmp_path / 'pair.html').exists()


def test_header_cannot_relabel_non_png_payload(tmp_path, make_package, capsys):
    # Catches treating the PMTiles PNG type flag as proof about the selected bytes.
    left = make_package('candidate', 'a', {ADDRESS: _png((255, 0, 0))})
    right = make_package('comparator', 'b', {ADDRESS: b'<svg><title>Not relief</title></svg>'})
    with pytest.raises(SystemExit, match='^2$'):
        _run(tmp_path, left, right)
    assert 'selected tile is not a bounded 256×256 PNG' in capsys.readouterr().err
    assert not (tmp_path / 'pair.html').exists()


def test_symlink_output_cannot_escape_scratch(tmp_path, make_package, capsys):
    # Catches using a path that looks local but resolves outside the designated scratch root.
    tiles = {ADDRESS: _png((255, 0, 0))}
    left = make_package('preview/candidate', 'a', tiles)
    right = make_package('preview/comparator', 'b', tiles)
    scratch = tmp_path / 'preview'
    outside = tmp_path / 'not-scratch.html'
    (scratch / 'pair.html').symlink_to(outside)
    with pytest.raises(SystemExit, match='^2$'):
        _run(scratch, left, right)
    assert 'paths must stay inside scratch root' in capsys.readouterr().err
    assert not outside.exists()


def _chunk(kind, payload):
    data = kind + payload
    return struct.pack('>I', len(payload)) + data + struct.pack('>I', zlib.crc32(data))


def _ihdr(depth=8, color=2, interlace=0):
    return _chunk(b'IHDR', struct.pack('>IIBBBBB', 256, 256, depth, color, 0, 0, interlace))


def _rows(row_bytes, ihdr, extra=b'', after=b''):
    body = zlib.compress((b'\x00' + bytes(row_bytes)) * 256)
    return b'\x89PNG\r\n\x1a\n' + ihdr + extra + _chunk(b'IDAT', body) + after + _chunk(b'IEND', b'')


def _indexed(extra, depth=8, after=b''):
    return _rows(256 // 8 * depth, _ihdr(depth, 3), extra, after)


@pytest.mark.parametrize('label, tile, reason', [
    ('signature and IHDR prefix only (33 bytes)', _png((1, 2, 3))[:33], 'must start with IHDR and end with IEND'),
    ('prefix plus a partial next chunk', _png((1, 2, 3))[:33 + 4], 'truncated PNG chunk'),
    ('IHDR with no image data or IEND', _png((1, 2, 3))[:8] + _ihdr(), 'must start with IHDR and end with IEND'),
    ('IHDR and IEND but no IDAT', _png((1, 2, 3))[:8] + _ihdr() + _chunk(b'IEND', b''), 'contiguous IDAT'),
    ('image data cut off before IEND', _png((1, 2, 3))[:-24], 'truncated PNG chunk'),
    ('pixel rows missing', _png((1, 2, 3))[:8] + _ihdr() + _chunk(b'IDAT', zlib.compress(b'\x00' * 3 * 256 * 255))
     + _chunk(b'IEND', b''), 'truncated, oversized'),
    ('corrupted image data checksum', _png((1, 2, 3))[:60] + b'\xff' + _png((1, 2, 3))[61:], 'checksum mismatch'),
    ('bytes after IEND', _png((1, 2, 3)) + b'\x00', 'trailing bytes'),
    # Valid framing and CRC do not make a nonempty IEND legal.
    ('CRC-correct nonempty IEND', _png((0, 255, 0))[:-12] + _chunk(b'IEND', b'\x00'), 'PNG IEND must be empty'),
    ('invalid scanline filter', _png((1, 2, 3))[:8] + _ihdr()
     + _chunk(b'IDAT', zlib.compress((b'\x09' + b'\x00' * 3 * 256) * 256)) + _chunk(b'IEND', b''), 'invalid filter'),
    ('indexed with a one-byte PLTE (gdk-pixbuf: PLTE invalid)',
     _indexed(_chunk(b'PLTE', b'\x00')), 'PLTE chunk is invalid'),
    ('indexed with an empty PLTE', _indexed(_chunk(b'PLTE', b'')), 'PLTE chunk is invalid'),
    ('indexed with more palette entries than the bit depth allows',
     _indexed(_chunk(b'PLTE', bytes(9)), depth=1), 'PLTE chunk is invalid'),
    ('indexed with two PLTE chunks', _indexed(_chunk(b'PLTE', bytes(3)) * 2), 'more than one PLTE'),
    ('indexed with PLTE after IDAT', _indexed(b'', after=_chunk(b'PLTE', bytes(3))), 'PLTE chunk comes after IDAT'),
    ('indexed with no PLTE', _indexed(b''), 'indexed PNG needs PLTE'),
    ('grayscale with a PLTE', _rows(256, _ihdr(8, 0), _chunk(b'PLTE', bytes(3))), 'must not have a PLTE'),
    ('indexed with more tRNS entries than palette entries',
     _indexed(_chunk(b'PLTE', bytes(3)) + _chunk(b'tRNS', b'\xff\xff')), 'tRNS chunk is invalid'),
    ('truecolor with a tRNS of the wrong length', _rows(768, _ihdr(8, 2), _chunk(b'tRNS', b'\x00\x00')),
     'tRNS chunk is invalid'),
    ('RGBA with a tRNS', _rows(1024, _ihdr(8, 6), _chunk(b'tRNS', b'\x00\x00')), 'tRNS chunk is invalid'),
    ('unknown critical chunk', _rows(768, _ihdr(8, 2), _chunk(b'ABCD', b'')), 'unknown critical chunk'),
])
def test_prefix_or_broken_png_refused_not_embedded(tmp_path, make_package, capsys, label, tile, reason):
    # Catches accepting any bound tile with a PNG signature and 256x256 IHDR and emitting a broken <img>.
    left = make_package('candidate', 'a', {ADDRESS: _png((255, 0, 0))})
    right = make_package('comparator', 'b', {ADDRESS: tile})
    with pytest.raises(SystemExit, match='^2$'):
        _run(tmp_path, left, right)
    err = capsys.readouterr().err
    assert 'selected tile is not a complete decodable 256×256 PNG' in err and reason in err, label
    assert not (tmp_path / 'pair.html').exists()


def test_valid_png_variants_still_embedded(tmp_path, make_package):
    # Catches an over-strict decoder refusing real tiles: palette, 16-bit RGBA, 1-bit gray and Adam7 interlace.
    rows = lambda size: (b'\x00' + bytes(size)) * 256
    adam7 = b''.join((b'\x00' + bytes(w)) * h for w, h in
                     ((32, 32), (32, 32), (64, 32), (64, 64), (128, 64), (128, 128), (256, 128)))
    head = b'\x89PNG\r\n\x1a\n'
    tiles = {
        (8, 41, 1): head + _ihdr(8, 3) + _chunk(b'PLTE', b'\x00\x00\x00') + _chunk(b'IDAT', zlib.compress(rows(256))),
        (8, 41, 2): head + _ihdr(16, 6) + _chunk(b'IDAT', zlib.compress(rows(256 * 8))),
        (8, 41, 3): head + _ihdr(1, 0) + _chunk(b'IDAT', zlib.compress(rows(32))),
        (8, 41, 4): head + _ihdr(8, 0, 1) + _chunk(b'IDAT', zlib.compress(adam7)),
        (8, 41, 5): _indexed(_chunk(b'PLTE', bytes(range(12))) + _chunk(b'tRNS', b'\x80\xff'), depth=2)[:-12],
        (8, 41, 6): _indexed(_chunk(b'PLTE', bytes(768)), depth=8)[:-12],
        (8, 41, 7): _rows(768, _ihdr(8, 2), _chunk(b'PLTE', bytes(6)) + _chunk(b'tRNS', bytes(6)))[:-12],
    }
    for address, body in tiles.items():
        tiles[address] = body + _chunk(b'IEND', b'')
    for address, body in tiles.items():
        left = make_package(f'candidate{address[2]}', 'a', {address: body})
        right = make_package(f'comparator{address[2]}', 'b', {address: body})
        output = f'pair{address[2]}.html'
        assert preview.main(['--scratch-root', str(tmp_path), '--region', REGION, '--xyz', *map(str, address),
                             '--candidate-envelope', str(left), '--comparator-envelope', str(right),
                             '--output', output]) == 0
        assert _images((tmp_path / output).read_text(encoding='utf-8')) == [body, body]
