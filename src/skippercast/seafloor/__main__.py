"""Rebuild the shared reference baseline or read the small committed ledger."""
import argparse
import json
from pathlib import Path

from skippercast.platform.contracts import REPO, read_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    planning = commands.add_parser('plan', help='Show runnable reaches, source-review backlog and measured progress')
    planning.add_argument('--region')
    planning.add_argument('--max-new', type=int, default=3)
    planning.add_argument('--json', action='store_true')
    planning.add_argument('--physical-only', action='store_true', help='Include reviewed private sources; never grants publication')
    review = commands.add_parser('review-source', help='Checkpoint a bounded completed discovery test; never qualifies a survey')
    review.add_argument('--source', required=True)
    review.add_argument('--reaches', nargs='+', required=True)
    review.add_argument('--outcome', required=True, choices=('no-incremental-support',
                        'no-valid-shallow-support', 'already-qualified', 'needs-original-input', 'access-failed'))
    review.add_argument('--evidence', required=True)
    review.add_argument('--note', required=True)
    review.add_argument('--save-private', action='store_true', help='Save only the discovery checkpoint with existing private R2 credentials')
    commands.add_parser('refresh-screen', help='Refresh reviewed MPA, federal and security snapshots')
    adoption = commands.add_parser('adopt-private-physics', help='Transfer checked private physics after rights-only promotion; screen still required')
    adoption.add_argument('--reach', required=True)
    migration = commands.add_parser('migrate-numeric-cache', help='Verify old numeric-only caches; apply explicitly, retain recovery and require rescreening')
    migration.add_argument('--reach', required=True)
    migration.add_argument('--private', action='store_true')
    migration.add_argument('--apply', action='store_true')
    publication = commands.add_parser('publish', help='Build a screened regional PMTiles bundle; upload only with --upload')
    publication.add_argument('--region', required=True)
    publication.add_argument('--scope-config', type=Path, help='Explicit isolated scope config; publication remains disabled for non-central scopes')
    publication.add_argument('--upload', action='store_true')
    promotion = commands.add_parser('promote-survey', help='Promote a metadata/rights-reviewed native draft; changes the catalog')
    promotion.add_argument('--draft', type=Path, required=True)
    promotion.add_argument('--rights-url', required=True)
    promotion.add_argument('--physical-only', action='store_true', help='Qualify native evidence for private processing only; no rights or publication granted')
    add = commands.add_parser('add-survey', help='Inspect an original URL and write a private candidate draft')
    add.add_argument('--url', required=True)
    add.add_argument('--id')
    add.add_argument('--bounds', type=float, nargs=4, required=True, metavar=('W', 'S', 'E', 'N'))
    add.add_argument('--format', choices=('bag', 'usgs-geotiff', 'arcgrid'))
    add.add_argument('--member', default='unknown')
    add.add_argument('--local', type=Path)
    add.add_argument('--fetch', action='store_true')
    restore = commands.add_parser('restore-reference', help='Rebuild verified private cells without changing the ledger')
    restore.add_argument('--fetch', action='store_true')
    process = commands.add_parser('run', help='Measure native coverage and rank held habitat candidates')
    process.add_argument('--reach', required=True)
    process.add_argument('--physical-only', action='store_true', help='Cache measured habitat before legal review; never publish')
    process.add_argument('--force', action='store_true')
    process.add_argument('--fetch', action='store_true', help='Fetch missing reviewed originals; pinned hashes still required')
    process.add_argument('--scope-config', type=Path, help='Explicit scope config; non-central processing fails closed pending scoped source and screen contracts')
    for command in ('reaches', 'ledger'):
        sub = commands.add_parser(command)
        sub.add_argument('--region')
        sub.add_argument('--scope-config', type=Path, help='Explicit scope config; artifacts are isolated by scope')
        if command == 'reaches':
            sub.add_argument('--fetch', action='store_true', help='Allow missing pinned reference assets to download')
        else:
            sub.add_argument('--json', action='store_true')
    args = parser.parse_args()
    try:
        if args.command == 'review-source':
            from datetime import datetime, timezone
            from .source_review import record
            from .manifest import load_manifest
            result = record(REPO, load_manifest(REPO), args.source, args.reaches,
                args.outcome, args.evidence, now=datetime.now(timezone.utc), note=args.note)
            if args.save_private:
                from .jobs import credentials
                from .state_cache import save
                from .source_review import RELATIVE
                s3, bucket = credentials()
                save(s3, bucket, REPO, 'source-review', [REPO/RELATIVE])
                result['saved_private'] = True
            print(json.dumps(result, indent=2))
            return
        if args.command == 'plan':
            from .rollout import plan, report
            result = plan(region=args.region, max_new=args.max_new, physical_only=args.physical_only)
            print(json.dumps(result, indent=2) if args.json else report(result))
            return
        if args.command == 'publish':
            if args.scope_config:
                from .scope_paths import resolve_scope
                _, paths = resolve_scope(REPO, scope_config=args.scope_config)
                if not paths.is_central_default:
                    raise ValueError('Non-central publication is disabled until its scoped ingest, legal and screen contracts are reviewed')
            from .publish import build, upload
            if args.upload:
                print(json.dumps(upload(args.region), indent=2))
            else:
                folder, manifest = build(args.region, scope_config=args.scope_config)
                print(json.dumps({'directory': str(folder), **manifest}, indent=2))
            return
        if args.command == 'migrate-numeric-cache':
            from .migrate_cache import migrate_numeric_cache
            print(json.dumps(migrate_numeric_cache(args.reach, private=args.private, apply=args.apply), indent=2))
            return
        if args.command == 'adopt-private-physics':
            from .adopt import adopt_private
            print(json.dumps(adopt_private(args.reach), indent=2))
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
            if args.scope_config:
                from .scope_paths import resolve_scope
                _, paths = resolve_scope(REPO, scope_config=args.scope_config)
                if not paths.is_central_default:
                    raise ValueError('Non-central processing is disabled until scoped source, physical and screen contracts are reviewed')
            from .run import run
            receipt, reused = run(args.reach, force=args.force, fetch=args.fetch,
                                  physical_only=args.physical_only, scope_config=args.scope_config)
            print(json.dumps({'unchanged': reused, **receipt['ledger_summary']}, indent=2))
            return
        if args.command == 'promote-survey':
            from .manifest import promote_draft
            print('Qualified original survey: '+promote_draft(args.draft, rights_url=args.rights_url, physical_only=args.physical_only))
            return
        if args.command == 'add-survey':
            from .draft import add_survey
            path = add_survey(args.url, args.bounds, ident=args.id, format_name=args.format,
                              member=args.member, local=args.local, fetch=args.fetch)
            print(f'Candidate draft: {path}. Review rights and metadata before manifest promotion.')
            return
        if args.command == 'reaches':
            from .grid import build
            ledger, unchanged = build(fetch=args.fetch, region=args.region, scope_config=args.scope_config)
            if args.region is None:
                args.region = ledger['scope']
            print('Reference unchanged; no rebuild.' if unchanged else 'Rebuilt reference baseline; all cells tier 0.')
        else:
            from .scope_paths import resolve_scope
            config, paths = resolve_scope(REPO, scope_config=args.scope_config)
            ledger = read_json(paths.ledger_path)
            if args.region is None:
                args.region = config['id']
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
