"""Approximate offshore-island review envelopes, separate from mainland sectors.

These boxes organize source audits only. They are not island shorelines,
legal boundaries, surveyed footprints, fishing grounds, or navigation areas.
"""
import json
from pathlib import Path


ISLAND_IDS = ('anacapa', 'santa-cruz', 'santa-rosa', 'san-miguel',
              'santa-barbara-island', 'catalina', 'san-clemente', 'san-nicolas')
PADDING_DEGREES = 0.02


def load_island_review_areas(path=Path('regions/southern-california/region.json')):
    region = json.loads(Path(path).read_text())
    areas = {row['id']: row for row in region['map']['local_areas']}
    if any(ident not in areas for ident in ISLAND_IDS):
        raise ValueError('Southern California island review envelopes are incomplete')
    result = []
    for ident in ISLAND_IDS:
        west, south, east, north = areas[ident]['bounds']
        if not (-125 < west < east < -115 and 30 < south < north < 36):
            raise ValueError('Invalid island review envelope: ' + ident)
        p = PADDING_DEGREES
        result.append({'id': ident, 'name': areas[ident]['name'],
                       'bounds': [west-p, south-p, east+p, north+p]})
    return result


def containing_island(lon, lat, islands):
    for row in islands:
        west, south, east, north = row['bounds']
        if west <= lon < east and south <= lat < north:
            return row['id']
    return None
