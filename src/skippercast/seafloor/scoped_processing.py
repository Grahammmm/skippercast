"""Verified context for private, physical-only processing of a noncentral scope.

Everything here only checks identity and confines paths. It adds no science and
grants no publication, rights or screen clearance: a valid scope config is not
human review and not G's D2 approval.
"""
from pathlib import Path

from skippercast.platform.contracts import read_json
from .io import sha256
from .scope_paths import resolve_scope

REFERENCE_FILES = ('seafloor-ledger.json', 'reaches.json', 'cells.json')


def _load(path, what):
    try:
        document = read_json(path)
    except FileNotFoundError as exc:
        raise ValueError(f'Scoped reference {what} is missing; build it with reaches --scope-config first') from exc
    except UnicodeDecodeError as exc:
        raise ValueError(f'Scoped reference {what} is not UTF-8 text') from exc
    if not isinstance(document, dict):
        raise ValueError(f'Scoped reference {what} must be a JSON object')
    return document


def _reach_ids(rows, what):
    if not isinstance(rows, list):
        raise ValueError(f'Scoped {what} reaches must be a list')
    ids = []
    for row in rows:
        ident = row.get('id') if isinstance(row, dict) else None
        if not isinstance(ident, str) or not ident:
            raise ValueError(f'Scoped {what} has a reach without a nonempty ID')
        ids.append(ident)
    if len(ids) != len(set(ids)):
        raise ValueError(f'Scoped {what} has duplicate reach IDs')
    return ids


def load_context(root, scope_config, reach_id=None):
    """Verify one noncentral scope's reference artifacts; never fall back to central ones."""
    from .scoped import require_noncentral
    from .scoped_grid import _require_scope_bounds
    root = Path(root).resolve()
    config, paths = require_noncentral(root, scope_config)
    _require_scope_bounds(config.get('bounds'))
    scope_id = config['id']
    ledger = _load(paths.ledger_path, 'ledger')
    catalog = _load(paths.reaches_path, 'reach catalog')
    cells = _load(paths.cells_path, 'cells')
    receipt = _load(paths.build_receipt_path, 'build receipt')
    if ledger.get('scope') != scope_id or catalog.get('scope') != scope_id:
        raise ValueError('Scoped reference belongs to a different scope')
    ledger_ids = _reach_ids(ledger.get('reaches'), 'ledger')
    if set(ledger_ids) != set(_reach_ids(catalog.get('reaches'), 'catalog')):
        raise ValueError('Scoped ledger and reach catalog list different reaches')
    if reach_id is not None and reach_id not in ledger_ids:
        raise ValueError('Unknown reach')
    owned = set(ledger_ids)
    rows = cells.get('cells')
    if not isinstance(rows, list):
        raise ValueError('Scoped reference cells must be a list')
    seen = set()
    for cell in rows:
        if (not isinstance(cell, dict) or not isinstance(cell.get('id'), str) or cell['id'] in seen
                or cell.get('reach') not in owned):
            raise ValueError('Scoped reference has a cell with an invalid or foreign owner')
        seen.add(cell['id'])
    input_hash = receipt.get('input_hash')
    if not isinstance(input_hash, str) or not input_hash or any(
            document.get('input_hash') != input_hash for document in (ledger, catalog, cells)):
        raise ValueError('Scoped reference input hashes do not agree')
    config_sha = sha256(paths.config_path)
    inputs = receipt.get('inputs')
    if not isinstance(inputs, dict) or inputs.get('config_sha256') != config_sha:
        raise ValueError('Scoped reference was built from a different scope config')
    actual = {name: sha256(path) for name, path in zip(
        REFERENCE_FILES, (paths.ledger_path, paths.reaches_path, paths.cells_path))}
    if receipt.get('output_hashes') != actual:
        raise ValueError('Scoped reference outputs do not match their build receipt')
    if ledger.get('reference_cells_sha256', actual['cells.json']) != actual['cells.json']:
        raise ValueError('Scoped ledger reference digest does not match its cells')
    scope_root = (root/'var/seafloor/scopes'/scope_id).resolve()
    identity = {'scope_id': scope_id, 'config_path': paths.config_path.relative_to(root).as_posix(),
                'config_sha256': config_sha, 'reference_input_hash': input_hash,
                'reference_cells_sha256': actual['cells.json'],
                'reference_reaches_sha256': actual['reaches.json'],
                'scoped_processing_sha256': sha256(Path(__file__))}
    return {'identity': identity, 'paths': paths, 'config': config, 'ledger': ledger,
            'catalog': catalog, 'cells': rows, 'reach_ids': ledger_ids,
            'private_dir': scope_root/'private-reaches'}


def reach_folder(context, reach_id):
    """The only place a noncentral reach may write; refuses any symlink or alias escape."""
    folder = context['private_dir']/reach_id
    expected = context['private_dir'].parent/'private-reaches'/reach_id
    if reach_id not in context['reach_ids'] or folder.resolve() != expected:
        raise ValueError('Private reach output path escapes its scope directory')
    return folder


def private_progress(context, manifest):
    """Complete private receipts for exactly this scope, config, reference and current sources."""
    current = {r['id']: r for r in manifest['surveys']}
    result = {}
    for reach_id in context['reach_ids']:
        folder = reach_folder(context, reach_id)
        path = folder/'run.json'
        if not path.is_file():
            continue
        receipt = read_json(path)
        if not isinstance(receipt, dict) or not isinstance(receipt.get('inputs'), dict):
            raise ValueError('Private progress receipt is malformed')
        inputs = receipt['inputs']
        if (receipt.get('publication_prohibited') is not True
                or inputs.get('scope') != context['identity'] or inputs.get('reach_id') != reach_id
                or not inputs.get('sources')
                or any(current.get(r.get('id')) != r for r in inputs['sources'])):
            continue
        outputs = receipt.get('outputs')
        if not isinstance(outputs, dict) or not outputs:
            continue
        for name, expected in outputs.items():
            if Path(name).name != name or not (folder/name).is_file() or sha256(folder/name) != expected:
                raise ValueError('Private progress output checksum mismatch')
        summary = receipt.get('ledger_summary')
        if isinstance(summary, dict) and summary.get('processing_incomplete') is False:
            result[reach_id] = summary
    return result
