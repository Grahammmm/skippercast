"""Where research receipts live, and how to resolve their historical paths.

Audit receipts used to be committed under ``dist/data/`` and shipped with the
web app. They now live in ``research/receipts/`` (engineering audit P1-02b).
Receipts, catalog bindings and ledgers written before the move still name each
other as ``dist/data/<name>``; those strings are hashed evidence and are kept
byte-for-byte, so resolve them with :func:`locate` instead of rewriting them.
"""
import hashlib
import json
from pathlib import Path

from research.lib.paths import ROOT

RECEIPTS = ROOT / 'research' / 'receipts'
MANIFEST = RECEIPTS / 'manifest.json'
LEGACY_PREFIX = 'dist/data/'


def locate(reference, root=ROOT):
    """Path of a repository-relative reference, following receipts moved out of dist/data/.

    ``root`` defaults to the repository; tests pass a temporary tree laid out the same way.
    """
    root = Path(root)
    path = root / reference
    text = Path(reference).as_posix()
    if not path.exists() and text.startswith(LEGACY_PREFIX):
        moved = root / 'research' / 'receipts' / text[len(LEGACY_PREFIX):]
        if moved.exists():
            return moved
    return path


def manifest_entries(directory=RECEIPTS):
    """{relative path: sha256} for every receipt file (the manifest itself excluded)."""
    return {path.relative_to(directory).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(directory.rglob('*'))
            if path.is_file() and path != directory / 'manifest.json' and '__pycache__' not in path.parts}


def write_manifest(directory=RECEIPTS):
    (directory / 'manifest.json').write_text(json.dumps(
        {'schema_version': 1,
         'note': 'sha256 of every research receipt; tests/test_receipt_manifest.py fails on drift. '
                 'Regenerate with: python -m research.lib.receipts',
         'files': manifest_entries(directory)}, indent=1, sort_keys=False) + '\n')


if __name__ == '__main__':
    write_manifest()
    print(f'Wrote {MANIFEST.relative_to(ROOT)} ({len(manifest_entries())} receipts)')
