#!/usr/bin/env python3
"""Evaluate already-produced contour pairs offline; select nothing without --pick.

All input paths are relative to an explicit, disposable --scratch directory.
The manifest has a `candidates` list of {id, full, overview} objects; each file
object has a `path` and its independently accepted `sha256`. Keep both pins in
one candidate row. Do not populate pins from the bytes being evaluated.
An optional `envelope` object (path and accepted sha256) names one generation.
Only exact paths in its verified layer inventory can omit an external pin.
On this base neither contour file is a normal envelope layer.

JSON stdout is a fit report. Only a named, passing candidate adds a `pickup`
record. Exit 1 means the named pair failed, and exit 2 means invalid invocation
or shared inputs. This is neither R8 approval nor authority to publish. Use
stable scratch copies; no geometry or files are written by this command.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys

if __name__ == '__main__':
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'src'))

from skippercast.platform import depth_contours as dc
from skippercast.relief import envelope, package


ROLES = ('full', 'overview')
INPUT_ERRORS = (ValueError, OSError, KeyError, TypeError, AttributeError, RecursionError)


def _document(root, relative):
    return package.decode_document(package.artifact_path(root, relative).read_bytes())


def _generation(root, region_id, ref):
    if not isinstance(ref, dict) or ref.keys() != {'path', 'sha256'} or not package.is_sha256(ref['sha256']):
        raise ValueError('envelope needs an explicit path and accepted SHA-256')
    path = package.artifact_path(root, ref['path'])
    verified = envelope.verify_artifacts(path)
    if verified.release['region'] != region_id or verified.envelope_sha256 != ref['sha256']:
        raise ValueError('verified envelope does not match the region and accepted SHA-256')
    return {path.parents[2] / row['path']: row for row in verified.layers}, verified.generation


def _load(root, ref, layers):
    if not isinstance(ref, dict) or 'path' not in ref or ref.keys() - {'path', 'sha256'}:
        raise ValueError('expected a file path and, for external bytes, an accepted SHA-256')
    path = package.artifact_path(root, ref['path'])
    bound = layers.get(path)
    pin = ref.get('sha256')
    if 'sha256' in ref and not package.is_sha256(pin):
        raise ValueError('invalid accepted SHA-256')
    if bound is None and pin is None:
        raise ValueError('external file needs an accepted SHA-256 (not R8-proven)')
    raw = path.read_bytes()
    digest, size = hashlib.sha256(raw).hexdigest(), len(raw)
    if bound is not None and (bound['sha256'] != digest or bound['bytes'] != size):
        raise ValueError('file differs from its generation-bound bytes')
    if pin is not None and pin != digest:
        raise ValueError('accepted SHA-256 mismatch')
    # Decode exactly the bytes counted and hashed, not a second read or a re-encoding.
    return package.decode_document(raw), digest, size, bool(bound)


def _pair_metadata(full, overview):
    # These are the only provenance fields the shipping overview projection changes.
    projected = {'overview', 'coordinate_decimals', 'features'}

    def common(value):
        return {key: item for key, item in value.items() if key not in projected}

    if ('overview' in full or overview.get('overview', {}).get('max_zoom') != dc.OVERVIEW_MAX_ZOOM
            or common(full) != common(overview)):
        raise ValueError('full and overview do not have matching pair provenance and roles')


def _fit(root, candidate, region, sources, pointer, layers):
    row = {'id': candidate['id'], 'fits': False, 'files': {}}
    loaded, errors = {}, {}
    for role in ROLES:
        try:
            loaded[role] = _load(root, candidate[role], layers)
            collection, _, size, bound = loaded[role]
            row['files'][role] = {
                'bytes': size,
                'binding': 'generation-bound' if bound else 'external-pin-not-R8-proven',
            }
            if collection.get('provenance', {}).get('set') not in (dc.FT_V2, dc.FT_V3):
                raise ValueError('expected an ft-v2 or ft-v3 contour collection')
            if dc.check_catalog_contours(collection, region, sources, pointer) is None:
                raise ValueError('expected an explicit reviewed pointer for this region')
        except INPUT_ERRORS as exc:
            errors[role] = str(exc)

    if 'full' in loaded and 'full' not in errors:
        for role, cap in zip(ROLES, dc.size_budgets(loaded['full'][0])):
            if role in row['files']:
                info = row['files'][role]
                info.update(cap_bytes=cap, within_cap=info['bytes'] <= cap)
                if not info['within_cap']:
                    errors.setdefault(role, f"{info['bytes']} bytes exceeds {cap}-byte cap")
    if not errors:
        try:
            _pair_metadata(*(loaded[role][0]['provenance'] for role in ROLES))
        except INPUT_ERRORS as exc:
            errors['pair'] = str(exc)
    if errors:
        row['errors'] = errors
        return row, None
    row['fits'] = True
    return row, {role: loaded[role][1] for role in ROLES}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--scratch', required=True, type=Path, help='quiescent disposable input directory')
    for option in ('region', 'catalog', 'pointer', 'manifest'):
        parser.add_argument(f'--{option}', required=True, help=f'{option} JSON path relative to --scratch')
    parser.add_argument('--pick', help='exact candidate ID to emit if both files pass')
    args = parser.parse_args(argv)
    try:
        root = args.scratch.absolute()
        if root != root.resolve(strict=True) or not root.is_dir():
            raise ValueError('--scratch must be a directory with no symlinks in its path')
        region, catalog, pointer, manifest = (
            _document(root, path) for path in (args.region, args.catalog, args.pointer, args.manifest)
        )
        region_id = region['id']
        if not isinstance(region_id, str) or not region_id:
            raise ValueError('region requires an ID')
        sources = {source['id']: source for source in catalog['sources']}
        if len(sources) != len(catalog['sources']):
            raise ValueError('duplicate source IDs in catalog')
        candidates = manifest['candidates']
        if (manifest.keys() - {'candidates', 'envelope'} or not isinstance(candidates, list) or not candidates
                or any(not isinstance(row, dict) or row.keys() != {'id', *ROLES}
                       or not isinstance(row['id'], str) or not row['id'].strip() for row in candidates)):
            raise ValueError('manifest needs one or more {id, full, overview} candidate rows')
        ids = {row['id'] for row in candidates}
        if len(ids) != len(candidates):
            raise ValueError('duplicate candidate ID')
        if args.pick is not None and args.pick not in ids:
            raise ValueError('--pick must name a candidate in the manifest')
        layers, generation = (_generation(root, region_id, manifest['envelope'])
                              if 'envelope' in manifest else ({}, None))
    except INPUT_ERRORS as exc:
        parser.error(str(exc))

    report = {'region': region_id, 'candidates': []}
    if generation is not None:
        report['generation'] = generation
    for candidate in candidates:
        row, hashes = _fit(root, candidate, region, sources, pointer, layers)
        report['candidates'].append(row)
        if args.pick == row['id'] and hashes is not None:
            bindings = {file['binding'] for file in row['files'].values()}
            report['pickup'] = {
                'candidate': row['id'],
                'sha256': hashes,
                'binding': ('external-pin-not-R8-proven' if 'external-pin-not-R8-proven' in bindings
                            else 'generation-bound'),
            }
    print(json.dumps(report, indent=2))
    return int(args.pick is not None and 'pickup' not in report)


if __name__ == '__main__':
    sys.exit(main())
