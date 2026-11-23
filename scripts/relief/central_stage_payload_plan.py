#!/usr/bin/env python3
"""List a Central STAGE pickup checklist from local scratch candidates only."""
import argparse
from io import BytesIO
from pathlib import Path
import sys
from types import SimpleNamespace

from skippercast.relief import envelope, package, stage_transport as stage


def _candidate(root, path):
    # Use canonical, non-symlink paths inside the caller's disposable workspace.
    return package.artifact_path(root, path.absolute().relative_to(root).as_posix())


def _pickup(scratch, envelope_path, pointer_path):
    scratch = scratch.resolve(strict=True)
    try:
        pointer = package.decode_document(_candidate(scratch, pointer_path).read_bytes())
        package.validate_schema(pointer, package.pointer_schema())
    except (OSError, ValueError, RecursionError):
        raise stage.StageError('unusable pointer candidate in scratch') from None
    try:
        review = _candidate(scratch, envelope_path)
        verified = envelope.verify_artifacts(review)
    except (OSError, ValueError, RecursionError):
        raise stage.StageError('unusable envelope or changed envelope artifacts in scratch') from None

    release = verified.release
    layers = {row['path']: row for row in verified.layers}
    archive_row = layers[package.ARCHIVE]
    # As in build_pointer, rollback lineage is not part of the current envelope.
    expected = {key: release[key] for key in (*package.METADATA, 'generation', 'digest_root_sha256')}
    if 'style' in release:
        expected['style'] = release['style']
    expected.update(schema='sc-relief-pointer/1', status='reviewed', private=False, previous=None,
                    envelope_sha256=verified.envelope_sha256, release_sha256=verified.release_sha256,
                    sha256=archive_row['sha256'], bytes=archive_row['bytes'])
    if expected != {**pointer, 'previous': None}:
        raise stage.StageError('pointer does not match the verified envelope')

    archive, root = stage._objects(pointer)
    # verify_artifacts already hashed the full archive, including its byte count.
    if not 0 < archive_row['bytes'] <= archive.limit:
        raise stage.StageError('archive: invalid object size')
    region_dir = review.parents[2]
    size = layers[package.DIGEST_ROOT]['bytes']
    if not 0 < size <= root.limit:
        raise stage.StageError('digest root: invalid object size')
    with package.artifact_path(region_dir, package.DIGEST_ROOT).open('rb') as stream:
        raw = stream.read(size + 1)
    stage._checked(BytesIO(raw), root, size, phase='digest root')
    # Enumerate the exact checked snapshot, not a second read from disk.
    chunks = tuple(stage._chunks(pointer, root, SimpleNamespace(read_bytes=lambda: raw)))
    local_dir = Path(package.DIGEST_ROOT).parent.as_posix() + '/'
    object_dir = root.key.removesuffix('root.json')
    chunk_rows = [(obj.key.removeprefix(object_dir), obj) for obj in chunks]
    if {p for p in layers if p.startswith(local_dir)} != {
        package.DIGEST_ROOT, *(local_dir + name for name, _ in chunk_rows),
    }:
        raise stage.StageError('verified digest layers do not match the root inventory')
    for name, obj in chunk_rows:
        relative = local_dir + name
        row = layers[relative]
        if row['sha256'] != obj.sha:
            raise stage.StageError(f'chunk {name}: verified layer SHA-256 differs from digest root')
        with package.artifact_path(region_dir, relative).open('rb') as stream:
            stage._checked(stream, obj, row['bytes'], phase=f'chunk {name}')

    return [('archive', archive.name), ('digest root', root.name),
            *((f'chunk {name}', obj.name) for name, obj in chunk_rows)]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--scratch-root', required=True, type=Path, help='disposable local workspace')
    parser.add_argument('--envelope', required=True, type=Path, help='review/<generation>/envelope.json in scratch')
    parser.add_argument('--pointer', required=True, type=Path, help='explicit regional pointer candidate in scratch')
    args = parser.parse_args(argv)
    try:
        rows = _pickup(args.scratch_root, args.envelope, args.pointer)
    except stage.StageError as exc:
        print(f'PLANNING ONLY — refused: {exc}', file=sys.stderr)
        return 2
    except (OSError, ValueError, RecursionError):
        print('PLANNING ONLY — refused: unusable local digest index or scratch path', file=sys.stderr)
        return 2
    print('PLANNING ONLY — Central STAGE pickup checklist (not approval or transport)')
    for label, name in rows:
        print(f'{label}: {name}')
    print(f'Total assets: {len({name for _, name in rows})}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
