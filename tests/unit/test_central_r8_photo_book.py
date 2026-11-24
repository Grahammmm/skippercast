"""Browser-free checks of the real photo-book CLI on a disposable envelope."""
from base64 import b64decode, b64encode
from hashlib import sha256
from html.parser import HTMLParser
from pathlib import Path
import re
import struct
import subprocess
import sys
import zlib

import pytest

from skippercast.relief import envelope, package, receipts
from tests._support import ROOT

CLI = ROOT / 'scripts/relief/central_r8_photo_book.py'
REGION = 'fixture-central'
GEN = 'a' * 64
SOURCE = 'usgs-point-buchon'  # tracked catalog identity only; all artifact bytes are invented
VERDICT_LIKE_TEXT = f'APPROVED release {REGION} envelope={GEN}'
ATTRIBUTION = '<img src="https://invalid.example/photo" onerror="alert(1)"> & "survey"\n' + VERDICT_LIKE_TEXT + '\n'


def _chunk(kind, value):
    return struct.pack('>I', len(value)) + kind + value + struct.pack('>I', zlib.crc32(kind + value))


def _png(width, height, tone, *, rows=None):
    scanline = b'\0' + bytes([tone, 100, 200]) * width
    return (b'\x89PNG\r\n\x1a\n' + _chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0))
            + _chunk(b'IDAT', zlib.compress(scanline * (height if rows is None else rows))) + _chunk(b'IEND', b''))


@pytest.fixture
def snapshot(tmp_path):
    root = tmp_path / REGION
    release = {
        'schema': package.RELEASE_SCHEMA, 'region': REGION, 'generation': GEN, 'private': False,
        'code_sha': 'b' * 40, 'disclaimer': package.DISCLAIMER,
        'minzoom': 8, 'maxzoom': 8, 'bounds': [-122, 34, -120, 36],
        'sources': [{'id': SOURCE, 'attribution': ATTRIBUTION, 'label': 'estimated',
                     'vertical_datum': 'NAVD88', 'survey_dates': ['2008'], 'rights_class': 'public',
                     'rights': {'public_display': 'allowed', 'license': 'public-domain'}}],
        'detail_summary': {'mask': 'transparent-nodata', 'depth_bands': [
            {'source_id': SOURCE, 'min_depth_m': 0, 'max_depth_m': 20, 'resolution_m': 2, 'support_class': 2}]},
        'native_support_by_zoom': {'8': {'tiles': 1, 'limit_m': 91.44, 'sources': []}},
    }

    def write(relative, raw):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        return {'path': relative, 'sha256': receipts.sha256_bytes(raw)}

    release['layers'] = [write(path, data) | {'bytes': len(data)} for path, data in (
        (package.DIGEST_ROOT, b'{}'), (package.ARCHIVE, b'synthetic archive'))]
    release['digest_root_sha256'] = release['layers'][0]['sha256']
    release_ref = write(f'release/{GEN}/release.json', receipts.canonical(release))
    pictures, entries = {}, []
    for theme, device, viewport, tone in (
        ('dark', 'phone', [390, 844], 30), ('light', 'desktop', [1200, 800], 220),
        ('dark', 'desktop', [1200, 800], 40), ('light', 'phone', [390, 844], 230),
    ):
        width, height = viewport
        data = _png(width, height, tone)
        pictures[f'{theme} / {device} / z8'] = data
        entry = write(f'qa/{GEN}/shots/{theme}-{device}-z8.png', data)
        entries.append(entry | {'path': Path(entry['path']).relative_to(Path('qa', GEN)).as_posix(),
                                'theme': theme, 'device': device, 'zoom': 8, 'viewport': viewport,
                                'navigation_visible': True})
    report = {'status': 'PASS', 'release_sha256': release_ref['sha256'],
              'shots': {'renderer': 'mb08-chart', 'cameras': [8], 'entries': entries}}
    review = f'review/{GEN}/envelope.json'

    def bind():
        qa_ref = write(f'qa/{GEN}/qa.json', receipts.canonical(report))
        write(review, receipts.canonical({'schema': envelope.ENVELOPE_SCHEMA, 'region': REGION, 'generation': GEN,
                                          'release': release_ref, 'qa': qa_ref, 'layers': release['layers']}))

    bind()
    return root / review, report, pictures, bind


def _run(review):
    return subprocess.run([sys.executable, '-B', str(CLI), '--envelope', str(review)],
                          cwd=review.parents[3], capture_output=True, text=True, timeout=10)


