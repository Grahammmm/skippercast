#!/usr/bin/env python3
"""Summarize one live-conditions cycle.

Publication failures and missing products fail the cycle. Degraded or missing
individual sources (a buoy spectrum, one satellite analysis) are expected on
most runs; they are reported as warnings so a red run always means the public
feed did not update.
"""
import argparse
import json
import os
from pathlib import Path

PRODUCTS = ('latest.json', 'regions/index.json', 'intelligence-health.json', 'habitat-health.json')


def summarize(output, outcome):
    """Return (markdown lines, failures, warnings) for one cycle."""
    lines, failures, warnings = ['## Regional evidence publication', 'Publication: ' + outcome], [], []
    if outcome != 'success':
        lines.append('This cycle did not confirm a new publication. The public feed remains the last confirmed generation.')
        failures.append('Publication was not confirmed')
    for name in PRODUCTS:
        path = Path(output) / name
        if not path.is_file():
            failures.append(name + ' was not produced')
            continue
        data = json.loads(path.read_text())
        if name == 'latest.json':
            lines.append('Buoy feed collected ' + data['completed_at'])
            for source in data['sources'].values():
                sample = (source.get('data') or {}).get('sample_at', 'unavailable')
                lines.append(f"- {source['name']}: {source['status']}; observed {sample}")
            warnings.extend(data['health']['issues'])
        else:
            lines.append('\n### ' + name)
            for region in data['regions']:
                lines.append('- ' + region['region_id'] + ': ' + region['status'])
                if region.get('error_class'):
                    lines.append(f"  - Refresh failed ({region['error_class']}): {region.get('error', '')}; "
                                 'its last publication stays in place')
                coverage = region.get('forecast_coverage')
                if coverage:
                    lines.append(f"  - Seven-day wind + seas: {coverage['rated_point_days']}/{coverage['point_days']} point-days; "
                                 f"two-model comparison: {coverage['two_model_point_days']}/{coverage['point_days']}")
                lines.extend('  - Source issue: ' + str(issue) for issue in region['issues'])
                lines.extend('  - Coverage gap: ' + str(gap) for gap in region.get('coverage_gaps', []))
                warnings.extend(region['issues'])
    if warnings:
        lines.append(f'\n{len(warnings)} source(s) degraded this cycle; the feed was still published with their last good values or gaps.')
    return lines, failures, sorted(set(map(str, warnings)))


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--output', default='var/live')
    parser.add_argument('--outcome', default=os.environ.get('PUBLICATION_OUTCOME', 'unknown'))
    args = parser.parse_args()
    lines, failures, warnings = summarize(args.output, args.outcome)
    summary = os.environ.get('GITHUB_STEP_SUMMARY')
    if summary:
        with open(summary, 'a') as handle:
            handle.write('\n'.join(lines) + '\n')
    for warning in warnings:
        print(f'::warning title=Degraded source::{warning}')
    if failures:
        raise SystemExit('Publication failed or products missing: ' + '; '.join(failures))
    print(f'Published; {len(warnings)} degraded source(s).')


if __name__ == '__main__':
    main()
