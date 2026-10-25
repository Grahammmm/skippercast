"""Fail-closed entry points for explicitly selected noncentral scopes."""
import hashlib
import os
import stat

from .scope_paths import resolve_scope

_SNAPSHOT_CHUNK = 1024 * 1024
_UNSAFE_SNAPSHOT = 'unsafe scope snapshot diagnostic'


def _snapshot_identity(info):
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns


def _snapshot_sha256(snapshot):
    """Hash a held-diagnostic snapshot through one no-follow regular-file descriptor.

    Returns None when the snapshot is absent. A leaf symlink, a nonregular leaf,
    or a leaf replaced or changed while it is opened and read raises ValueError.
    Only the leaf is protected: in-root directory aliases that scope_paths
    resolves upstream keep their meaning. This is not a race-free sandbox.
    """
    try:
        before = os.lstat(snapshot)
    except (FileNotFoundError, NotADirectoryError):
        return None
    if not stat.S_ISREG(before.st_mode):
        raise ValueError(f'{_UNSAFE_SNAPSHOT}: snapshot leaf is not a regular file')
    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | getattr(os, 'O_CLOEXEC', 0)
    try:
        descriptor = os.open(snapshot, flags)
    except OSError as error:
        raise ValueError(f'{_UNSAFE_SNAPSHOT}: snapshot leaf changed before it was opened') from error
    try:
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode) or _snapshot_identity(opened) != _snapshot_identity(before):
            raise ValueError(f'{_UNSAFE_SNAPSHOT}: snapshot leaf was replaced or changed before it was read')
        digest, total = hashlib.sha256(), 0
        while chunk := os.read(descriptor, _SNAPSHOT_CHUNK):
            total += len(chunk)
            if total > opened.st_size:
                raise ValueError(f'{_UNSAFE_SNAPSHOT}: snapshot leaf grew while it was read')
            digest.update(chunk)
        if total != opened.st_size or _snapshot_identity(os.fstat(descriptor)) != _snapshot_identity(opened):
            raise ValueError(f'{_UNSAFE_SNAPSHOT}: snapshot leaf changed while it was read')
        try:
            current = os.lstat(snapshot)
        except OSError as error:
            raise ValueError(f'{_UNSAFE_SNAPSHOT}: snapshot leaf name changed while it was read') from error
        if (current.st_dev, current.st_ino) != (opened.st_dev, opened.st_ino):
            raise ValueError(f'{_UNSAFE_SNAPSHOT}: snapshot leaf name was replaced while it was read')
    finally:
        os.close(descriptor)
    return digest.hexdigest()


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
    digest = _snapshot_sha256(snapshot)
    if digest is not None:
        state['snapshot_sha256'] = digest
    return state


def build_reference(root, *, fetch=False, region=None, scope_config=None, scope_id=None):
    from . import scoped_grid
    return scoped_grid.build(root, fetch=fetch, region=region,
                             scope_config=scope_config, scope_id=scope_id)
