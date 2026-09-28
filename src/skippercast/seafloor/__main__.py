"""Rebuild the shared reference baseline or read the small committed ledger."""
import argparse
import json
from pathlib import Path

from skippercast.platform.contracts import REPO, read_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('refresh-screen', help='Refresh reviewed MPA, federal and security snapshots')
    publication = commands.add_parser('publish', help='Build a screened regional PMTiles bundle; upload only with --upload')
    publication.add_argument('--region', required=True)
    publication.add_argument('--upload', action='store_true')
    add = commands.add_parser('add-survey', help='Inspect an original URL and write a private candidate draft')
    add.add_argument('--url', required=True)
    add.add_argument('--id')
    add.add_argument('--bounds', type=float, nargs=4, required=True, metavar=('W', 'S', 'E', 'N'))
    add.add_argument('--format', choices=('bag', 'usgs-geotiff'))
    add.add_argument('--member', default='unknown')
    add.add_argument('--local', type=Path)
    add.add_argument('--fetch', action='store_true')
    restore = commands.add_parser('restore-reference', help='Rebuild verified private cells without changing the ledger')
    restore.add_argument('--fetch', action='store_true')
    process = commands.add_parser('run', help='Measure native coverage and rank held habitat candidates')
    process.add_argument('--reach', required=True)
    process.add_argument('--force', action='store_true')
    process.add_argument('--fetch', action='store_true', help='Fetch missing reviewed originals; pinned hashes still required')
    for command in ('reaches', 'ledger'):
        sub = commands.add_parser(command)
        sub.add_argument('--region', default='central-coast')
        if command == 'reaches':
            sub.add_argument('--fetch', action='store_true', help='Allow missing pinned reference assets to download')
        else:
            sub.add_argument('--json', action='store_true')
    args = parser.parse_args()
    try:
        if args.command == 'publish':
            from .publish import build, upload
            if args.upload:
                print(json.dumps(upload(args.region), indent=2))
            else:
                folder, manifest = build(args.region)
                print(json.dumps({'directory': str(folder), **manifest}, indent=2))
            return
        if args.command == 'refresh-screen':
            from .screen_sources import refresh
            result = refresh()
            print(json.dumps({'checked_at': result['checked_at'], 'layers': list(result['layers'])}))
            return
        if args.command == 'restore-reference':
            from .restore import restore_reference
            print(f'Restored verified reference cells: {restore_reference(fetch=args.fetch)}')
            return
        if args.command == 'run':
            from .run import run
            receipt, reused = run(args.reach, force=args.force, fetch=args.fetch)
            print(json.dumps({'unchanged': reused, **receipt['ledger_summary']}, indent=2))
            return
        if args.command == 'add-survey':
            from .draft import add_survey
            path = add_survey(args.url, args.bounds, ident=args.id, format_name=args.format,
                              member=args.member, local=args.local, fetch=args.fetch)
            print(f'Candidate draft: {path}. Review rights and metadata before manifest promotion.')
            return
        if args.command == 'reaches':
            from .grid import build
            ledger, unchanged = build(fetch=args.fetch, region=args.region)
            print('Reference unchanged; no rebuild.' if unchanged else 'Rebuilt reference baseline; all cells tier 0.')
        else:
            ledger = read_json(REPO / 'dist/data/seafloor-ledger.json')
        known = {r['region'] for r in ledger['reaches']}
        if args.region != ledger['scope'] and args.region not in known:
            parser.error('Unknown seafloor region')
        records = [r for r in ledger['reaches'] if args.region == ledger['scope'] or r['region'] == args.region]
        if getattr(args, 'json', False):
            print(json.dumps({'reference': ledger['reference'], 'reaches': records}, indent=2))
            return
        print('Provisional band km² | tier 1 = survey-qualified cells; tier 2 = screened habitat')
        print(f'{"Reach":48} {"Band":>9} {"Tier 1":>9} {"Tier 2":>9}')
        for row in records:
            print(f'{row["id"]:48} {row["band_km2"]:9.3f} {row["tier1_km2"]:9.3f} {row["tier2_km2"]:9.3f}')
        print(f'{"TOTAL":48} {sum(r["band_km2"] for r in records):9.3f} '
              f'{sum(r["tier1_km2"] for r in records):9.3f} {sum(r["tier2_km2"] for r in records):9.3f}')
    except (ValueError, FileNotFoundError) as error:
        parser.exit(1, f'Seafloor: {error}\n')


if __name__ == '__main__':
    main()
