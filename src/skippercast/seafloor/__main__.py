"""Rebuild the shared reference baseline or read the small committed ledger."""
import argparse
import json
from pathlib import Path

from skippercast.platform.contracts import REPO, read_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    add = commands.add_parser('add-survey', help='Inspect an original URL and write a private candidate draft')
    add.add_argument('--url', required=True)
    add.add_argument('--id')
    add.add_argument('--bounds', type=float, nargs=4, required=True, metavar=('W', 'S', 'E', 'N'))
    add.add_argument('--format', choices=('bag', 'usgs-geotiff'))
    add.add_argument('--member', default='unknown')
    add.add_argument('--local', type=Path)
    add.add_argument('--fetch', action='store_true')
    for command in ('reaches', 'ledger'):
        sub = commands.add_parser(command)
        sub.add_argument('--region', default='central-coast')
        if command == 'reaches':
            sub.add_argument('--fetch', action='store_true', help='Allow missing pinned reference assets to download')
        else:
            sub.add_argument('--json', action='store_true')
    args = parser.parse_args()
    try:
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
        print('Provisional band km² | original surveys not yet processed')
        print(f'{"Reach":48} {"Band":>9} {"Tier 1":>9} {"Tier 2":>9}')
        for row in records:
            print(f'{row["id"]:48} {row["band_km2"]:9.3f} {row["tier1_km2"]:9.3f} {row["tier2_km2"]:9.3f}')
        print(f'{"TOTAL":48} {sum(r["band_km2"] for r in records):9.3f} '
              f'{sum(r["tier1_km2"] for r in records):9.3f} {sum(r["tier2_km2"] for r in records):9.3f}')
    except (ValueError, FileNotFoundError) as error:
        parser.exit(1, f'Seafloor: {error}\n')


if __name__ == '__main__':
    main()
