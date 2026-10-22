"""Read-only reconstruction of the maintained runner's physical cache identity.

Keep run.py byte-identical: retained physics receipts pin its implementation hash.
The integrated runner regression checks this reconstruction against actual output.
"""
import hashlib
import json
from pathlib import Path

from pyproj import Transformer
from shapely.geometry import box
from shapely.ops import transform, unary_union

from skippercast.platform.contracts import read_json
from .coverage import cell_geometry
from .habitat import validate_rules
from .io import sha256
from .manifest import load_manifest, physical_source
from .run import VERSION
from .source_scope import scoped_manifest
from .substrate import resolve_bindings


def current_physical_input_hash(root, reach_id):
    """Match run(..., physical_only=False) without ingestion, terrain or writes."""
    root = Path(root)
    if not any(r['id'] == reach_id for r in read_json(root/'catalog/reaches.json')['reaches']):
        raise ValueError('Unknown reach')
    cells = read_json(root/'var/seafloor/reference/cells.json')['cells']
    scope = unary_union([cell_geometry(c) for c in cells if c['reach'] == reach_id])
    manifest, source_scope = scoped_manifest(root, load_manifest(root))
    project = Transformer.from_crs(4326, 3310, always_xy=True).transform
    rows = [row for row in manifest['surveys'] if physical_source(row)
            and transform(project, box(*row['adapter_review']['requested_bounds_wgs84'])).intersects(scope)]
    rules = validate_rules(read_json(root/'catalog/habitat-rules.json'))
    ids = {row['id'] for row in rows}
    bindings = {k: v for k, v in resolve_bindings(rules, manifest, scoped=source_scope is not None).items()
                if k in ids}
    inputs = {'rule_version': VERSION, 'reach_id': reach_id,
              'reference_cells_sha256': sha256(root/'var/seafloor/reference/cells.json'),
              'reaches_sha256': sha256(root/'catalog/reaches.json'),
              'sources': rows, 'habitat_rules': rules, 'substrate_bindings': bindings,
              'atlas_sha256': sha256(root/'dist/data/atlas.json'),
              'scoring_sha256': sha256(Path(__file__).parents[1]/'atlas/scoring.py'),
              'requirements_sha256': sha256(root/'requirements-survey.txt'),
              'implementation': {n: sha256(Path(__file__).parent/n)
                                 for n in ('coverage.py', 'terrain.py', 'run.py', 'habitat.py', 'habitat_tiles.py', 'substrate.py', 'terrain_support.py', 'resolution_profile.py', 'normalized.py', 'source_scope.py')}}
    if source_scope is not None:
        inputs['source_scope'] = source_scope
    return hashlib.sha256(json.dumps(inputs, sort_keys=True).encode()).hexdigest()
