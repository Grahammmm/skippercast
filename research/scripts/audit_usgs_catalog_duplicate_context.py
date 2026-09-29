"""Check whether another USGS catalog reconstructs already-shown habitat.

The overlap is a provenance crosswalk, not new mapped area or fishing evidence.
Both layers must be research-only and MPA-screened before comparison.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime, timezone
import json
from pathlib import Path

from pyproj import Transformer
from shapely.geometry import shape
from shapely.ops import transform, unary_union
from shapely.strtree import STRtree


def audit(candidate, coast_shards):
    if candidate.get('scope') != 'generalized-statewide-usgs-hard-bottom-context':
        raise ValueError('Wrong candidate context')
    to_m = Transformer.from_crs('EPSG:4326', 'EPSG:3310', always_xy=True).transform
    originals = []
    for shard in coast_shards:
        if shard.get('scope') != candidate['scope']:
            raise ValueError('Wrong existing context scope')
        for feature in shard['features']:
            if feature['properties'].get('fishing_target') is not False:
                raise ValueError('Existing context contains a fishing target')
            if feature['properties'].get('release_id'):
                originals.append((transform(to_m, shape(feature['geometry'])),
                                  feature['properties']['release_id']))
    if not originals:
        raise ValueError('No published DOI-sourced context')
    geoms = [row[0] for row in originals]
    tree = STRtree(geoms)
    groups = defaultdict(lambda: {'outlines': 0, 'fully_contained_outlines': 0,
                                  'overlap_fraction_min': 1., 'doi_release_ids': set()})
    for feature in candidate['features']:
        props = feature['properties']
        if props.get('fishing_target') is not False or props.get('exportable') is not False:
            raise ValueError('Candidate context contains a fishing target')
        ident = props['block_id']
        polygon = transform(to_m, shape(feature['geometry']))
        hits = [int(i) for i in tree.query(polygon)
                if polygon.intersects(geoms[int(i)])]
        overlap = polygon.intersection(unary_union([geoms[i] for i in hits])).area if hits else 0
        fraction = overlap / polygon.area if polygon.area else 0
        group = groups[ident]
        group['outlines'] += 1
        group['fully_contained_outlines'] += int(fraction >= .9999)
        group['overlap_fraction_min'] = min(group['overlap_fraction_min'], fraction)
        group['doi_release_ids'].update(originals[i][1] for i in hits)
    rows = [{'block_id': ident, **{key: value for key, value in row.items()
            if key != 'doi_release_ids'}, 'doi_release_ids': sorted(row['doi_release_ids'])}
            for ident, row in sorted(groups.items())]
    return {'schema_version': 1, 'scope': 'usgs-csmp-vs-published-doi-context',
            'checked_at': datetime.now(timezone.utc).isoformat(),
            'candidate_catalog_url': candidate['source_catalog_url'],
            'candidate_outlines': len(candidate['features']),
            'fully_contained_outlines': sum(r['fully_contained_outlines'] for r in rows),
            'method': 'Intersect each projected MPA-screened CSMP context outline with the union of existing DOI-sourced browse context shapes; report per-outline area containment, never add overlapping counts as new seabed.',
            'fishing_target': False,
            'blocks': rows}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--candidate', type=Path, required=True)
    parser.add_argument('--shards', type=Path, default=Path('dist/data'))
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    data = json.loads(args.candidate.read_text())
    coasts = [json.loads((args.shards / f'usgs-hard-context-{name}.geojson').read_text())
              for name in ('northern', 'mendocino', 'san-francisco', 'central', 'southern')]
    result = audit(data, coasts)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + '\n')
    print(f"{result['fully_contained_outlines']}/{result['candidate_outlines']} CSMP outlines already within published DOI context")


if __name__ == '__main__':
    main()
