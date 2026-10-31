"""Report every discovered region's regulatory checks in the scheduled job."""
import argparse
import json
import os
from pathlib import Path


def _region_lines(ident, data):
    legal_review = data['rules_review_status'] == 'reviewed' and data['valid_for_current_date']
    affected = [p['name'] for p in data['species'].values() if p['issues'] or not legal_review]
    areas = [p['name'] for p in data['areas'].values() if p['issues'] or not legal_review]
    lines = [f"### {ident}", f"Jurisdiction: {data['jurisdiction_id']} · reviewed {data['reviewed_at']} · valid through {data['valid_through']}",
             f"Required sources: {len(data['checks']) - len(data['review_required'])}/{len(data['checks'])} match; legal content: {data['rules_review_status']}; review valid for today: {data['valid_for_current_date']}.",
             'Species requiring review or a fresh check: ' + (', '.join(affected) or 'none'),
             'Area notices requiring a fresh rule check: ' + (', '.join(areas) or 'none'),
             'Source review is not live military, harbor or entrance clearance.', '']
    for source_id in data['review_required']:
        s = data['checks'][source_id]
        lines.append(f"- {source_id}: {s['status']} · {s['source_status']} · checked {s.get('checked_at')}")
    return lines, bool(affected or areas or data['review_required'])


def report(root):
    try:
        regions = json.loads((root / 'regions/index.json').read_text())['regions']
        if not isinstance(regions, list):
            raise TypeError('regions is not a list')
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError) as exc:
        raise SystemExit(f'regions/index.json unreadable: {type(exc).__name__}') from None
    lines = ['## Regulation coverage', '']
    needs_attention = False
    unreadable = []
    for position, region in enumerate(regions):
        ident = region.get('region_id') if isinstance(region, dict) else None
        if not isinstance(ident, str):
            unreadable.append(str(position))
            continue
        try:
            section, attention = _region_lines(ident, json.loads((root / 'regions' / ident / 'regulations-health.json').read_text()))
        except FileNotFoundError:
            problem = 'missing'
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError, AttributeError) as exc:
            problem = f'unreadable ({type(exc).__name__}: {str(exc)[:120]})'
        else:
            lines.extend(section)
            needs_attention |= attention
            continue
        lines.extend([f'### {ident}', f"regulations-health.json {problem}; this region's rules were not checked.", ''])
        unreadable.append(ident)
    return '\n'.join(lines) + '\n', needs_attention or bool(unreadable), unreadable


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root', type=Path, required=True)
    args = p.parse_args()
    markdown, attention, unreadable = report(args.root)
    print(markdown)
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'], 'a') as stream:
            stream.write(markdown)
    if attention:
        print('::warning::Regulatory sources or content need review. Affected species withhold season-open status; consult the regional report.')
    if unreadable:
        print(f"::error::Regulation health unreadable for: {', '.join(unreadable)}")
        raise SystemExit(1)
