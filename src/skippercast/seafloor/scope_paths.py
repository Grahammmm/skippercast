"""Resolve isolated seafloor-scope artifacts without changing the central default."""
from dataclasses import dataclass
from pathlib import Path
import re

from skippercast.platform.contracts import read_json


CENTRAL_SCOPE = 'central-coast'
CENTRAL_CONFIG = Path('catalog/seafloor-scope.json')


@dataclass(frozen=True)
class ScopePaths:
    scope_id: str
    config_path: Path
    is_central_default: bool
    reference_dir: Path
    ledger_path: Path
    reaches_path: Path
    cells_path: Path
    build_receipt_path: Path
    screen_dir: Path


def resolve_scope(root, *, scope_config=None, scope_id=None):
    """Load one explicit scope and return its isolated derived-artifact paths.

    The central scope keeps its historic checked-in/cache paths. Every other
    scope requires an explicit config and writes generated artifacts only
    beneath ``var/seafloor/scopes/<id>/`` until downstream contracts are reviewed.
    """
    root = Path(root).resolve()
    if scope_config is None:
        if scope_id not in (None, CENTRAL_SCOPE):
            raise ValueError('A non-central seafloor scope requires an explicit scope config')
        config_path = (root / CENTRAL_CONFIG).resolve()
    else:
        config_path = Path(scope_config)
        if not config_path.is_absolute():
            config_path = root / config_path
        config_path = config_path.resolve()
        if not config_path.is_relative_to(root.resolve()):
            raise ValueError('Scope config must be inside the repository root')
    if not config_path.is_file():
        raise FileNotFoundError(f'Seafloor scope config is missing: {config_path}')
    config = read_json(config_path)
    ident = config.get('id')
    if not isinstance(ident, str) or not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', ident):
        raise ValueError('Scope config needs a stable lowercase ID')
    if scope_id is not None and scope_id != ident:
        raise ValueError('Requested scope ID does not match the selected scope config')
    central_path = (root / CENTRAL_CONFIG).resolve()
    is_central = ident == CENTRAL_SCOPE and config_path == central_path
    if ident == CENTRAL_SCOPE and not is_central:
        raise ValueError('The central scope config cannot be replaced through scoped selection')
    if is_central:
        reference_dir = root / 'var/seafloor/reference'
        ledger_path = root / 'dist/data/seafloor-ledger.json'
        reaches_path = root / 'catalog/reaches.json'
        cells_path = reference_dir / 'cells.json'
        build_receipt_path = reference_dir / 'run.json'
        screen_dir = root / 'var/seafloor/screen'
    else:
        scope_root = root / 'var/seafloor/scopes' / ident
        reference_dir = scope_root / 'reference'
        ledger_path = scope_root / 'seafloor-ledger.json'
        reaches_path = scope_root / 'reaches.json'
        cells_path = reference_dir / 'cells.json'
        build_receipt_path = reference_dir / 'run.json'
        screen_dir = scope_root / 'screen'
    return config, ScopePaths(ident, config_path, is_central, reference_dir,
                              ledger_path, reaches_path, cells_path,
                              build_receipt_path, screen_dir)
