"""Shared CI orchestration; all geography comes from the catalog and ledger."""
import argparse
import json
from pathlib import Path

from skippercast.platform.contracts import REPO, read_json
from . import state_cache
from .io import sha256
from .publish import credentials, upload
from .restore import restore_reference
from .run import run, apply_ledger
from .screen_sources import refresh


def select(root, region=None, reach=None):
    rows = read_json(Path(root)/'dist/data/seafloor-ledger.json')['reaches']
    if reach:
        selected = [r for r in rows if r['id'] == reach and (not region or r['region'] == region)]
    else:
        selected = [r for r in rows if r['status'] != 'unassessed' and (not region or r['region'] == region)]
    if not selected:
        raise ValueError('No processed reaches in requested scope; qualify a reach before publishing')
    return selected


def prepare(root, region=None, reach=None):
    s3, bucket = credentials()
    selected = select(root, region, reach)
    # Publication rebuilds complete affected regions, including unchanged peers.
    regions = sorted({r['region'] for r in selected})
    # A failed/cancelled refresh must not leave an older legal-screen pass live.
    for name in regions:
        s3.put_object(Bucket=bucket, Key=f'tiles/seafloor/manifest-{name}.json',
            Body=b'{"status":"updating"}', ContentType='application/json', CacheControl='no-store')
    all_rows = read_json(Path(root)/'dist/data/seafloor-ledger.json')['reaches']
    rows = [r for r in all_rows if r['region'] in regions and
            (r['status'] != 'unassessed' or r['id'] == reach)]
    state_cache.restore(s3, bucket, root, 'shared')
    for row in rows:
        state_cache.restore(s3, bucket, root, row['id'])
    reference = Path(root)/'var/seafloor/reference/cells.json'
    expected = read_json(Path(root)/'dist/data/seafloor-ledger.json')['reference_cells_sha256']
    if not reference.exists() or sha256(reference) != expected:
        restore_reference(root=root, fetch=True)
    try:
        refresh(root=root)
    except Exception:
        for name in regions:
            s3.put_object(Bucket=bucket, Key=f'tiles/seafloor/manifest-{name}.json',
                Body=b'{"status":"held","reason":"screen-refresh-failed"}',
                ContentType='application/json', CacheControl='no-store')
        raise
    state_cache.save(s3, bucket, root, 'shared', state_cache.shared_paths(root))
    # Refresh changes the snapshot timestamp/hash, therefore every assessed
    # reach in these regions has a changed screening input. Workers still use
    # run()'s exact hash/no-op check; no terrain or grade is invented by the job.
    return {'include': [{'reach': row['id'], 'region': row['region']} for row in rows]}


def process(root, reach):
    s3, bucket = credentials()
    state_cache.restore(s3, bucket, root, reach)
    state_cache.restore(s3, bucket, root, 'shared')
    receipt, unchanged = run(reach, root=root, fetch=True)
    state_cache.save(s3, bucket, root, reach, state_cache.reach_paths(root, reach))
    # Review receipts are private even though their habitat will be public.
    folder = Path(root)/'var/seafloor/reaches'/reach
    for name in ('run.json', 'atlas-comparison.json'):
        s3.put_object(Bucket=bucket, Key=f'seafloor-review/{reach}/{receipt["input_hash"]}/{name}',
            Body=(folder/name).read_bytes(), ContentType='application/json', CacheControl='private, no-store')
    return {'reach': reach, 'unchanged': unchanged, 'tier2_km2': receipt['ledger_summary']['tier2_km2']}


def finish(root, matrix):
    s3, bucket = credentials()
    state_cache.restore(s3, bucket, root, 'shared')
    before = read_json(Path(root)/'dist/data/seafloor-ledger.json')
    for row in matrix['include']:
        ident = row['reach']
        if not state_cache.restore(s3, bucket, root, ident):
            raise ValueError('Missing completed reach state')
        receipt = read_json(Path(root)/'var/seafloor/reaches'/ident/'run.json')
        apply_ledger(Path(root), ident, receipt['ledger_summary'])
    results = [upload(region, root=root) for region in sorted({r['region'] for r in matrix['include']})]
    after = read_json(Path(root)/'dist/data/seafloor-ledger.json')
    old = {r['id']: r for r in before['reaches']}
    lines = ['Automated screened seafloor update. No fish-presence claim.', '',
             '| Reach | Tier 1 km² before → after | Tier 2 km² before → after |',
             '| --- | ---: | ---: |']
    for row in after['reaches']:
        prior = old[row['id']]
        if row != prior:
            lines.append(f"| {row['id']} | {prior['tier1_km2']:.6f} → {row['tier1_km2']:.6f} | "
                         f"{prior['tier2_km2']:.6f} → {row['tier2_km2']:.6f} |")
    lines += ['', 'Zero area delta means refreshed screening/provenance only. Source grids and review receipts remain private.',
              'Validation: current source hashes, full-polygon spatial screening, PMTiles build and R2 byte read-back.']
    destination = Path(root)/'var/seafloor/ledger-pr.md'
    destination.write_text('\n'.join(lines)+'\n')
    delta = after['totals']['tier2_km2']-before['totals']['tier2_km2']
    return {'published': [r['key'] for r in results], 'title': f'Refresh seafloor ledger ({delta:+.3f} km² tier 2)'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage', choices=('prepare', 'run', 'finish'))
    parser.add_argument('--region')
    parser.add_argument('--reach')
    parser.add_argument('--matrix', type=Path)
    args = parser.parse_args()
    if args.stage == 'prepare':
        result = prepare(REPO, args.region, args.reach)
    elif args.stage == 'run':
        result = process(REPO, args.reach)
    else:
        result = finish(REPO, read_json(args.matrix))
    print(json.dumps(result))


if __name__ == '__main__':
    main()
