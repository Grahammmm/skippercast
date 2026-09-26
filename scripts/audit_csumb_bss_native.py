"""Inspect hash-pinned original Big Sur South grids as research evidence only."""
import argparse
import hashlib
import json
from pathlib import Path
import tarfile
import tempfile
from datetime import datetime, timezone
from urllib.parse import urlparse
from urllib.request import urlopen
from xml.etree import ElementTree

import numpy as np
import rasterio
from rasterio.warp import transform_bounds


ROOT = Path(__file__).resolve().parents[1]


def file_sha256(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for part in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(part)
    return h.hexdigest()


def acquire(spec, cache, fetch):
    path = cache / (spec['survey_id'] + '_additional_products.tar.gz')
    if not path.exists():
        if not fetch:
            raise FileNotFoundError(path)
        if urlparse(spec['archive_url']).scheme != 'https' or urlparse(spec['archive_url']).hostname != 'data.ngdc.noaa.gov':
            raise ValueError('Unreviewed archive source')
        cache.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix('.partial')
        try:
            with urlopen(spec['archive_url'], timeout=120) as response, temporary.open('wb') as output:
                if response.status != 200 or urlparse(response.url).hostname != 'data.ngdc.noaa.gov':
                    raise ValueError('Unexpected NOAA archive response')
                if int(response.headers.get('Content-Length', '-1')) != spec['archive_bytes']:
                    raise ValueError('NOAA archive size changed')
                while part := response.read(1024 * 1024):
                    output.write(part)
            if temporary.stat().st_size != spec['archive_bytes'] or file_sha256(temporary) != spec['archive_sha256']:
                raise ValueError('NOAA archive incomplete or changed')
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)
    if path.stat().st_size != spec['archive_bytes'] or file_sha256(path) != spec['archive_sha256']:
        raise ValueError('Cached NOAA archive does not match pinned original')
    return path


def metadata_value(bundle, grid, tag):
    member = bundle.getmember(grid + '/metadata.xml')
    root = ElementTree.fromstring(bundle.extractfile(member).read())
    values = [' '.join(''.join(node.itertext()).split()) for node in root.iter()
              if node.tag.rsplit('}', 1)[-1].lower() == tag]
    return values[0] if values else ''


def inspect_grid(bundle, grid, kind, tmp):
    prefix = grid + '/'
    members = [m for m in bundle.getmembers() if m.isfile() and m.name.startswith(prefix)]
    if not members or sum(m.size for m in members) > 100_000_000:
        raise ValueError('Expected bounded original Esri grid directory')
    for member in members:
        relative = Path(member.name)
        if relative.is_absolute() or '..' in relative.parts or not str(relative).startswith(prefix):
            raise ValueError('Unsafe original archive member')
        path = tmp / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(bundle.extractfile(member).read())
    with rasterio.open(tmp / grid) as dataset:
        if dataset.crs is None or dataset.count != 1 or dataset.width * dataset.height > 50_000_000:
            raise ValueError('Unexpected original grid geometry')
        cells = dataset.read(1, masked=True)
        values = cells.compressed()
        if not values.size:
            raise ValueError('Original grid contains no valid cells')
        mask = ~np.ma.getmaskarray(cells)
        rows = np.flatnonzero(mask.any(axis=1))
        cols = np.flatnonzero(mask.any(axis=0))
        left, top = dataset.transform * (int(cols[0]), int(rows[0]))
        right, bottom = dataset.transform * (int(cols[-1]) + 1, int(rows[-1]) + 1)
        result = {'grid': grid, 'crs': str(dataset.crs), 'resolution_m': list(dataset.res),
                  'bounds_native': list(dataset.bounds),
                  'valid_cell_envelope_wgs84': list(transform_bounds(dataset.crs, 'EPSG:4326', left, bottom, right, top)),
                  'valid_cells': int(values.size), 'minimum': float(values.min()), 'maximum': float(values.max())}
        if kind == 'habitat':
            code, count = np.unique(values, return_counts=True)
            result['class_counts'] = {str(int(k)): int(v) for k, v in zip(code, count)}
    result['process_description'] = metadata_value(bundle, grid, 'procdesc')
    result['access_constraints'] = metadata_value(bundle, grid, 'accconst')
    result['use_constraints'] = metadata_value(bundle, grid, 'useconst')
    return result


