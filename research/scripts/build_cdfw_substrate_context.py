"""Publish coarse CDFW-predicted hard substrate as non-target atlas context.

Only patches of at least 100 valid predicted-hard 40 m cells survive this context view.
This source uses rugosity as a proxy, includes interpolated shallow gaps, and
must not be presented as native survey geology, a fishing point, or depth proof.
"""
import argparse
from collections import defaultdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

import lerc
from pyproj import Transformer
from rasterio.features import shapes
from rasterio.transform import from_origin
from shapely import STRtree, get_parts
from shapely.affinity import translate
from shapely.geometry import mapping, shape
from shapely.ops import transform, unary_union

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # repository root, for research.*
from research.scripts.build_usgs_statewide_context import mpa_union
from research.scripts.audit_cdfw_substrate_tiles import BASE, LEVEL, ORIGIN, RESOLUTION_M

MIN_CELLS = 100
PIXEL_AREA = RESOLUTION_M * RESOLUTION_M
TILE_SIZE = 256
MIN_AREA = MIN_CELLS * PIXEL_AREA


def _native_patches(tiles, cache):
    """Yield sized components and their anchor tiles, without a dense mosaic."""
    seam_parts, seam_tiles = [], []
    stride = TILE_SIZE * RESOLUTION_M
    for item in sorted(tiles, key=lambda item: (item['row'], item['col'])):
        if item['hard_cells'] == 0:
            continue
        row, col = item['row'], item['col']
        blob = (cache / str(LEVEL) / str(row) / f'{col}.lerc').read_bytes()
        if hashlib.sha256(blob).hexdigest() != item['sha256']:
            raise ValueError(f'CDFW tile hash changed: {row}/{col}')
        status, values, mask = lerc.decode(blob)
        if (status != 0 or values.shape != (TILE_SIZE, TILE_SIZE)
                or (mask is not None and mask.shape != values.shape)):
            raise ValueError(f'CDFW tile decode changed: {row}/{col}')
        hard = (values == 1) & (mask if mask is not None else True)
        # Work relative to the service origin so matching seam coordinates are
        # exact integer metres, independent of floating-point affine offsets.
        x, y = col * stride, -row * stride
        affine = from_origin(x, y, RESOLUTION_M, RESOLUTION_M)
        for geometry, _ in shapes(hard.astype('uint8'), mask=hard, transform=affine, connectivity=4):
            polygon = shape(geometry)
            if not polygon.is_valid:  # GDAL rings can touch at a pixel corner.
                polygon = polygon.buffer(0)
            xmin, ymin, xmax, ymax = polygon.bounds
            if xmin == x or ymin == y - stride or xmax == x + stride or ymax == y:
                seam_parts.append(polygon)
                seam_tiles.append(item)
            elif polygon.area >= MIN_AREA:
                yield polygon, item

    tree = STRtree(seam_parts)
    unseen = set(range(len(seam_parts)))
    for first, anchor in enumerate(seam_tiles):
        if first not in unseen:
            continue
        unseen.remove(first)
        pending, group = [first], []
        while pending:
            i = pending.pop()
            part = seam_parts[i]
            group.append(part)
            for j in tree.query(part, predicate='intersects'):
                # Native components have disjoint interiors. Within a tile they
                # cannot already share an edge; across tiles a point is not enough.
                if j in unseen and part.intersection(seam_parts[j]).length > 0:
                    unseen.remove(j)
                    pending.append(j)
        if sum(part.area for part in group) >= MIN_AREA:
            yield unary_union(group) if len(group) > 1 else group[0], anchor


