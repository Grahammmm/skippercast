#!/usr/bin/env python3
"""Render one local R8 capture inventory as a standalone HTML photo book."""
import argparse
from base64 import b64encode
from html import escape
from pathlib import Path
import struct
import sys
import zlib

if __name__ == '__main__':
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'src'))

from skippercast.relief import envelope, package, qa, receipts

MAX_SHOTS = 12
MAX_JSON_BYTES = 4 * 1024 * 1024
MAX_PNG_BYTES = 4 * 1024 * 1024
MAX_LAYER_BYTES = 2_000_000_000  # includes the R7 archive budget plus other public layers
PNG_SIGNATURE = b'\x89PNG\r\n\x1a\n'
# Fixed-size color/physical metadata only; no APNG frames or compressed metadata.
PNG_METADATA = {b'sRGB': 1, b'gAMA': 4, b'cHRM': 32, b'pHYs': 9}


def _read(path, limit):
    with path.open('rb') as stream:
        raw = stream.read(limit + 1)
    if len(raw) > limit:
        raise package.ReleaseError(f'{path.name} exceeds its read limit')
    return raw


def _verify(path):
    if (len(path.parents) < 3 or path.name != 'envelope.json' or path.parents[1].name != 'review'
            or '..' in path.parts or not package.is_sha256(path.parent.name)):
        raise package.ReleaseError('expected a local review/<generation>/envelope.json')
    root, gen = path.parents[2], path.parent.name
    reviews = f'review/{gen}/envelope.json'
    release_path = f'release/{gen}/release.json'
    qa_path = f'qa/{gen}/qa.json'
    review_file, release_file, qa_file = (package.artifact_path(root, relative)
                                         for relative in (reviews, release_path, qa_path))
    # Preflight the stable, offline artifact tree before the shared verifier's
    # JSON reads and streaming layer hashes. Never read layers into the gallery.
    if any(file.stat().st_size > MAX_JSON_BYTES for file in (review_file, release_file, qa_file)):
        raise package.ReleaseError('envelope, release or QA JSON exceeds its read limit')
    layers = package.release_layers(package.decode_document(_read(release_file, MAX_JSON_BYTES)))
    total = 0
    for row in layers:
        total += row['bytes']
        if (total > MAX_LAYER_BYTES
                or package.artifact_path(root, row['path']).stat().st_size != row['bytes']):
            raise package.ReleaseError('release layer exceeds the read limit or differs in size')
    verified = envelope.verify_artifacts(path)
    raw = _read(qa_file, MAX_JSON_BYTES)
    if receipts.sha256_bytes(raw) != verified.qa_sha256:
        raise package.ReleaseError('qa.json does not match envelope')
    return root, verified, package.decode_document(raw)


def _check_png(raw, viewport):
    """Check Chromium's 8-bit RGB/RGBA PNG profile and bound decoded scanlines."""
    problem = package.ReleaseError('invalid PNG capture or decoded size differs from viewport')
    if raw[:16] != PNG_SIGNATURE + b'\0\0\0\rIHDR' or len(raw) < 33:
        raise problem
    width, height, bits, color, compression, filter_method, interlace = struct.unpack_from('>IIBBBBB', raw, 16)
    if ([width, height] != viewport or bits != 8 or color not in (2, 6)
            or any((compression, filter_method, interlace))):
        raise problem
    channels = 3 if color == 2 else 4
    stride = 1 + width * channels
    limit = height * stride  # viewport is selected from QA's fixed device table
    data = memoryview(raw)
    pixels = bytearray()
    in_idat = False
    allowed_metadata = PNG_METADATA | {b'sBIT': channels}
    metadata = set()
    start = len(PNG_SIGNATURE)
    while start + 12 <= len(data):
        size, kind = struct.unpack_from('>I4s', data, start)
        end = start + 12 + size
        if end > len(data) or zlib.crc32(data[start + 4:end - 4]) != struct.unpack_from('>I', data, end - 4)[0]:
            raise problem
        if start == len(PNG_SIGNATURE):
            pass  # IHDR was checked above
        elif kind == b'IDAT':
            in_idat = True
            pixels.extend(data[start + 8:end - 4])
        elif kind == b'IEND' and size == 0 and end == len(data):
            break
        elif not in_idat and size == allowed_metadata.get(kind) and kind not in metadata:
            metadata.add(kind)
        else:
            raise problem
        start = end
    else:
        raise problem
    decoder = zlib.decompressobj()
    try:
        scanlines = decoder.decompress(pixels, limit + 1)
    except zlib.error as exc:
        raise problem from exc
    if (len(scanlines) != limit or not decoder.eof or decoder.unused_data
            or any(code > 4 for code in scanlines[::stride])):
        raise problem


