"""Select original government inputs before any scientific source precedence.

This is an input scope, never a filter over mixed-source habitat results. The
complete pinned catalog remains unchanged. Scoped processing requires an owned,
root-bound marker so it cannot overwrite the default ledger and reach outputs.
"""
import os
from pathlib import Path

from skippercast.platform.contracts import read_json
from .io import sha256

VERSION = 'government-input-scope-v1'
GOVERNMENT = 'government-only'
LICENSE = 'public-domain-us-gov'


def processing_scope(root):
    root = Path(root)
    path = root/'deployments/production.json'
    configured = read_json(path).get('source_scope', 'all') if path.exists() else 'all'
    scope = os.environ.get('SKIPPERCAST_SOURCE_SCOPE', configured)
    if configured not in {'all', GOVERNMENT} or scope not in {'all', GOVERNMENT}:
        raise ValueError('Unknown seafloor input source scope')
    if configured == GOVERNMENT and scope != GOVERNMENT:
        raise ValueError('Environment cannot weaken configured government input scope')
    marker_path = root/'var/seafloor/input-scope.json'
    marker = read_json(marker_path) if marker_path.exists() else None
    if scope == GOVERNMENT:
        from .rights import deployment_use
        if deployment_use(root) != 'for-profit':
            raise ValueError('Government input scope requires explicit for-profit source use')
        if marker != {'version': 1, 'scope': GOVERNMENT, 'isolated_root': str(root.resolve())}:
            raise ValueError('Government input scope requires a matching isolated-root marker')
    elif marker is not None:
        raise ValueError('Default processing cannot use a scoped isolated root')
    return scope


def government_row(row, rows, visited=()):
    """Lineage cannot launder an excluded original into a government label."""
    ident = row.get('id')
    if row.get('license') != LICENSE or ident in visited:
        return False
    return all(parent in rows and government_row(rows[parent], rows, (*visited, ident))
               for parent in row.get('derived_from', []))


def scoped_manifest(root, manifest):
    scope = processing_scope(root)
    if scope == 'all':
        return manifest, None
    rows = {row['id']: row for row in manifest['surveys']}
    admitted = [row for row in manifest['surveys'] if government_row(row, rows)]
    admitted_ids = {row['id'] for row in admitted}
    audit = {'version': VERSION, 'scope': GOVERNMENT, 'source_use': 'for-profit',
             'catalog_sha256': sha256(Path(root)/'catalog/surveys.json'),
             'admitted_source_ids': sorted(admitted_ids),
             'excluded_source_ids': sorted(set(rows)-admitted_ids)}
    return dict(manifest, surveys=admitted), audit


def validate_dependencies(ids, rows, audit, *, label):
    if (not isinstance(ids, list) or any(not isinstance(ident, str) for ident in ids)
            or len(ids) != len(set(ids))):
        raise ValueError(f'Invalid government {label} dependency inventory')
    admitted = set(audit['admitted_source_ids'])
    for ident in ids:
        if ident not in admitted or ident not in rows or not government_row(rows[ident], rows):
            raise ValueError(f'Restricted or unknown government {label} dependency: {ident}')
        from .rights import source_rights
        source_rights(rows[ident], use='for-profit')


def validate_receipt(inputs, candidates, manifest, audit):
    """Check indirect calibration and substrate, even without own polygons."""
    if inputs.get('source_scope') != audit:
        raise ValueError('Government source scope receipt changed; rerun required')
    rows = {row['id']: row for row in manifest['surveys']}
    sources = inputs.get('sources')
    if not isinstance(sources, list):
        raise ValueError('Missing government physical source inventory')
    ids = [row.get('id') for row in sources if isinstance(row, dict)]
    if len(ids) != len(sources):
        raise ValueError('Invalid government physical source inventory')
    validate_dependencies(ids, rows, audit, label='physical')
    if any(row != rows[row['id']] for row in sources):
        raise ValueError('Government physical source metadata changed; rerun required')
    calibration = candidates.get('calibration_source_ids')
    validate_dependencies(calibration, rows, audit, label='calibration')
    if not set(calibration).issubset(ids):
        raise ValueError('Government calibration is outside verified physical inputs')
    bindings = inputs.get('substrate_bindings')
    if not isinstance(bindings, dict):
        raise ValueError('Missing government substrate dependency inventory')
    for depth_id, entry in bindings.items():
        if depth_id not in ids or not isinstance(entry, dict) or not isinstance(entry.get('row'), dict):
            raise ValueError('Invalid government substrate dependency inventory')
        row = entry['row']
        validate_dependencies([row.get('id')], rows, audit, label='substrate')
        if row != rows[row['id']]:
            raise ValueError('Government substrate metadata changed; rerun required')
    return calibration
