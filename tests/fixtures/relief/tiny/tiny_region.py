#!/usr/bin/env python3
"""The ``tiny`` relief fixture: three synthetic grids and a four-stage receipt chain.

    python3 tests/fixtures/relief/tiny/tiny_region.py <OUT>
    python3 scripts/relief/region.py status --region tiny --out <OUT>

The grids are written by a small pure-Python GeoTIFF writer (no GDAL), so the bytes are
the same on every machine and no binary file is committed:

* ``projected_1m.tif``: 24 x 24 Float32, 1 m cells, EPSG:26910 (UTM 10N), no vertical datum,
  nodata -9999 with a 3 x 3 hole in the middle.
* ``geographic_1m.tif``: 24 x 24 Float32, about 1 m cells (1.1e-5 deg x 9.0e-6 deg),
  EPSG:4269 (NAD83 geographic), nodata -9999 with a 2 x 3 hole.
* ``bluetopo_like_3band.tif``: 16 x 16, 4 m cells, EPSG:26910 + NAVD88 (EPSG:5703) height,
  three Float32 bands named Elevation, Uncertainty and Contributor like a BlueTopo tile,
  nodata 1000000 in every band over a 2 x 4 block.

Values are invented (elevation-up metres sloping from -2 m to about -20 m near Morro Bay);
they are not survey data and carry no rights. The chain (inventory -> normalize -> select ->
mosaic.public) are stand-in stages that only list and hash; they exist to exercise
``skippercast.relief.receipts`` and ``region.py status``, not to transform data.
"""
from array import array
import json
from pathlib import Path
import struct
import sys

try:
    from skippercast.relief import receipts
except ImportError:  # run from a plain checkout
    sys.path.insert(0, str(Path(__file__).resolve().parents[4] / 'src'))
    from skippercast.relief import receipts

REGION = 'tiny'
CODE_LABEL = 'tests/fixtures/relief/tiny/tiny_region.py'
ORDER = ('inventory', 'normalize', 'select', 'mosaic.public')

# TIFF field types: SHORT, LONG, DOUBLE, ASCII.
SHORT, LONG, DOUBLE, ASCII = 3, 4, 12, 2
_PACK = {SHORT: 'H', LONG: 'I', DOUBLE: 'd'}


def _entry(tag, kind, values):
    if kind == ASCII:
        payload = values.encode('ascii') + b'\0'
        return tag, kind, len(payload), payload
    return tag, kind, len(values), struct.pack('<%d%s' % (len(values), _PACK[kind]), *values)


def geotiff(width, height, bands, *, origin, pixel, geokeys, nodata, descriptions=None):
    """Bytes of an uncompressed little-endian GeoTIFF, one strip, pixel-interleaved Float32."""
    spp = len(bands)
    pixels = array('f', (bands[b][r * width + c] for r in range(height) for c in range(width) for b in range(spp)))
    if sys.byteorder != 'little':
        pixels.byteswap()
    data = pixels.tobytes()
    keys = sorted(geokeys)
    directory = [1, 1, 0, len(keys)] + [v for key, value in keys for v in (key, 0, 1, value)]
    entries = [
        _entry(256, LONG, [width]), _entry(257, LONG, [height]), _entry(258, SHORT, [32] * spp),
        _entry(259, SHORT, [1]), _entry(262, SHORT, [1]), _entry(273, LONG, [0]),
        _entry(277, SHORT, [spp]), _entry(278, LONG, [height]), _entry(279, LONG, [len(data)]),
        _entry(284, SHORT, [1]), _entry(339, SHORT, [3] * spp),
        _entry(33550, DOUBLE, [pixel[0], pixel[1], 0.0]),
        _entry(33922, DOUBLE, [0.0, 0.0, 0.0, origin[0], origin[1], 0.0]),
        _entry(34735, SHORT, directory), _entry(42113, ASCII, nodata),
    ]
    if spp > 1:
        entries.append(_entry(338, SHORT, [0] * (spp - 1)))
    if descriptions:
        items = ''.join(f'  <Item name="DESCRIPTION" sample="{i}" role="description">{d}</Item>\n'
                        for i, d in enumerate(descriptions))
        entries.append(_entry(42112, ASCII, f'<GDALMetadata>\n{items}</GDALMetadata>'))
    entries.sort()
    ifd_size = 2 + 12 * len(entries) + 4
    cursor = 8 + ifd_size
    placed = []
    for tag, kind, count, payload in entries:
        if len(payload) > 4:
            cursor += cursor % 2
            placed.append((tag, kind, count, payload, cursor))
            cursor += len(payload)
        else:
            placed.append((tag, kind, count, payload, None))
    strip = cursor + (-cursor % 8)
    out = bytearray(b'II' + struct.pack('<HI', 42, 8) + struct.pack('<H', len(placed)))
    for tag, kind, count, payload, offset in placed:
        if tag == 273:
            payload = struct.pack('<I', strip)
        field = payload.ljust(4, b'\0') if offset is None else struct.pack('<I', offset)
        out += struct.pack('<HHI', tag, kind, count) + field
    out += struct.pack('<I', 0)
    for _tag, _kind, _count, payload, offset in placed:
        if offset is not None:
            out += b'\0' * (offset - len(out)) + payload
    out += b'\0' * (strip - len(out)) + data
    return bytes(out)


