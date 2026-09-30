"""Transfer checked private physics after rights-only source promotion.

No numerical implementation is exempted from cache identity. This operation
keeps the destination held until the ordinary runner applies a fresh screen.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import shutil
import tempfile

from pyproj import Transformer
from shapely.geometry import box
from shapely.ops import transform, unary_union

from skippercast.platform.contracts import REPO, atomic_json, read_json
from .coverage import cell_geometry
from .ingest import ingest
from .io import sha256
from .manifest import load_manifest, physical_source
from .substrate import resolve_bindings, verify_sources

PHYSICAL = ('cells.json', 'terrain.json', 'candidates.geojson', 'atlas-comparison.json')
OUTPUTS = (*PHYSICAL, 'physical.json', 'habitat.geojson', 'held.geojson')
RELEASE_FIELDS = {'status', 'license', 'rights_review', 'hold_reason', 'notes'}
IMPLEMENTATION = ('coverage.py', 'terrain.py', 'run.py', 'habitat.py',
                  'habitat_tiles.py', 'substrate.py', 'resolution_profile.py', 'normalized.py')


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def scientific_row(row):
    return {k: v for k, v in row.items() if k not in RELEASE_FIELDS}


def adopt_private(reach_id, *, root=REPO):
    """Adopt into a new public cache; never overwrite an existing reach."""
    from .run import VERSION
    root = Path(root)
    reaches = read_json(root/'catalog/reaches.json')
    if not any(r['id'] == reach_id for r in reaches['reaches']):
        raise ValueError('Unknown reach')
    private = root/'var/seafloor/private-reaches'/reach_id
    receipt = read_json(private/'run.json')
    old = deepcopy(receipt['inputs'])
    old.pop('screen', None)
    old.pop('screen_implementation_sha256', None)
    physical = read_json(private/'physical.json')
    if (old.get('reach_id') != reach_id or not receipt.get('publication_prohibited')
            or receipt['ledger_summary'].get('processing_incomplete')
            or physical['input_hash'] != digest(old)
            or receipt['physical_input_hash'] != digest(old)):
        raise ValueError('Private physics receipt is incomplete or inconsistent')
    if set(receipt['outputs']) != set(OUTPUTS) or set(physical['outputs']) != set(PHYSICAL):
        raise ValueError('Private output inventory is incomplete')
    for name in OUTPUTS:
        if sha256(private/name) != receipt['outputs'][name]:
            raise ValueError('Private output checksum mismatch')
    if physical['outputs'] != {name: sha256(private/name) for name in PHYSICAL}:
        raise ValueError('Private physical output checksum mismatch')
    module = Path(__file__).parent
    checks = {'rule_version': VERSION,
              'reference_cells_sha256': sha256(root/'var/seafloor/reference/cells.json'),
              'reaches_sha256': sha256(root/'catalog/reaches.json'),
              'atlas_sha256': sha256(root/'dist/data/atlas.json'),
              'scoring_sha256': sha256(module.parent/'atlas/scoring.py'),
              'requirements_sha256': sha256(root/'requirements-survey.txt'),
              'implementation': {name: sha256(module/name) for name in IMPLEMENTATION},
              'habitat_rules': read_json(root/'catalog/habitat-rules.json')}
    if any(old.get(key) != value for key, value in checks.items()):
        raise ValueError('Scientific inputs or implementation changed; recompute physics')
    baseline = read_json(root/'var/seafloor/reference/cells.json')
    reference = read_json(root/'var/seafloor/reference/run.json')
    if (baseline['input_hash'] != reaches['input_hash']
            or reference['input_hash'] != reaches['input_hash']
            or reference['output_hashes']['cells.json'] != checks['reference_cells_sha256']):
        raise ValueError('Reference identity changed')
    scope = unary_union([cell_geometry(c) for c in baseline['cells'] if c['reach'] == reach_id])
    project = Transformer.from_crs(4326, 3310, always_xy=True).transform
    manifest = load_manifest(root)
    selected = [r for r in manifest['surveys'] if physical_source(r)
                and transform(project, box(*r['adapter_review']['requested_bounds_wgs84'])).intersects(scope)]
    if [r['id'] for r in selected] != [r['id'] for r in old['sources']]:
        raise ValueError('Selected source set or ordering changed; recompute physics')
    for before, after in zip(old['sources'], selected):
        if scientific_row(before) != scientific_row(after):
            raise ValueError('Scientific source metadata changed; recompute physics')
        if before['status'] not in {'usable', 'physical-only'} or after['status'] != 'usable':
            raise ValueError('Source publication rights remain unqualified')
        # Ingestion still validates original and normalized bytes; no fetch or
        # terrain extraction is permitted during this cache migration.
        current, _, _ = ingest(after, after['adapter_review']['requested_bounds_wgs84'], root=root)
        if current['cog_sha256'] != before['adapter_review']['cog_sha256']:
            raise ValueError('Normalized scientific raster changed')
    bindings = resolve_bindings(checks['habitat_rules'], manifest)
    ids = {r['id'] for r in selected}
    bindings = {key: value for key, value in bindings.items() if key in ids}
    if bindings != old['substrate_bindings']:
        raise ValueError('Substrate inputs changed; recompute physics')
    verify_sources(bindings, root=root)
    current_inputs = dict(old, sources=selected)
    new_hash = digest(current_inputs)
    destination = root/'var/seafloor/reaches'/reach_id
    if destination.exists():
        raise ValueError('Destination reach already exists; preserve it and review separately')
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix='.adopt-', dir=destination.parent))
    try:
        for name in OUTPUTS:
            shutil.copyfile(private/name, staging/name)
        for name in ('cells.json', 'terrain.json'):
            data = read_json(staging/name)
            data['input_hash'] = new_hash
            atomic_json(staging/name, data)
        evidence = {'version': 'rights-only-physics-adoption-v1',
                    'private_run_sha256': sha256(private/'run.json'),
                    'previous_physical_hash': physical['input_hash'], 'physical_input_hash': new_hash,
                    'scientific_inputs_unchanged': True, 'requires_current_screen': True}
        atomic_json(staging/'physical.json', {'input_hash': new_hash,
                    'outputs': {name: sha256(staging/name) for name in PHYSICAL}}, indent=2)
        # Keep private sources and deferred screen in this transitional run
        # receipt so publication explicitly refuses it until run() rescreens.
        receipt['outputs'] = {name: sha256(staging/name) for name in OUTPUTS}
        receipt['adoption'] = evidence
        atomic_json(staging/'run.json', receipt, indent=2)
        staging.rename(destination)
        return evidence
    finally:
        if staging.exists():
            shutil.rmtree(staging)
