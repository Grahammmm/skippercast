"""Fail-closed entry points for explicitly selected noncentral scopes."""
from .scope_paths import resolve_scope


def require_noncentral(root, scope_config):
    if scope_config is None:
        raise ValueError('A noncentral scope must be selected explicitly')
    config, paths = resolve_scope(root, scope_config=scope_config)
    if paths.is_central_default:
        raise ValueError('Central scope must use its retained default pipeline')
    return config, paths


def load_snapshot(root, reach_id, now=None, *, scope_config=None):
    """Central delegates unchanged; noncentral scope stays held pending full policy contract."""
    from . import screen
    if scope_config is None:
        return screen.load_snapshot(root, reach_id, now)
    config, paths = resolve_scope(root, scope_config=scope_config)
    if paths.is_central_default:
        return screen.load_snapshot(root, reach_id, now)
    state = {'version': screen.VERSION, 'status': 'held',
             'reasons': ['scope-screen-contract-unavailable'], 'layers': [],
             'scope_id': config['id']}
    snapshot = paths.screen_dir/'snapshot.json'
    if snapshot.is_file():
        from .io import sha256
        state['snapshot_sha256'] = sha256(snapshot)
    return state


def build_reference(root, *, fetch=False, region=None, scope_config=None, scope_id=None):
    from . import scoped_grid
    return scoped_grid.build(root, fetch=fetch, region=region,
                             scope_config=scope_config, scope_id=scope_id)