def audit(spec, cache, fetch=False):
    path = acquire(spec, cache, fetch)
    with tarfile.open(path, 'r:gz') as bundle, tempfile.TemporaryDirectory() as directory:
        member_names = [member.name for member in bundle.getmembers() if member.isfile()]
        uncertainty_products = [name for name in member_names if any(
            word in name.lower() for word in ('uncertainty', 'stddev', 'std_dev', 'cube_surface'))]
        tmp = Path(directory)
        bathy = inspect_grid(bundle, spec['bathymetry_grid'], 'bathymetry', tmp)
        habitat = inspect_grid(bundle, spec['habitat_grid'], 'habitat', tmp)
        with rasterio.open(tmp / spec['bathymetry_grid']) as depth_grid, rasterio.open(tmp / spec['habitat_grid']) as terrain_grid:
            depth = depth_grid.read(1, masked=True)
            terrain = terrain_grid.read(1, masked=True)
            if depth.shape != terrain.shape or depth_grid.transform != terrain_grid.transform:
                raise ValueError('Original depth and terrain grids do not align cell for cell')
            within_limit = (~np.ma.getmaskarray(depth) & (depth.data >= -60.96) & (depth.data < 0))
            rough = (~np.ma.getmaskarray(terrain) & np.isin(terrain.data, [-1, -31, -101, -201]))
            band_200_300 = (~np.ma.getmaskarray(depth) & (depth.data >= -91.44)
                            & (depth.data < -60.96))
            native_depth_screen = {
                'limit_ft': 200,
                'cells_within_limit': int(within_limit.sum()),
                'derived_rough_class_cells_within_limit': int((within_limit & rough).sum()),
                'basis': 'source NAVD88 elevation only; no chart-datum conversion or independent rock confirmation',
                'comparison_band_200_300ft_navd88_cells': int(band_200_300.sum()),
                'derived_rough_class_cells_in_comparison_band': int((band_200_300 & rough).sum()),
                'comparison_band_note': '2 m exported NAVD88 DEM cells only; not MLLW-qualified 200–300 ft coverage or verified rock',
            }
    if (bathy['crs'] != habitat['crs'] or bathy['bounds_native'] != habitat['bounds_native']
            or bathy['resolution_m'] != habitat['resolution_m']):
        raise ValueError('Original bathymetry and habitat grids do not align')
    if spec['native_vertical_datum'].lower() not in bathy['process_description'].lower():
        raise ValueError('Original bathymetry metadata does not confirm the declared datum')
    if 'rough and smooth habitat' not in habitat['process_description'].lower():
        raise ValueError('Original habitat-class semantics changed')
    if not bathy['access_constraints'].lower().startswith('to be determined'):
        raise ValueError('Original source constraints changed; review rights again')
    return {'source_id': spec['id'], 'producer': spec['producer'], 'archive_url': spec['archive_url'],
            'documentation_url': spec['documentation_url'], 'archive_sha256': spec['archive_sha256'],
            'native_vertical_datum': spec['native_vertical_datum'], 'status': 'held-from-fishing-targets',
            'rights_status': spec['rights_status'], 'reason': spec['limitations'],
            'bathymetry': bathy, 'terrain_habitat': habitat,
            'archive_product_inventory': {
                'file_members': len(member_names),
                'named_uncertainty_or_cube_surface_products': uncertainty_products,
                'note': 'Filename inventory of this compact additional-products archive only; a CARIS source CUBE surface may exist outside it.',
            },
            'native_depth_screen': native_depth_screen}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, default=ROOT / 'catalog/csumb-bss-native-sources.json')
    parser.add_argument('--cache', type=Path, default=ROOT / 'var/noaa-native-cache')
    parser.add_argument('--output', type=Path, default=ROOT / 'dist/data/csumb-bss-native-source-review.json')
    parser.add_argument('--fetch', action='store_true')
    args = parser.parse_args()
    sources = json.loads(args.manifest.read_text())['sources']
    result = {'schema_version': 1, 'scope': 'original-csumb-bss-native-grid-review',
              'reviewed_at': datetime.now(timezone.utc).isoformat(),
              'publication_status': 'source-evidence-only',
              'sources': [audit(spec, args.cache, args.fetch) for spec in sources]}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix('.partial')
    temporary.write_text(json.dumps(result, separators=(',', ':')) + '\n')
    temporary.replace(args.output)
    print(json.dumps({'sources': len(sources), 'output': str(args.output)}))


if __name__ == '__main__':
    main()
