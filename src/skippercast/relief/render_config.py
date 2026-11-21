"""Resolve a region's render recipe without making it a stage input."""
from pathlib import Path
import re

from skippercast import style
from skippercast.paths import repo_root
from skippercast.relief.package import decode_document, validate_schema

LEGACY = 'deep-fixed-v1'


def _read(path):
    return decode_document(path.read_bytes())


def _config(region_id):
    if not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,63}', region_id):
        raise ValueError('invalid render region id')
    repo = repo_root()
    path = repo / 'regions' / region_id / 'render.json'
    try:
        value = _read(path)
    except FileNotFoundError:
        return None
    validate_schema(value, _read(repo / 'schemas/sc-render-v1.schema.json'))
    if value['region'] != region_id:
        raise ValueError('render config belongs to another region')
    for group in ('previews', 'piers'):
        ids = [row['id'] for row in value[group]]
        if len(set(ids)) != len(ids):
            raise ValueError(f'duplicate render config {group} id')
    return value


def _select(config, directory):
    index = _read(directory / 'index.json')
    version = (config or {}).get('style', index['default'])
    entry = index['versions'].get(version)
    if entry is None or entry.get('status') == 'retired':
        raise ValueError(f'unavailable render style: {version}')
    return version, entry


def resolve_style(region_id, root=None):
    """Return (version, verified Style); the legacy builder has no Style.

    As in style.load, root overrides the style directory, not the region tree.
    """
    directory = repo_root() / 'style' if root is None else Path(root)
    version, _ = _select(_config(region_id), directory)
    return version, None if version == LEGACY else style.load(version, root=directory)


def previews(region_id, *, native_footprints=()):
    """Return configured windows or deterministic defaults.

    An evidence producer may supply footprints as (source id, cell metres,
    area m², [lon, lat] centroid) rows. No native windows are invented when
    evidence is absent. First select the finest tier, then its largest footprint.
    """
    config = _config(region_id)
    if config is not None:
        _select(config, repo_root() / 'style')
        return config['previews']
    w, s, e, n = _read(repo_root() / 'regions' / region_id / 'region.json')['fishing_bounds']
    windows = [dict(id='fishing-z11', center=[(w + e) / 2, (s + n) / 2], size_m=8000, zoom=11)]
    if native_footprints:
        _, cell_m, _, center = min(native_footprints, key=lambda row: (row[1], -row[2], row[0]))
        windows.append(dict(id='native-z13', center=list(center), size_m=4000, zoom=13))
        if cell_m <= 2:
            windows.append(dict(id='native-z15', center=list(center), size_m=1200, zoom=15))
    return windows


def piers(region_id):
    config = _config(region_id)
    if config is None:
        return []
    _select(config, repo_root() / 'style')
    return config['piers']
