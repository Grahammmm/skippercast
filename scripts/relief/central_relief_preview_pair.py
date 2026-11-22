"""Compare one exact XYZ tile in two existing Central Coast relief packages.

Run from the repo root with python -m scripts.relief.central_relief_preview_pair.
All paths are explicit and relative to --scratch-root (or absolute within it).
Use stable, local package copies; this does not run stages or check approvals.
"""
import argparse
from base64 import b64encode
from hashlib import sha256
from html import escape
from pathlib import Path
import struct
from zlib import error as ZlibError

from scripts.relief.central_camera_bounds import REGIONS
from skippercast.relief import envelope, package
from skippercast.seafloor.rough_first import read_tiles

# Cap the bytes admitted to envelope verification as well as the preview itself.
PACKAGE_LIMIT = 1_500_000_000  # QA's relief archive budget, here applied to all layers
ARCHIVE_LIMIT = 256 << 20  # read_tiles indexes the full archive, not just the selected address
DOCUMENT_LIMIT = 4 << 20
TILE_LIMIT = 1 << 20
PNG = b'\x89PNG\r\n\x1a\n\x00\x00\x00\x0dIHDR'


def _inside(root, path):
    path = root / path
    if '..' in path.parts or not path.is_relative_to(root) or path.resolve() != path:
        raise ValueError('paths must stay inside scratch root without symlinks or parent traversal')
    return path


def _size(path):
    if not path.is_file():
        raise ValueError(f'expected a regular file: {path.name}')
    return path.stat().st_size


def _verify(path, region):
    root, generation = path.parents[2], path.parent.name
    if root.name != region:
        raise ValueError(f'envelope must belong to selected Central region {region}')
    if (path.name != 'envelope.json' or path.parent.parent.name != 'review'
            or not package.is_sha256(generation)):
        raise ValueError('expected review/<generation>/envelope.json')
    release = package.artifact_path(root, f'release/{generation}/release.json')
    qa = package.artifact_path(root, f'qa/{generation}/qa.json')
    if any(_size(doc) > DOCUMENT_LIMIT for doc in (path, release, qa)):
        raise ValueError('envelope, release or QA document exceeds preview read budget')
    # Preflight actual layer sizes before the shared verifier hashes them.
    with release.open('rb') as stream:
        raw = stream.read(DOCUMENT_LIMIT + 1)
    if len(raw) > DOCUMENT_LIMIT:
        raise ValueError('release document exceeds preview read budget')
    rows = package.release_layers(package.decode_document(raw))
    sizes = {row['path']: _size(package.artifact_path(root, row['path'])) for row in rows}
    if sizes[package.ARCHIVE] > ARCHIVE_LIMIT:
        raise ValueError('relief archive exceeds preview read budget')
    if sum(sizes.values()) > PACKAGE_LIMIT:
        raise ValueError('package layers exceed preview read budget')
    return envelope.verify_artifacts(path)


def _selected_png(path, binding, xyz):
    if not 127 <= binding['bytes'] <= ARCHIVE_LIMIT:
        raise ValueError('relief archive exceeds preview read budget or is too short')
    with path.open('rb') as stream:
        archive = stream.read(binding['bytes'] + 1)
    if len(archive) != binding['bytes'] or sha256(archive).hexdigest() != binding['sha256']:
        raise ValueError('relief archive changed after verification')
    if archive[:8] != b'PMTiles\x03' or archive[97:100] != b'\x02\x01\x02':
        raise ValueError('expected PMTiles v3 with gzip directories and uncompressed PNG tiles')
    # As in QA, use views so indexing the archive does not copy all tile payloads.
    with memoryview(archive) as view:
        tiles = read_tiles(view)
        try:
            tile = tiles.get(xyz)
            if tile is None:
                return None
            if (not 33 <= len(tile) <= TILE_LIMIT or tile[:16] != PNG
                    or struct.unpack_from('>II', tile, 16) != (256, 256)):
                raise ValueError('selected tile is not a bounded 256×256 PNG')
            return bytes(tile)
        finally:
            # The reader's recursive walk can retain its dictionary until cycle collection.
            tiles.clear()


def _panel(label, path, verified, xyz):
    binding = next(row for row in verified.layers if row['path'] == package.ARCHIVE)
    archive = package.artifact_path(path.parents[2], package.ARCHIVE)
    png = _selected_png(archive, binding, xyz)
    if png is None:
        raster = '<p class="empty">Tile absent at the selected XYZ address</p>'
    else:
        encoded = b64encode(png).decode('ascii')
        raster = f'<img width="256" height="256" alt="{escape(label)} relief tile" src="data:image/png;base64,{encoded}">'
    return (f'<section><h2>{escape(label)}</h2>{raster}<dl>'
            f'<dt>Code commit</dt><dd>{escape(verified.release["code_sha"])}</dd>'
            f'<dt>Envelope SHA-256</dt><dd>{escape(verified.envelope_sha256)}</dd>'
            f'<dt>Relief archive SHA-256</dt><dd>{escape(binding["sha256"])}</dd>'
            f'<dt>Relief archive size</dt><dd>{binding["bytes"]} bytes</dd></dl></section>')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--scratch-root', required=True, type=Path)
    parser.add_argument('--region', required=True, choices=REGIONS)
    parser.add_argument('--xyz', required=True, type=int, nargs=3, metavar=('Z', 'X', 'Y'))
    parser.add_argument('--candidate-envelope', required=True, type=Path)
    parser.add_argument('--comparator-envelope', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path, help='new HTML file in scratch root')
    args = parser.parse_args(argv)
    z, x, y = xyz = tuple(args.xyz)
    if not (0 <= z <= 26 and 0 <= x < 1 << z and 0 <= y < 1 << z):
        parser.error('invalid XYZ address (expected Z X Y)')
    try:
        root = args.scratch_root.resolve(strict=True)
        if not root.is_dir():
            raise ValueError('expected a scratch directory')
        paths = [_inside(root, p) for p in (args.candidate_envelope, args.comparator_envelope)]
        output = _inside(root, args.output)
        verified = [_verify(path, args.region) for path in paths]
        panels = ''.join(_panel(label, path, item, xyz) for label, path, item in
                         zip(('Candidate', 'Comparator'), paths, verified, strict=True))
        with output.open('x', encoding='utf-8') as stream:
            stream.write(f'''<!doctype html>
<html lang="en"><meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src data:; style-src 'unsafe-inline'; base-uri 'none'">
<title>Central relief preview pair</title>
<style>
body {{ font: 1rem system-ui, sans-serif; }}
main {{ display: grid; grid-template-columns: repeat(2, minmax(256px, 22rem)); gap: 1rem; }}
img {{ display: block; }}
dd {{ margin-left: 0; overflow-wrap: anywhere; }}
.empty {{ margin: 0; width: 256px; height: 256px; display: grid; place-items: center; background: #eee; text-align: center; }}
</style>
<h1>Relief preview: {escape(args.region)} · XYZ (z/x/y) {z}/{x}/{y}</h1>
<p>Relief only. Measured support is unproved: neither panel independently proves measured coverage. Not for navigation.</p>
<main>{panels}</main>
</html>
''')
    except (ValueError, OSError, IndexError, RecursionError, struct.error, ZlibError) as exc:
        parser.error(str(exc))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
