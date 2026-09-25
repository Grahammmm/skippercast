"""Audit every inventoried NOAA tile intersecting displayed USGS hard context.

Receipts are retained per tile so an interrupted or partially failed run is
explicitly resumable. This only screens depth provenance, never fishing spots.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import json
from pathlib import Path

from scripts.audit_nbs_modeling_tile import audit, sha256, scheme_row


def atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, indent=2) + '\n')
    temporary.replace(path)


def validate(inventory, scheme):
    if inventory.get('scope') != 'noaa-nbs-tiles-intersecting-displayed-usgs-hard-context':
        raise ValueError('Expected exact hard-footprint inventory')
    if inventory['scheme_sha256'] != sha256(scheme):
        raise ValueError('NOAA scheme hash changed; regenerate and review inventory')
    if inventory['tile_count'] != len(inventory['tiles']):
        raise ValueError('Incomplete tile inventory')
    for lead in inventory['tiles']:
        row = scheme_row(scheme, lead['tile'])
        if (lead['raster_url'] != row['GeoTIFF_Link']
                or lead['contributor_table_url'] != row['RAT_Link']
                or lead['resolution'] != row['Resolution']):
            raise ValueError('Inventory tile identity differs from pinned NOAA scheme')


def run_one(lead, scheme, cache, receipts, fetch):
    tile = lead['tile']
    receipt_path = receipts / f'{tile}.json'
    if receipt_path.exists():
        previous = json.loads(receipt_path.read_text())
        if previous.get('tile') == tile and previous.get('scheme_sha256') == sha256(scheme):
            result = previous
        else:
            raise ValueError('Stale or mismatched receipt: ' + tile)
    else:
        result = audit(scheme, tile, cache, fetch=fetch)
        atomic_json(receipt_path, result)
    return {'tile': tile, 'coasts': lead['coasts'],
            'planning_sector_ids': lead['planning_sector_ids'],
            'resolution': lead['resolution'],
            'raster_sha256': result['raster_sha256'],
            'rat_sha256': result['rat_sha256'],
            'counts': result['counts'],
            'screen': result['screen']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--inventory', type=Path, default=Path('var/review/nbs-hard-footprint-tile-inventory.json'))
    parser.add_argument('--scheme', type=Path, default=Path('var/modeling-tile-scheme-20260923.gpkg'))
    parser.add_argument('--cache', type=Path, default=Path('var/nbs-cache'))
    parser.add_argument('--receipts', type=Path, default=Path('var/review/nbs-hard-footprint-receipts'))
    parser.add_argument('--output', type=Path, default=Path('var/review/nbs-hard-footprint-depth-audit.json'))
    parser.add_argument('--workers', type=int, default=4)
    parser.add_argument('--fetch', action='store_true')
    args = parser.parse_args()
    if not 1 <= args.workers <= 8:
        raise ValueError('workers must be 1–8')
    inventory = json.loads(args.inventory.read_text())
    validate(inventory, args.scheme)
    completed, failed = [], []
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        jobs = {executor.submit(run_one, lead, args.scheme, args.cache, args.receipts, args.fetch): lead
                for lead in inventory['tiles']}
        for future in as_completed(jobs):
            lead = jobs[future]
            try:
                completed.append(future.result())
            except Exception as exc:
                failed.append({'tile': lead['tile'], 'error': f'{type(exc).__name__}: {exc}'})
            report = {'schema_version': 1, 'scope': 'noaa-nbs-hard-footprint-native-depth-source-audit',
                      'audited_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
                      'inventory_sha256': sha256(args.inventory),
                      'scheme_sha256': inventory['scheme_sha256'],
                      'inventoried_tiles': inventory['tile_count'],
                      'completed_tiles': len(completed), 'failed_tiles': len(failed),
                      'status': 'complete' if len(completed) == inventory['tile_count'] and not failed else 'partial',
                      'fishing_target': False, 'exportable': False,
                      'limitations': ['Tiles intersect only selected generalized historical USGS display context, not full California hard substrate.',
                                      'A passing NOAA depth pixel does not establish hard bottom, legal access, a fishing spot or present catch.',
                                      'NOAA NBS Modeling is a test-and-evaluation source and does not replace current charts or original surveys.'],
                      'tiles': sorted(completed, key=lambda row: row['tile']),
                      'failures': sorted(failed, key=lambda row: row['tile'])}
            atomic_json(args.output, report)
            print(f"{len(completed) + len(failed)}/{inventory['tile_count']} complete={len(completed)} failed={len(failed)}", flush=True)
    if failed:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
