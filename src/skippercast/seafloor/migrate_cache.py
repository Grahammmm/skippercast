"""Explicit numeric-only cache migration; never grants publication rights."""
from copy import deepcopy
import json
from pathlib import Path
import shutil
import tempfile

from pyproj import Transformer
from shapely.geometry import box
from shapely.ops import transform, unary_union

from skippercast.platform.contracts import REPO, read_json, atomic_json
from .adopt import IMPLEMENTATION, OUTPUTS, PHYSICAL, digest
from .coverage import cell_geometry
from .ingest import ingest
from .io import sha256
from .manifest import load_manifest, normalize_measurement_row, physical_source
from .state_cache import scope_name
from .substrate import resolve_bindings, verify_sources


def migrate_numeric_cache(reach_id, *, root=REPO, private=False, apply=False):
    """Verify all science/bytes, then stage a held replacement with full recovery."""
    from .run import VERSION
    scope_name(reach_id)
    root = Path(root)
    folder = root/'var/seafloor'/('private-reaches' if private else 'reaches')/reach_id
    receipt = read_json(folder/'run.json')
    physical = read_json(folder/'physical.json')
    old = deepcopy(receipt['inputs'])
    old.pop('screen', None)
    old.pop('screen_implementation_sha256', None)
    if (old.get('reach_id') != reach_id or receipt['ledger_summary'].get('processing_incomplete')
            or physical['input_hash'] != digest(old)
            or receipt['physical_input_hash'] != digest(old)
            or receipt['input_hash'] != digest(receipt['inputs'])):
        raise ValueError('Incomplete or inconsistent original cache identity')
    if set(receipt['outputs']) != set(OUTPUTS) or set(physical['outputs']) != set(PHYSICAL):
        raise ValueError('Incomplete output inventory')
    for name in OUTPUTS:
        if sha256(folder/name) != receipt['outputs'][name]:
            raise ValueError('Original output checksum mismatch')
    if physical['outputs'] != {name: sha256(folder/name) for name in PHYSICAL}:
        raise ValueError('Original physical output checksum mismatch')
    reaches = read_json(root/'catalog/reaches.json')
    if not any(r['id'] == reach_id for r in reaches['reaches']):
        raise ValueError('Unknown reach')
    module = Path(__file__).parent
    checks = {'rule_version': VERSION,
              'reference_cells_sha256': sha256(root/'var/seafloor/reference/cells.json'),
              'reaches_sha256': sha256(root/'catalog/reaches.json'),
              'atlas_sha256': sha256(root/'dist/data/atlas.json'),
              'scoring_sha256': sha256(module.parent/'atlas/scoring.py'),
              'requirements_sha256': sha256(root/'requirements-survey.txt'),
              'implementation': {name: sha256(module/name) for name in IMPLEMENTATION},
              'habitat_rules': read_json(root/'catalog/habitat-rules.json')}
    if any(json.dumps(old.get(k), sort_keys=True) != json.dumps(v, sort_keys=True) for k, v in checks.items()):
        raise ValueError('Scientific inputs or implementation changed; recompute physics')
    baseline = read_json(root/'var/seafloor/reference/cells.json')
    reference = read_json(root/'var/seafloor/reference/run.json')
    if (baseline['input_hash'] != reaches['input_hash'] or reference['input_hash'] != reaches['input_hash']
            or reference['output_hashes']['cells.json'] != checks['reference_cells_sha256']):
        raise ValueError('Reference identity changed')
    scope = unary_union([cell_geometry(c) for c in baseline['cells'] if c['reach'] == reach_id])
    project = Transformer.from_crs(4326, 3310, always_xy=True).transform
    manifest = load_manifest(root)
    selected = [row for row in manifest['surveys'] if physical_source(row, physical_only=private)
                and transform(project, box(*row['adapter_review']['requested_bounds_wgs84'])).intersects(scope)]
    normalized = [normalize_measurement_row(row) for row in old['sources']]
    if json.dumps(normalized, sort_keys=True) != json.dumps(selected, sort_keys=True):
        raise ValueError('Scientific sources, ordering or rights changed; not numeric-only')
    for row in selected:
        native, _, _ = ingest(row, row['adapter_review']['requested_bounds_wgs84'], root=root)
        if native['cog_sha256'] != row['adapter_review']['cog_sha256']:
            raise ValueError('Normalized source bytes changed')
    bindings = resolve_bindings(checks['habitat_rules'], manifest)
    ids = {r['id'] for r in selected}
    bindings = {k: v for k, v in bindings.items() if k in ids}
    if json.dumps(bindings, sort_keys=True) != json.dumps(old['substrate_bindings'], sort_keys=True):
        raise ValueError('Substrate inputs changed')
    verify_sources(bindings, root=root)
    current = dict(old, sources=normalized)
    new_hash = digest(current)
    evidence = {'version': 'numeric-only-cache-migration-v1', 'reach': reach_id,
                'previous_physical_hash': physical['input_hash'], 'physical_input_hash': new_hash,
                'original_run_sha256': sha256(folder/'run.json'), 'scientific_inputs_unchanged': True,
                'requires_current_screen': True, 'changed': new_hash != physical['input_hash'], 'applied': False}
    if not evidence['changed'] or not apply:
        return evidence
    backup = root/'var/seafloor/numeric-migrations'/reach_id/receipt['input_hash']
    if backup.exists():
        raise ValueError('Recovery already exists; reconcile interrupted migration before retrying')
    staging = Path(tempfile.mkdtemp(prefix='.numeric-', dir=folder.parent))
    try:
        for name in OUTPUTS:
            shutil.copyfile(folder/name, staging/name)
        for name in ('cells.json', 'terrain.json'):
            data = read_json(staging/name)
            if data['input_hash'] != physical['input_hash']:
                raise ValueError('Physical metadata identity mismatch')
            data['input_hash'] = new_hash
            atomic_json(staging/name, data)
        atomic_json(staging/'physical.json', {'input_hash': new_hash,
                    'outputs': {name: sha256(staging/name) for name in PHYSICAL}}, indent=2)
        revised = deepcopy(receipt)
        revised['inputs']['sources'] = normalized
        revised['inputs']['screen'] = {'status': 'deferred',
                    'reasons': ['numeric-migration-requires-current-screen'], 'layers': []}
        revised['input_hash'] = digest(revised['inputs'])
        revised['physical_input_hash'] = new_hash
        revised['publication_prohibited'] = True
        revised['ledger_summary']['physical_input_hash'] = new_hash
        revised['ledger_summary']['survey_run_hash'] = revised['input_hash']
        revised['outputs'] = {name: sha256(staging/name) for name in OUTPUTS}
        evidence['applied'] = True
        revised['numeric_migration'] = evidence
        atomic_json(staging/'run.json', revised, indent=2)
        atomic_json(staging/'numeric-migration.json', evidence, indent=2)
        backup.parent.mkdir(parents=True, exist_ok=True)
        folder.rename(backup)
        try:
            staging.rename(folder)
        except BaseException:
            backup.rename(folder)
            raise
        return evidence
    finally:
        if staging.exists():
            shutil.rmtree(staging)
