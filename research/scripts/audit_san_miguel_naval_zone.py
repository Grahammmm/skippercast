"""Verify the exact eCFR danger-zone source before research screening."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re

from shapely.geometry import Polygon
from skippercast.pipeline.collect import Client
from skippercast.pipeline.regulations import ecfr_section


def degrees(value):
    match = re.fullmatch(r'(\d{2,3})°(\d{2})′(\d{2})″', value)
    if not match:
        raise ValueError('Invalid official DMS vertex')
    degree, minute, second = map(int, match.groups())
    if minute >= 60 or second >= 60:
        raise ValueError('Invalid official DMS vertex')
    return degree + minute / 60 + second / 3600


def danger_polygon(manifest):
    if (manifest.get('id') != 'san-miguel-334-1140' or manifest.get('title') != 33
            or manifest.get('section') != '334.1140' or not manifest.get('research_only')
            or manifest.get('fishing_target') or manifest.get('exportable')):
        raise ValueError('Unreviewed San Miguel danger-zone scope')
    vertices = manifest['vertices_n_w']
    if len(vertices) != 8:
        raise ValueError('Expected eight eCFR vertices')
    polygon = Polygon([(-degrees(west), degrees(north)) for north, west in vertices])
    if not polygon.is_valid or polygon.area <= 0:
        raise ValueError('Invalid eCFR danger polygon')
    return polygon


def verify(manifest, now=None):
    now = now or datetime.now(timezone.utc)
    polygon = danger_polygon(manifest)
    source = ecfr_section(Client(now=now), {
        'title': 33, 'section': '334.1140',
        'keywords': ['San Miguel Island', 'Point A', 'Point H',
                     'open to fishing', 'anchoring, stopping or loitering']})
    if (source['content_sha256'] != manifest['reviewed_content_sha256']
            or source['normalization'] != manifest['normalization']):
        raise ValueError('San Miguel eCFR source changed; hold research for review')
    return {'schema_version': 1, 'id': manifest['id'],
            'checked_at': now.isoformat(), 'source_url': manifest['source_url'],
            'source_api_url': source['source_url'],
            'source_content_sha256': source['content_sha256'],
            'title_current_through': source['up_to_date_as_of'],
            'title_latest_issue_date': source['title_latest_issue_date'],
            'polygon_bounds_lon_lat': list(polygon.bounds),
            'research_only': True, 'fishing_target': False, 'exportable': False,
            'operational_status_checked': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, default=Path('catalog/san-miguel-naval-danger-zone.json'))
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    receipt = verify(json.loads(args.manifest.read_text()))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(receipt, indent=2) + '\n')
    print(json.dumps(receipt))


if __name__ == '__main__':
    main()
