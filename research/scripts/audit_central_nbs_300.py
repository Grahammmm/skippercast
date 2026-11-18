"""Re-screen pinned central-coast NBS tiles at 300 ft as source leads only.

This does not grant fishing, chart, substrate, or legal clearance. The source
review fixes tile identities and SHA-256 digests before any network fetch.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

from research.scripts.audit_nbs_modeling_tile import audit


CENTRAL_SECTORS = frozenset({'monterey-sur', 'big-sur', 'sur-san-simeon'})
EXIT_INCOMPLETE = 3


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build(review, scheme, cache, *, workers=4, fetch=False):
    if review.get('scope') != 'coast-nbs-multiple-rocky-camera-tile-source-review':
        raise ValueError('A pinned central coast camera-tile review is required')
    if review.get('scheme_sha256') != digest(scheme) or review.get('failed_tiles'):
        raise ValueError('The source review or tile scheme is incomplete or changed')
    if review.get('coast') != 'central':
        raise ValueError('The source review must declare the central coast')
    review_sectors = review.get('sectors')
    if not review_sectors or {sector.get('sector_id') for sector in review_sectors} != CENTRAL_SECTORS:
        raise ValueError('The source review sectors do not match the central coast sectors')
    expected = {}
    sectors = {}
    for sector in review_sectors:
        sector_id = sector['sector_id']
        if sector_id in sectors:
            raise ValueError('Duplicate sector ' + sector_id)
        if not sector['reviewed_tiles']:
            raise ValueError('No reviewed tiles for sector ' + sector_id)
        sectors[sector_id] = []
        for item in sector['reviewed_tiles']:
            tile = item['tile']
            source = item['source_audit']
            pair = (source['raster_sha256'], source['rat_sha256'])
            if tile in expected and expected[tile] != pair:
                raise ValueError('Conflicting pinned source for ' + tile)
            expected[tile] = pair
            sectors[sector_id].append(tile)

    if not expected:
        raise ValueError('The source review lists no tiles to screen')
    for key in ('requested_unique_tiles', 'audited_unique_tiles'):
        if review.get(key) != len(expected):
            raise ValueError(f'The source review {key} does not match its reviewed tiles')

    def screen(tile):
        row = audit(scheme, tile, cache, fetch=fetch, limit_ft=300)
        if (row['raster_sha256'], row['rat_sha256']) != expected[tile]:
            raise ValueError('Pinned source changed for ' + tile)
        return row

    results, failures = {}, {}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        jobs = {pool.submit(screen, tile): tile for tile in sorted(expected)}
        for job in as_completed(jobs):
            tile = jobs[job]
            try:
                results[tile] = job.result()
            except Exception as error:
                failures[tile] = type(error).__name__ + ': ' + str(error)
    complete = bool(expected) and not failures and len(results) == len(expected)
    return {
        'schema_version': 1,
        'scope': 'central-nbs-300ft-original-source-screen',
        'reviewed_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'status': 'complete-source-screen' if complete else 'incomplete-source-screen',
        'depth_ft': [25, 300],
        'scheme_sha256': digest(scheme),
        'source_review_sha256': None,
        'requested_unique_tiles': len(expected),
        'screened_unique_tiles': len(results),
        'failed_tiles': dict(sorted(failures.items())),
        'sectors': [{
            'sector_id': sector_id,
            'tiles': [results[tile] for tile in tiles if tile in results],
            'missing_tiles': [tile for tile in tiles if tile not in results],
        } for sector_id, tiles in sectors.items()],
        'fishing_target': False,
        'exportable': False,
        'limitations': [
            'NOAA NBS Modeling is a test-and-evaluation compilation, not a navigation chart.',
            'Depth-qualified pixels are source leads; original survey, native substrate, relief, closures, hazards and routes remain separate gates.',
            'Counts include overlapping tiles and cannot be added as unique seafloor area.',
        ],
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--review', type=Path, default=Path('research/receipts/nbs-central-gap-all-camera-tiles-review.json'))
    parser.add_argument('--scheme', type=Path, required=True)
    parser.add_argument('--cache', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--workers', type=int, default=4)
    parser.add_argument('--fetch', action='store_true')
    args = parser.parse_args(argv)
    if not 1 <= args.workers <= 8:
        raise ValueError('workers must be 1–8')
    result = build(json.loads(args.review.read_text()), args.scheme, args.cache,
                   workers=args.workers, fetch=args.fetch)
    result['source_review_sha256'] = digest(args.review)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(args.output.suffix + '.tmp')
    temporary.write_text(json.dumps(result, indent=2) + '\n')
    temporary.replace(args.output)
    print(result['status'], result['screened_unique_tiles'], '/', result['requested_unique_tiles'])
    return 0 if result['status'] == 'complete-source-screen' else EXIT_INCOMPLETE


if __name__ == '__main__':
    sys.exit(main())
