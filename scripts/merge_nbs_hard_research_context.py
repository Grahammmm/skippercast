"""Join reviewed Central Coast source leads without duplicating native-survey context.

All inputs remain optional historical research overlays, never fishing spots.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

from pyproj import Transformer
from shapely.geometry import shape
from shapely.ops import transform


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def merge(primary_path, addition_path, native_path):
    primary, addition, native = (json.loads(path.read_text()) for path in
                                 (primary_path, addition_path, native_path))
    if any(layer.get('type') != 'FeatureCollection' or layer.get('coast_id') != 'central'
           for layer in (primary, addition, native)):
        raise ValueError('Only reviewed Central Coast geometry can be combined')
    if primary['scope'] != addition['scope'] or native['scope'] != 'central-native-noaa-usgs-hard-bottom-context':
        raise ValueError('Source scope changed')
    if (primary['mpa_screened_at'] != addition['mpa_screened_at'] or
            primary['federal_screened_at'] != addition['federal_screened_at']):
        raise ValueError('Closure snapshots differ')
    if primary['maximum_screen_uncertainty_m'] < addition['maximum_screen_uncertainty_m']:
        raise ValueError('Addition exceeds published uncertainty policy')
    for layer in (primary, addition, native):
        if any(feature['properties'].get('fishing_target') is not False or
               feature['properties'].get('exportable') is not False for feature in layer['features']):
            raise ValueError('Only non-target research source layers can be merged')
    if set(primary['sector_ids']) & set(addition['sector_ids']):
        raise ValueError('Overlapping sector batches need separate review')
    to_m = Transformer.from_crs(4326, 3310, always_xy=True).transform
    existing = [transform(to_m, shape(item['geometry'])) for item in
                primary['features'] + native['features']]
    accepted, duplicate = [], []
    for feature in addition['features']:
        p = feature['properties']
        if any(p.get(key) is not False for key in
               ('legal_clearance', 'fish_confirmed', 'depth_qualified_for_target')):
            raise ValueError('Addition is not held from fishing promotion')
        area = transform(to_m, shape(feature['geometry']))
        if not area.is_valid or area.is_empty or area.area <= 0:
            raise ValueError('Invalid added display geometry')
        overlap = max((area.intersection(other).area / area.area for other in existing), default=0)
        if overlap >= .5:
            duplicate.append({'outline_id': p['id'], 'maximum_overlap_fraction': round(overlap, 3)})
        else:
            accepted.append(feature)
            existing.append(area)
    result = dict(primary)
    result['compiled_at'] = datetime.now(timezone.utc).isoformat()
    result['sector_ids'] = sorted(set(primary['sector_ids']) | set(addition['sector_ids']))
    result['features'] = primary['features'] + accepted
    result['source_layers'] = [{
        'path': str(path), 'sha256': digest(path), 'compiled_at': layer['compiled_at'],
        'screen_uncertainty_m': layer['maximum_screen_uncertainty_m'],
        'features': len(layer['features'])
    } for path, layer in ((primary_path, primary), (addition_path, addition))]
    result['native_duplicate_screen'] = {
        'source_path': str(native_path), 'sha256': digest(native_path),
        'overlap_threshold_fraction': .5, 'held_additions': duplicate,
    }
    result['method'] += ' Southern additions used a stricter 1 m uncertainty screen; outlines covering at least 50% of an existing original-survey display polygon were withheld as duplicate context.'
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--primary', type=Path, default=Path('dist/data/central-estero-nbs-usgs-hard-research-context.geojson'))
    parser.add_argument('--addition', type=Path, default=Path('dist/data/central-south-nbs-usgs-hard-research-context.geojson'))
    parser.add_argument('--native', type=Path, default=Path('dist/data/point-conception-native-hard-context.geojson'))
    parser.add_argument('--output', type=Path, default=Path('dist/data/central-nbs-usgs-hard-research-context.geojson'))
    args = parser.parse_args()
    result = merge(args.primary, args.addition, args.native)
    temporary = args.output.with_suffix(args.output.suffix + '.tmp')
    temporary.write_text(json.dumps(result, separators=(',', ':')) + '\n')
    temporary.replace(args.output)
    print(len(result['features']), 'research outlines;',
          len(result['native_duplicate_screen']['held_additions']), 'duplicate held')


if __name__ == '__main__':
    main()
