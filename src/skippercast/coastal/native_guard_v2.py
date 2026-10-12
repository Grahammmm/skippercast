"""Authenticate local native containers before any scientific reader opens them."""
from pathlib import Path


def check(path):
    from .handoff.common import ref, validate_native_source
    path = Path(path).absolute()
    root = path.parent
    return validate_native_source(root, ref(root, path, 'native-source-v2'))
