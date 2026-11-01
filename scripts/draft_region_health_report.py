"""Report one draft region's legal and source health (draft-region-health.yml).

Exit 0 when healthy, 1 when the evidence needs review or no receipt exists,
2 on a usage error. A failed past-day landing report (`catches-*`) is not
counted as a source fetch failure: the 5-of-7-day coverage gate
(`critical_available`) decides whether missing reports matter.
"""
import argparse
import json
import os
from pathlib import Path

PAST_DAY_REPORT = 'catches-'


def main(argv=None):
    parser = argparse.ArgumentParser(description='Report draft region legal and source health.')
    parser.add_argument('--region', required=True)
    parser.add_argument('--root', default='var/draft-rehearsal')
    parser.add_argument('--summary', default=os.environ.get('GITHUB_STEP_SUMMARY'))
    args = parser.parse_args(argv)
    if not args.summary:
        parser.error('--summary or GITHUB_STEP_SUMMARY is required')
    region = args.region
    root = Path(args.root) / region / 'regions' / region
    if not (root / 'latest.json').is_file():
        raise SystemExit('Draft collector produced no regional receipt')
    evidence = json.loads((root / 'latest.json').read_text())
    rules = json.loads((root / 'regulations-health.json').read_text())
    health = evidence['health']
    unknown = [ident for ident in health['issues'] if ident not in evidence['sources']]
    if unknown:
        raise SystemExit(f"Draft evidence names unknown sources: {', '.join(unknown)}")
    fetch_failed = [ident for ident in health['issues']
                    if evidence['sources'][ident]['status'] in ('failed', 'retained')]
    past_day = [ident for ident in fetch_failed if ident.startswith(PAST_DAY_REPORT)]
    source_failures = [ident for ident in fetch_failed if ident not in past_day]
    with open(args.summary, 'a') as out:
        out.write(f"## {region} draft rehearsal\n")
        out.write(f"{health['sources_ok']}/{health['sources_total']} sources healthy; legal source changes or failures: {len(rules['review_required'])}; source fetch failures: {len(source_failures)}.\n")
        if past_day:
            out.write(f'Past-day landing reports that failed: {len(past_day)} (left to the 5-of-7 coverage gate).\n')
        out.write('This is unpublished source evidence, not fishing permission or site clearance.\n')
        for issue in health['issues']:
            out.write(f'- {issue}\n')
    if rules['review_required'] or source_failures or not health['critical_available']:
        raise SystemExit('Draft evidence needs review before regional promotion')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