def _photos(root, verified, report):
    shots = report.get('shots')
    if not isinstance(shots, dict) or not isinstance(shots.get('entries'), list) or not shots['entries']:
        raise package.ReleaseError('QA capture inventory is absent or empty')
    entries = shots['entries']
    if len(entries) > MAX_SHOTS:
        raise package.ReleaseError(f'QA capture inventory exceeds {MAX_SHOTS} PNGs')
    low, high = (int(verified.release[key]) for key in ('minzoom', 'maxzoom'))
    # Same fixed cameras and cross-product as the R7 QA producer. Do not infer
    # completeness from the listed rows (or display any camera coordinates).
    cameras = sorted({z for z in (low, 10, 13, 15, high) if low <= z <= high})
    if shots.get('renderer') != 'mb08-chart' or shots.get('cameras') != cameras:
        raise package.ReleaseError('QA capture inventory does not list the fixed release cameras')
    expected = {(z, t, d) for z in cameras for t in qa.THEMES for d in qa.DEVICES}
    if len(entries) != len(expected):
        raise package.ReleaseError('incomplete QA camera/theme/device inventory')
    paths, hashes, photos = set(), set(), []
    generation = f'qa/{verified.generation}'
    for row in entries:
        if (not isinstance(row, dict) or type(row.get('zoom')) is not int
                or not all(isinstance(row.get(key), str) for key in ('theme', 'device', 'path'))
                or not package.is_sha256(row.get('sha256'))):
            raise package.ReleaseError('invalid QA capture entry')
        z, t, d = key = (row['zoom'], row['theme'], row['device'])
        path = f'shots/{t}-{d}-z{z}.png'
        if (key not in expected or row['path'] != path or row.get('viewport') != qa.DEVICES[d]
                or row.get('navigation_visible') is not True or row['sha256'] in hashes):
            raise package.ReleaseError('invalid or duplicate QA camera/theme/device entry')
        expected.remove(key)
        paths.add(Path(path).name)
        hashes.add(row['sha256'])
        raw = _read(package.artifact_path(root, f'{generation}/{path}'), MAX_PNG_BYTES)
        if receipts.sha256_bytes(raw) != row['sha256']:
            raise package.ReleaseError(f'capture hash differs: {path}')
        _check_png(raw, qa.DEVICES[d])
        photos.append((z, t, d, raw))
    # Do not scan the region or other generations. Also refuse stray files in
    # this exact inventory directory; traversal stops at the first extra entry.
    if any(file.name not in paths for file in (root / generation / 'shots').iterdir()):
        raise package.ReleaseError('unlisted file in QA capture inventory')
    return sorted(photos)


def _render(verified, photos):
    release = verified.release
    lines = [
        '<!doctype html>', '<html lang="en">', '<meta charset="utf-8">',
        "<meta http-equiv=\"Content-Security-Policy\" content=\"default-src 'none'; img-src data:; base-uri 'none'\">",
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        '<title>Central R8 photo book</title>', '<h1>Central R8 photo book</h1>',
        '<p>Captured QA evidence for inspection only. Not for navigation or release approval.</p>',
        f'<p>Region: {escape(release["region"])}<br>Generation: {escape(verified.generation)}'
        f'<br>Envelope SHA-256: {escape(verified.envelope_sha256)}</p>',
        '<h2>Release sources</h2>', '<ul>',
        *('<li>' + escape(' '.join(f'{row["id"]} — {row["attribution"]}'.splitlines())) + '</li>'
          for row in release['sources']),
        '</ul>', '<h2>Captures</h2>',
    ]
    for zoom, theme, device, raw in photos:
        label = escape(f'{theme} / {device} / z{zoom}')
        lines.extend(('<figure>', f'<figcaption>{label}</figcaption>',
                      f'<img alt="{label}" src="data:image/png;base64,{b64encode(raw).decode("ascii")}">',
                      '</figure>'))
    return '\n'.join([*lines, '</html>'])


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--envelope', required=True, type=Path,
                        help='one review/<generation>/envelope.json in a stable local artifact tree')
    args = parser.parse_args(argv)
    try:
        root, verified, report = _verify(args.envelope)
        document = _render(verified, _photos(root, verified, report))
    except (OSError, ValueError, RecursionError) as exc:
        print('Photo book refused: ' + ' '.join(str(exc).splitlines()), file=sys.stderr)
        return 1
    print(document)
    return 0


if __name__ == '__main__':
    sys.exit(main())