def build(audit, mpas, coasts, cache):
    if audit.get('scope') != 'cdfw-ds3091-40m-tile-audit' or audit.get('failures') or audit.get('requested_tiles') != audit.get('audited_tiles'):
        raise ValueError('Complete audited CDFW ds3091 tile set is required')
    age = datetime.now(timezone.utc) - datetime.fromisoformat(audit['checked_at'])
    if not 0 <= age.total_seconds() < 30 * 86400:
        raise ValueError('CDFW substrate tile audit is stale')
    mpa_wgs = mpa_union(mpas)
    to_projected = Transformer.from_crs(4326, 3310, always_xy=True).transform
    to_wgs = Transformer.from_crs(3310, 4326, always_xy=True).transform
    # Keep a conservative 100 m display buffer because transformed long MPA
    # edges and later WGS84 serialization can otherwise leave tiny slivers.
    excluded = translate(transform(to_projected, mpa_wgs).buffer(100), -ORIGIN[0], -ORIGIN[1])
    rows = {coast['id']: [] for coast in coasts['regions']}
    ranks = defaultdict(int)
    for native, anchor in _native_patches(audit['tiles'], cache):
        projected = native.simplify(RESOLUTION_M / 2, preserve_topology=True)
        # Generalize inward only; simplification must not fill nodata or soft cells.
        if not native.covers(projected):
            projected = projected.intersection(native)
        legal = projected.difference(excluded) if projected.intersects(excluded) else projected
        row, col = anchor['row'], anchor['col']
        for part in get_parts(legal):
            if part.geom_type != 'Polygon' or part.area < MIN_AREA:
                continue
            wgs = transform(to_wgs, translate(part, *ORIGIN))
            latitude = wgs.centroid.y
            matches = [coast['id'] for coast in coasts['regions'] if coast['latitude'][0] <= latitude < coast['latitude'][1]]
            if len(matches) != 1:
                continue
            ranks[row, col] += 1
            rows[matches[0]].append({'type': 'Feature', 'geometry': mapping(wgs), 'properties': {
                'id': f'cdfw-ds3091-{LEVEL}-{row}-{col}-{ranks[row, col]}', 'source': 'CDFW ds3091 predicted substrate',
                'source_url': BASE, 'metadata_url': audit['metadata_url'],
                'source_tile_sha256': anchor['sha256'], 'source_class': 'Predicted hard (rugosity proxy)',
                'display_resolution_m': RESOLUTION_M, 'approx_area_m2': round(part.area),
                'fishing_target': False, 'exportable': False, 'depth_qualified': False,
                'fish_confirmed': False, 'mpa_screened_at': mpas['sources']['mpas']['data_retrieved_at']}})
    return {coast: {'type': 'FeatureCollection', 'schema_version': 1,
                    'scope': 'cdfw-predicted-hard-substrate-context', 'coast_id': coast,
                    'compiled_at': datetime.now(timezone.utc).isoformat(),
                    'source_catalog_url': audit['metadata_url'], 'source_service_url': BASE,
                    'method': ('CDFW ds3091 level-7 40 m LERC overview; edge-connected hard-class components >=100 cells across tiles, '
                               'simplified inward at 20 m tolerance, cut by current complete CDFW MPA polygons plus 100 m display buffer. '
                               'Tile ID and hash identify the first contributing tile of the native component in row/column order.'),
                    'limitations': ['Predicted rugosity proxy, not verified rock or native survey bathymetry.',
                                    'Source includes interpolated shallow gaps and varying original resolutions.',
                                    'Patches smaller than 0.16 km² are omitted; displayed borders are coarse.',
                                    'No fish presence, legal depth, catch success, or navigational accuracy is inferred.'],
                    'features': features} for coast, features in rows.items()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--audit', type=Path, default=Path('var/cdfw-ds3091-tile-audit.json'))
    parser.add_argument('--mpas', type=Path, default=Path('var/live-coastal-latest.json'))
    parser.add_argument('--coasts', type=Path, default=Path('dist/data/coasts.json'))
    parser.add_argument('--cache', type=Path, default=Path('var/cdfw-ds3091-tiles'))
    parser.add_argument('--output-dir', type=Path, default=Path('research/receipts'))
    args = parser.parse_args()
    outputs = build(json.loads(args.audit.read_text()), json.loads(args.mpas.read_text()),
                    json.loads(args.coasts.read_text()), args.cache)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    for coast, data in outputs.items():
        path = args.output_dir / f'cdfw-predicted-hard-{coast}.geojson'
        path.write_text(json.dumps(data, separators=(',', ':')) + '\n')
        print(coast, len(data['features']))


if __name__ == '__main__':
    main()