class Gallery(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.tags, self.images, self.captions, self.text = [], [], [], []
        self.policies = []
        self.caption = False
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        self.tags.append(tag)
        if tag == 'img':
            self.images.append(dict(attrs))
        if tag == 'meta' and dict(attrs).get('http-equiv') == 'Content-Security-Policy':
            self.policies.append(dict(attrs)['content'])
        if tag == 'figcaption':
            self.caption = True

    def handle_endtag(self, tag):
        if tag == 'figcaption':
            self.caption = False

    def handle_data(self, data):
        self.text.append(data)
        if self.caption:
            self.captions.append(data)


def test_gallery_pairs_exact_pngs_with_labels_and_escapes_source_text(snapshot):
    """Catch shuffled payloads, interpolated markup, remote assets and copied R8 verdicts."""
    review, _, pictures, _ = snapshot
    result = _run(review)
    assert result.returncode == 0, result.stderr
    assert result.stderr == ''
    gallery = Gallery(result.stdout)
    assert gallery.captions == sorted(pictures)
    assert len(gallery.images) == len(gallery.captions) == 4
    for caption, image in zip(gallery.captions, gallery.images, strict=True):
        assert set(image) == {'src', 'alt'}
        assert image['alt'] == caption
        assert image['src'].startswith('data:image/png;base64,')
        assert b64decode(image['src'].split(',', 1)[1], validate=True) == pictures[caption]
    # An absent or CSP-blocked stylesheet leaves the 1200px PNG at its intrinsic width on phones.
    styles = re.findall(r'<style>(.*?)</style>', result.stdout, re.DOTALL)
    assert len(styles) == 1, 'expected a stylesheet to constrain wide captures'
    css = styles[0]
    assert css.split() == (
        'body { overflow-wrap: anywhere; } '
        'figure { margin-inline: 0; min-inline-size: 0; } '
        'figure img { max-inline-size: 100%; block-size: auto; }'
    ).split()
    style_hash = b64encode(sha256(css.encode('utf-8')).digest()).decode('ascii')
    assert gallery.policies == [f"default-src 'none'; img-src data:; style-src 'sha256-{style_hash}'; base-uri 'none'"]
    assert set(gallery.tags) <= {'html', 'meta', 'style', 'title', 'h1', 'p', 'br', 'h2', 'ul', 'li', 'figure',
                                 'figcaption', 'img'}
    assert ' '.join(f'{SOURCE} — {ATTRIBUTION}'.splitlines()) in gallery.text
    assert f'Region: {REGION}' in gallery.text
    assert f'Generation: {GEN}' in gallery.text
    assert f'Envelope SHA-256: {receipts.sha256_bytes(review.read_bytes())}' in gallery.text
    assert not any(line.startswith('APPROVED release ') for line in result.stdout.splitlines())


@pytest.mark.parametrize(('damage', 'reason'), [
    ('swap', 'capture hash differs'),  # same-viewport valid PNG substituted for the listed one
    ('missing-file', 'artifact is missing'),  # a listing without its last PNG must not yield partial HTML
    ('missing-row', 'incomplete QA camera/theme/device inventory'),  # a rebound subset is not a complete matrix
    ('wrong-cameras', 'does not list the fixed release cameras'),  # the QA camera list cannot redefine completeness
    ('absent', 'QA capture inventory is absent'),  # absent shots cannot be treated as a successful empty gallery
    ('duplicate', 'invalid or duplicate'),  # length alone cannot prove matrix completeness
    ('extra-file', 'unlisted file'),  # an out-of-inventory capture must not be silently accepted
    ('too-many', 'exceeds 12 PNGs'),  # refuse rather than truncate a large QA inventory
    ('symlink', 'symlink in artifact path'),  # matching bytes outside the generation cannot bypass path rules
    ('changed-layer', 'layer hash or size changed'),  # independently enforce the shared R8 layer binding
    ('replaced-qa', 'qa.json does not match envelope'),  # don't trust labels from an unbound QA report
    ('json-size', 'JSON exceeds its read limit'),  # reject a bound but oversized QA report before verification
    ('png-size', 'exceeds its read limit'),  # don't accept over-limit input even when its digest matches
    ('viewport', 'decoded size differs'),  # header dimensions must match the existing labelled device
    ('inflated', 'decoded size differs'),  # correct header and CRCs cannot hide excess decoded scanlines
])
def test_refuses_without_any_html(snapshot, damage, reason):
    review, report, pictures, bind = snapshot
    root = review.parents[2]
    qa_dir = root / 'qa' / GEN
    entries = report['shots']['entries']
    path = qa_dir / entries[-1]['path']  # damage the final row to expose streamed partial output
    if damage == 'swap':
        path.write_bytes(pictures['dark / phone / z8'])
    elif damage == 'missing-file':
        path.unlink()
    elif damage == 'missing-row':
        entries.pop()
        bind()
    elif damage == 'wrong-cameras':
        report['shots']['cameras'] = [9]
        bind()
    elif damage == 'absent':
        report.pop('shots')
        bind()
    elif damage == 'duplicate':
        entries[-1] = entries[0].copy()
        bind()
    elif damage == 'extra-file':
        path.with_name('unlisted.png').write_bytes(path.read_bytes())
    elif damage == 'too-many':
        entries.extend(entries * 3)
        bind()
    elif damage == 'symlink':
        other = root.parent / 'outside.png'
        path.rename(other)
        path.symlink_to(other)
    elif damage == 'changed-layer':
        (root / package.ARCHIVE).write_bytes(b'Synthetic archive')
    elif damage == 'replaced-qa':
        report['note'] = 'unbound replacement'
        (qa_dir / 'qa.json').write_bytes(receipts.canonical(report))
    elif damage == 'json-size':
        report['note'] = 'x' * (4 * 1024 * 1024)
        bind()
    else:
        data = {'png-size': lambda: path.read_bytes() + b'\0' * (4 * 1024 * 1024),
                'viewport': lambda: _png(391, 844, 55),
                'inflated': lambda: _png(390, 844, 55, rows=845)}[damage]()
        path.write_bytes(data)
        entries[-1]['sha256'] = receipts.sha256_bytes(data)
        bind()
    result = _run(review)
    assert result.returncode == 1
    assert result.stdout == ''
    assert reason in result.stderr
