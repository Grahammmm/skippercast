"""Portable SC178 constructors: synthetic screen inputs only, never operational data.

Shapes follow tests/gis/test_seafloor_screen.py (polygon, state, terrain and
fit) and tests/gis/test_classified_habitat.py (classified producer inputs).
Nothing here imports product code or writes files.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

from pyproj import Transformer
from shapely.geometry import box, mapping
from shapely.ops import transform

NOW = '2026-09-28T00:00:00+00:00'
TO_GEO = Transformer.from_crs(3310, 4326, always_xy=True).transform
LAYERS = ('cdfw-mpa', 'noaa-federal', 'security')
EXPECTED_HABITAT_LABEL = 'Habitat candidate, unverified. Nominal depth (unknown); verify on your sounder.'

# Malformed ordinary fit values: label -> (properties update, extra expected reasons).
# A MISSING sentinel removes the fit key entirely.
MISSING = object()
MALFORMED = {
    'bool-true-rank': {'lingcod': True},
    'bool-false-rank': {'lingcod': False},
    'bool-true-mixed-with-int': {'lingcod': 3, 'rockfish-reef': True},
    'float-three-rank': {'lingcod': 3.0},
    'float-one-rank': {'lingcod': 1.0},
    'float-fraction-rank': {'lingcod': 2.5},
    'zero-rank': {'lingcod': 0},
    'four-rank': {'lingcod': 4},
    'negative-rank': {'lingcod': -1},
    'null-rank': {'lingcod': None},
    'text-rank': {'lingcod': '3'},
    'list-rank': {'lingcod': [3]},
    'mapping-rank': {'lingcod': {'rank': 3}},
    'null-fit': None,
    'missing-fit': MISSING,
    'empty-mapping-fit': {},
    'list-fit': [3],
    'empty-list-fit': [],
    'text-fit': '3',
    'empty-text-fit': '',
    'scalar-int-fit': 3,
    'scalar-float-fit': 3.0,
    'scalar-true-fit': True,
    'tuple-fit': (3,),
}


def geo(x, y, size=50):
    return mapping(transform(TO_GEO, box(x, y, x + size, y + size)))


def candidate(ident, x=0, y=0, fit=None, grade='B'):
    """Otherwise-valid ordinary polygon feature (all non-fit gates pass)."""
    feature = {'type': 'Feature', 'geometry': geo(x, y), 'properties': {
        'id': ident, 'tier': 1, 'hold_reasons': ['legal-screen-pending'],
        'terrain': {'grade': grade}, 'fit': {'lingcod': 3} if fit is None else deepcopy(fit),
        'resolution_m': 2, 'depth_min_ft': 90, 'depth_max_ft': 110, 'vertical_datum': 'unknown'}}
    return feature


def malformed(label, x=0, y=0):
    feature = candidate('bad-' + label, x, y)
    value = MALFORMED[label]
    if value is MISSING:
        del feature['properties']['fit']
    else:
        feature['properties']['fit'] = deepcopy(value)
    return feature


def state(exclusion=None):
    return json.loads(json.dumps({
        'version': 'whole-polygon-screen-v1', 'status': 'ready', 'reasons': [], 'snapshot': NOW,
        'snapshot_sha256': 'a' * 64, 'scope': geo(-1000, -1000, 3000),
        'layers': [{'id': name, 'features': [{'geometry': exclusion or geo(1500, 1500)}]}
                   for name in LAYERS]}))


def search_patch(ident, rule_version, x=0, y=0):
    feature = candidate(ident, x, y)
    feature['properties'].update(terrain='unknown', fit={'lingcod': 'unknown', 'rockfish-reef': 'unknown'},
                                 source_ids=['native'], rule_version=rule_version, metric_support_fraction=.65,
                                 hold_reasons=['legal-screen-pending', 'metric-support-incomplete'])
    return feature


def classified_inputs():
    """Producer inputs for classified_habitat.features_for (synthetic, reviewed shape)."""
    policy = {'id': 'fixture-rugose-v1', 'reviewed_on': '2026-09-01',
              'depth_source_id': 'native', 'depth_source_sha256': 'a' * 64,
              'classification_source_id': 'classes', 'classification_source_sha256': 'b' * 64,
              'metadata_url': 'https://example.test/original-metadata', 'metadata_sha256': 'c' * 64,
              'rugose_raw_codes': [3, 13], 'credit': 'Original publisher and mapping lab',
              'release_license': 'public-domain-us-gov', 'notice': 'Not for navigation.',
              'review_basis': 'Synthetic explicitly reviewed class3; mixed excluded.'}
    row = {'id': 'native', 'sha256': 'a' * 64, 'status': 'usable', 'kind': 'bathymetry',
           'resolution_m': 2., 'vertical_datum': 'unknown', 'license': 'public-domain-us-gov',
           'url': 'https://example.test/original-depth', 'publisher': 'Original publisher',
           'adapter_review': {'requested_bounds_wgs84': [-122, 35, -121, 36]}}
    binding = {'row': {'id': 'classes', 'sha256': 'b' * 64, 'status': 'candidate', 'kind': 'substrate',
                       'format': 'usgs-geotiff', 'license': 'public-domain-us-gov',
                       'url': 'https://example.test/original-class', 'publisher': 'Original publisher'},
               'binding': {'source_id': 'classes', 'source_sha256': 'b' * 64, 'depth_source_ids': ['native'],
                           'review_status': 'reviewed', 'metadata_url': policy['metadata_url'],
                           'metadata_sha256': 'c' * 64, 'same_survey_as_depth': True,
                           'classes': {'1': {'normalized_code': 1}, '2': {'normalized_code': 2},
                                       '3': {'normalized_code': 3}, '13': {'normalized_code': 3}}}}
    return policy, row, binding


def native_box(x=0, y=0, size=50):
    return box(x, y, x + size, y + size)


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def snapshot(root):
    root = Path(root)
    return {str(p.relative_to(root)): digest(p) if p.is_file() else 'dir'
            for p in sorted(root.rglob('*'))}
