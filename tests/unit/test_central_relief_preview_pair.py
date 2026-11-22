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
