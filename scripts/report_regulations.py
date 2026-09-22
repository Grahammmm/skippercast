"""Report every discovered region's regulatory checks in the scheduled job."""
import argparse
import json
import os
from pathlib import Path


def report(root):
    index = json.loads((root / 'regions/index.json').read_text())
    lines = ['## Regulation coverage', '']
    needs_attention = False
    for region in index['regions']:
        ident = region['region_id']
        data = json.loads((root / 'regions' / ident / 'regulations-health.json').read_text())
        legal_review = data['rules_review_status'] == 'reviewed' and data['valid_for_current_date']
        affected = [p['name'] for p in data['species'].values() if p['issues'] or not legal_review]
        areas = [p['name'] for p in data['areas'].values() if p['issues'] or not legal_review]
        lines.extend([f"### {ident}", f"Jurisdiction: {data['jurisdiction_id']} · reviewed {data['reviewed_at']} · valid through {data['valid_through']}",
                      f"Required sources: {len(data['checks']) - len(data['review_required'])}/{len(data['checks'])} match; legal content: {data['rules_review_status']}; review valid for today: {data['valid_for_current_date']}.",
                      'Species requiring review or a fresh check: ' + (', '.join(affected) or 'none'),
                      'Area notices requiring a fresh rule check: ' + (', '.join(areas) or 'none'),
                      'Source review is not live military, harbor or entrance clearance.', ''])
        for source_id in data['review_required']:
            s = data['checks'][source_id]
            lines.append(f"- {source_id}: {s['status']} · {s['source_status']} · checked {s.get('checked_at')}")
        needs_attention |= bool(affected or areas or data['review_required'])
    return '\n'.join(lines) + '\n', needs_attention


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root', type=Path, required=True)
    args = p.parse_args()
    markdown, attention = report(args.root)
    print(markdown)
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'], 'a') as stream:
            stream.write(markdown)
    if attention:
        print('::warning::Regulatory sources or content need review. Affected species withhold season-open status; consult the regional report.')
