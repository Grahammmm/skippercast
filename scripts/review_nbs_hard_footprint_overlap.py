"""Join the complete displayed-hard tile audit to original USGS class grids.

The output is a closure-screened physical-source review, not fishing targets.
It fails closed on missing/old MPA or federal-area snapshots.
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

from scripts.audit_nbs_modeling_tile import sha256
from scripts.inventory_nbs_hard_footprint_tiles import COASTS
from scripts.review_nbs_hard_overlap import build


def compile_review(inventory, inventory_path, depth, depth_path, scheme, cache, hard_dir,
                   usgs_audit, usgs_audit_path, usgs_cache, map_audit, map_audit_path,
                   map_cache, mpas, federal):
    if (inventory.get('scope') != 'noaa-nbs-tiles-intersecting-displayed-usgs-hard-context'
            or depth.get('scope') != 'noaa-nbs-hard-footprint-native-depth-source-audit'
            or depth.get('status') != 'complete' or depth.get('failed_tiles')
            or depth['inventory_sha256'] != sha256(inventory_path)
            or depth['scheme_sha256'] != sha256(scheme)
            or inventory['scheme_sha256'] != sha256(scheme)):
        raise ValueError('Complete hash-bound NOAA footprint and depth audits required')
    receipts = {row['tile']: row for row in depth['tiles']}
    if len(receipts) != inventory['tile_count'] or len(receipts) != len(depth['tiles']):
        raise ValueError('Missing or duplicate NOAA tile receipts')
    output = []
    for coast in COASTS:
        path = hard_dir / f'usgs-hard-context-{coast}.geojson'
        context = json.loads(path.read_text())
        sectors = {}
        for lead in inventory['tiles']:
            if coast not in lead['coasts']:
                continue
            receipt = receipts[lead['tile']]
            if receipt['coasts'] != lead['coasts'] or receipt['planning_sector_ids'] != lead['planning_sector_ids']:
                raise ValueError('Tile attribution changed: ' + lead['tile'])
            primary = next((sid for sid in lead['planning_sector_ids']
                            if any(f['properties'].get('sector_id') == sid for f in context['features'])),
                           lead['planning_sector_ids'][0])
            sectors.setdefault(primary, []).append({'tile': lead['tile'],
                'source_audit': {'raster_sha256': receipt['raster_sha256'],
                                 'rat_sha256': receipt['rat_sha256']}})
        pseudo = {'scope': 'coast-nbs-hard-footprint-depth-source-audit',
                  'scheme_sha256': depth['scheme_sha256'], 'failed_tiles': [],
                  'sectors': [{'sector_id': sid, 'reviewed_tiles': choices}
                              for sid, choices in sorted(sectors.items())]}
        review = build(pseudo, scheme, cache, context, path, usgs_audit,
                       usgs_audit_path, usgs_cache, mpas, federal,
                       map_audit=map_audit, map_audit_path=map_audit_path,
                       map_cache=map_cache)
        output.append({'coast_id': coast, 'tile_count': sum(len(s['tiles']) for s in review['sectors']),
                       'source_review': review})
    return {'schema_version': 1, 'scope': 'california-nbs-displayed-hard-footprint-original-class-review',
            'reviewed_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
            'inventory_sha256': sha256(inventory_path), 'depth_audit_sha256': sha256(depth_path),
            'scheme_sha256': sha256(scheme), 'fishing_target': False, 'exportable': False,
            'status': 'research-leads-only',
            'limitations': ['Only selected generalized historical USGS hard display polygons enter this tile queue; empty coasts are unknown, not soft bottom.',
                            'Tile-level original class/depth pixels may overlap neighboring NOAA tiles and are not unique reef acreage.',
                            'Current fish presence, contributor reports, chart hazards, route safety, species rules and local legal clearance remain separate gates.'],
            'coasts': output}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--inventory', type=Path, default=Path('dist/data/nbs-hard-footprint-tile-inventory.json'))
    parser.add_argument('--depth', type=Path, default=Path('dist/data/nbs-hard-footprint-depth-audit.json'))
    parser.add_argument('--scheme', type=Path, default=Path('var/modeling-tile-scheme-20260923.gpkg'))
    parser.add_argument('--cache', type=Path, default=Path('var/nbs-cache'))
    parser.add_argument('--hard-dir', type=Path, default=Path('dist/data'))
    parser.add_argument('--usgs-audit', type=Path, default=Path('var/usgs-doi-native-audit.json'))
    parser.add_argument('--usgs-cache', type=Path, default=Path('var/usgs-doi-native-cache'))
    parser.add_argument('--map-audit', type=Path, default=Path('var/usgs-native-audit.json'))
    parser.add_argument('--map-cache', type=Path, default=Path('var/usgs-native-cache'))
    parser.add_argument('--mpas', type=Path, default=Path('var/review/latest-coastal-snapshot.json'))
    parser.add_argument('--federal', type=Path, default=Path('var/review/latest-noaa-federal.json'))
    parser.add_argument('--output', type=Path, default=Path('var/review/nbs-hard-footprint-original-class-overlap.json'))
    args = parser.parse_args()
    result = compile_review(json.loads(args.inventory.read_text()), args.inventory,
        json.loads(args.depth.read_text()), args.depth, args.scheme, args.cache,
        args.hard_dir, json.loads(args.usgs_audit.read_text()), args.usgs_audit,
        args.usgs_cache, json.loads(args.map_audit.read_text()), args.map_audit,
        args.map_cache, json.loads(args.mpas.read_text()), json.loads(args.federal.read_text()))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(args.output.suffix + '.tmp')
    temporary.write_text(json.dumps(result, indent=2) + '\n')
    temporary.replace(args.output)
    for coast in result['coasts']:
        tiles = [tile for sector in coast['source_review']['sectors'] for tile in sector['tiles']]
        print(coast['coast_id'], len(tiles), 'tiles',
              sum(tile['strict_1m_original_class3_unique_pixels'] for tile in tiles),
              'tile-level strict original-class pixels', flush=True)


if __name__ == '__main__':
    main()