def _grid(width, height, fn, hole, nodata):
    return [nodata if (r, c) in hole else round(fn(r, c), 2) for r in range(height) for c in range(width)]


def _block(rows, cols):
    return {(r, c) for r in rows for c in cols}


def grids():
    """name -> GeoTIFF bytes for the three fixture grids."""
    utm = [(1024, 1), (1025, 1), (3072, 26910), (3076, 9001)]
    hole = _block(range(10, 13), range(10, 13))
    projected = geotiff(24, 24, [_grid(24, 24, lambda r, c: -(2 + 0.5 * c + 0.25 * r), hole, -9999.0)],
                        origin=(694000.0, 3920024.0), pixel=(1.0, 1.0), geokeys=utm, nodata='-9999')
    hole = _block(range(4, 6), range(18, 21))
    geographic = geotiff(24, 24, [_grid(24, 24, lambda r, c: -(2 + 0.5 * c + 0.25 * r), hole, -9999.0)],
                         origin=(-120.87, 35.37), pixel=(1.1e-05, 9.0e-06),
                         geokeys=[(1024, 2), (1025, 1), (2048, 4269), (2054, 9102)], nodata='-9999')
    hole, nd = _block(range(0, 2), range(0, 4)), 1000000.0
    bands = [_grid(16, 16, lambda r, c: -(5 + 0.75 * c + 0.5 * r), hole, nd),
             _grid(16, 16, lambda r, c: 0.25 + 0.02 * r, hole, nd),
             _grid(16, 16, lambda r, c: 101.0 if c < 8 else 202.0, hole, nd)]
    bluetopo = geotiff(16, 16, bands, origin=(693900.0, 3920100.0), pixel=(4.0, 4.0),
                       geokeys=utm + [(4096, 5703), (4099, 9001)], nodata='1000000',
                       descriptions=['Elevation', 'Uncertainty', 'Contributor'])
    return {'projected_1m.tif': projected, 'geographic_1m.tif': geographic, 'bluetopo_like_3band.tif': bluetopo}


def write_grids(dest):
    """Write the grids into ``dest`` (existing files are left alone); return name -> path."""
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    paths = {}
    for name, data in grids().items():
        path = dest / name
        if not path.exists():
            path.write_bytes(data)
        paths[name] = path
    return paths


def _write(path, doc):
    path.write_text(json.dumps(doc, indent=1, sort_keys=True) + '\n', encoding='utf-8')


def stage_runs(region, *, code_digest=None, params=None):
    """The four stand-in stages of the fixture chain as ``receipts.StageRun`` objects."""
    digest = code_digest or receipts.stage_digest([(CODE_LABEL, Path(__file__))])
    params = params or {}
    raw = region.dir / 'raw'

    def inventory(out):
        rows = [{'name': p.name, 'bytes': p.stat().st_size, 'sha256': receipts.sha256_file(p)}
                for p in sorted(raw.glob('*.tif'))]
        _write(out / 'inventory.json', {'files': rows})

    def normalize(out):
        files = json.loads((region.dir / 'inventory' / 'inventory.json').read_text())['files']
        for row in files:
            _write(out / (row['name'] + '.json'), {'source_sha256': row['sha256'], 'stand_in': True})

    def select(out):
        names = sorted(p.name for p in (region.dir / 'normalize').glob('*.json'))
        _write(out / 'selection.json', {'selected': names, 'stand_in': True})

    def mosaic(out):
        selection = json.loads((region.dir / 'select' / 'selection.json').read_text())
        _write(out / 'manifest.json', {'scope': 'public', 'from': selection['selected'], 'stand_in': True})

    plan = receipts.Plan(inputs=[receipts.Input(raw / n, 'grid') for n in sorted(grids())],
                         params={'roots': ['raw'], **params.get('inventory', {})})
    return {
        'inventory': receipts.StageRun(region, 'inventory', inventory, digest, plan=plan),
        'normalize': receipts.StageRun(region, 'normalize', normalize, digest, upstream=[receipts.Ref('inventory')],
                                       plan=receipts.Plan(params={'crs': 'source', **params.get('normalize', {})})),
        'select': receipts.StageRun(region, 'select', select, digest, upstream=[receipts.Ref('normalize')],
                                    plan=receipts.Plan(params=params.get('select', {}))),
        'mosaic.public': receipts.StageRun(region, 'mosaic', mosaic, digest, scope='public',
                                           upstream=[receipts.Ref('select')],
                                           plan=receipts.Plan(params={'cell_m': 10, **params.get('mosaic', {})})),
    }


def build_chain(out_root, **run_kwargs):
    """Write the grids into ``OUT/tiny/raw`` and run the chain; return the ``Region``."""
    region = receipts.Region(out_root, REGION)
    write_grids(region.dir / 'raw')
    runs = stage_runs(region)
    for key in ORDER:
        result = receipts.run_stage(runs[key], **run_kwargs)
        if result.state not in ('ok', 'done'):
            raise RuntimeError(result.line())
    return region


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 1:
        print((__doc__ or '').strip())
        return 2
    region = build_chain(argv[0])
    print(f'wrote {region.dir}; now: python3 scripts/relief/region.py status --region {REGION} --out {argv[0]}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
