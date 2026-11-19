"""Package public relief layers into an immutable release manifest (R6)."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re

from skippercast.paths import repo_root
from skippercast.relief import receipts

RELEASE_SCHEMA = 'sc-relief-release/1'
DISCLAIMER = 'NOT FOR NAVIGATION'
METADATA = ('region', 'bounds', 'minzoom', 'maxzoom', 'sources', 'detail_summary', 'native_support_by_zoom')
LAYERS = 'layers/public/'
# Each producer owns its own leaf (receipts rename a whole target), so the archive is the
# tiles stage's own output, not a copy. The digest index is the digests stage's sibling leaf.
ARCHIVE = LAYERS + 'tiles/relief.pmtiles'
DIGEST_ROOT = LAYERS + 'relief.digests/root.json'
_COMPONENT = re.compile(r'[A-Za-z0-9_-][A-Za-z0-9._-]*')
_RESERVED = {'qa', 'qa.json', 'release.json', 'envelope.json', 'approval.json', 'shots', 'qwen.md'}
_MBARI = re.compile(r'\bmbari\b|monterey bay aquarium research institute', re.I)
_UNKNOWN_LICENSE = {'unknown', 'unlicensed', 'unresolved', 'metadata-review-needed'}


class ReleaseError(ValueError):
    """A relief release or review gate failed; do not publish it."""


def decode_document(data: bytes) -> dict:
    def unique(pairs):
        doc = {}
        for key, value in pairs:
            if key in doc:
                raise ReleaseError(f'duplicate JSON member {key!r}')
            doc[key] = value
        return doc

    doc = json.loads(data.decode('utf-8'), object_pairs_hook=unique)
    if not isinstance(doc, dict):
        raise ReleaseError('expected a JSON object')
    receipts.canonical(doc)  # reject NaN, Infinity and malformed Unicode
    return doc


def artifact_path(root: Path, relative: str) -> Path:
    """Resolve a canonical region-relative artifact path, without symlinks."""
    if not isinstance(relative, str) or not all(_COMPONENT.fullmatch(p) for p in relative.split('/')):
        raise ReleaseError(f'invalid artifact path {relative!r}')
    path = root
    if path.is_symlink():
        raise ReleaseError('region output directory cannot be a symlink')
    for part in relative.split('/'):
        path = path / part
        if path.is_symlink():
            raise ReleaseError(f'symlink in artifact path {relative!r}')
    if not path.is_file():
        raise ReleaseError(f'artifact is missing or not a file: {relative!r}')
    return path


def layer_path(relative: str) -> str:
    if (not isinstance(relative, str) or not relative.startswith(LAYERS)
            or _RESERVED.intersection(relative.lower().split('/'))
            or not all(_COMPONENT.fullmatch(p) for p in relative.split('/'))):
        raise ReleaseError(f'not a public layer path: {relative!r}')
    return relative


def layer_record(root: Path, relative: str) -> dict:
    digest = hashlib.sha256()
    size = 0
    with artifact_path(root, layer_path(relative)).open('rb') as stream:
        for block in iter(lambda: stream.read(1 << 20), b''):
            digest.update(block)
            size += len(block)
    return {'path': relative, 'sha256': digest.hexdigest(), 'bytes': size}


def pointer_schema() -> dict:
    return decode_document((repo_root() / 'catalog/relief/pointer.schema.json').read_bytes())


def validate_schema(doc: dict, schema: dict) -> None:
    # Already supplied by the survey, publish and test extras, not core runtime.
    from jsonschema import Draft202012Validator, ValidationError

    try:
        Draft202012Validator(schema).validate(doc)
    except ValidationError as exc:
        at = '.'.join(map(str, exc.absolute_path)) or 'document'
        raise ReleaseError(f'invalid relief metadata at {at}: {exc.message}') from None


def _lineage(row: dict) -> str:
    rights = row.get('rights', {})
    return ' '.join(str(v) for v in (row.get('id'), row.get('name'), row.get('provider'), row.get('attribution'),
                                     row.get('source_url'), row.get('documentation_url'),
                                     rights.get('attribution'), rights.get('terms_url')))


def validate_metadata(doc: dict, schema: dict, catalog: dict) -> None:
    validate_schema(doc, {'$defs': schema['$defs'], '$ref': '#/$defs/metadata'})
    w, s, e, n = doc['bounds']
    low, high = doc['minzoom'], doc['maxzoom']
    if not (w < e and s < n and low <= high):
        raise ReleaseError('bounds or zooms out of order')
    sources = {row['id']: row for row in doc['sources']}
    if len(sources) != len(doc['sources']):
        raise ReleaseError('duplicate source id')
    catalog_rows = {row['id']: row for row in catalog['sources']}
    for sid, row in sources.items():
        registered = catalog_rows.get(sid, {})
        lineage = _lineage(row) + ' ' + _lineage(registered)
        rights = registered.get('rights', {})
        license_id = row['rights']['license']
        # A description in the assembly manifest cannot clear a catalog hold.
        # An explicit publication denial vetoes the release. The owner's display decision lets a source show
        # inside its contours; it is not a release authorization and never overrides publication_allowed: false.
        if (_MBARI.search(lineage) or registered.get('review_status') != 'approved'
                or registered.get('publication_allowed') is False
                or rights.get('public_display') != 'allowed'
                or rights.get('license') != license_id or license_id.strip().lower() in _UNKNOWN_LICENSE):
            raise ReleaseError(f'source {sid!r} does not have public display rights')

    bands = doc['detail_summary']['depth_bands']
    if ({row['source_id'] for row in bands} != sources.keys()
            or any(row['max_depth_m'] <= row['min_depth_m'] for row in bands)):
        raise ReleaseError('detail summary does not describe the release sources and depth intervals')
    by_zoom = doc['native_support_by_zoom']
    for z in range(8, 18):
        support = by_zoom.get(str(z))
        if not low <= z <= high:
            if support and (support['tiles'] or support['sources']):
                raise ReleaseError(f'tiles outside release zooms at z{z}')
            continue
        if support is None or (not support['tiles'] and (z in (low, high) or support['sources'])):
            raise ReleaseError(f'missing or inconsistent zoom support at z{z}')
        if not support['tiles']:
            continue
        limit = 20 if z >= 16 else 91.44
        if (support.get('limit_m') != limit or (z >= 14 and not support['sources'])
                or (z >= 16 and support.get('support_class') != 3)):
            raise ReleaseError(f'missing required evidence at z{z}')
        for native in support['sources']:
            sid = native['id']
            grid = native['resolution_m']
            relevant = [b for b in bands if b['source_id'] == sid and b['resolution_m'] == grid
                        and b['min_depth_m'] < limit]
            if not relevant or native['tiles'] > support['tiles']:
                raise ReleaseError(f'inconsistent native source summary at z{z}')
            if z >= 16 and (grid > 1 or sources[sid]['label'] != 'measured' or sources[sid].get('estimated')
                            or any(b.get('support_class') != 3 for b in relevant)):
                raise ReleaseError(f'uncertified shallow detail at z{z}')


def release_layers(doc: dict) -> list[dict]:
    rows = doc.get('layers')
    if not isinstance(rows, list) or not rows:
        raise ReleaseError('missing release layers')
    paths = []
    for row in rows:
        if (not isinstance(row, dict) or row.keys() != {'path', 'sha256', 'bytes'}
                or not is_sha256(row['sha256']) or type(row['bytes']) is not int or row['bytes'] < 1):
            raise ReleaseError('invalid release layer record')
        paths.append(layer_path(row['path']))
    if paths != sorted(set(paths)) or ARCHIVE not in paths:
        raise ReleaseError('release layers must be sorted and unique and include relief.pmtiles')
    digest_rows = [row for row in rows if row['path'] == DIGEST_ROOT]
    if not digest_rows:
        raise ReleaseError('relief digest root is required in release layers')
    if doc.get('digest_root_sha256') != digest_rows[0]['sha256']:
        raise ReleaseError('digest root is not bound to its release layer')
    return rows


def is_sha256(value: object) -> bool:
    return isinstance(value, str) and receipts.HEX64.fullmatch(value) is not None


def _check_inventory(root: Path, paths: list[str]) -> None:
    # The digest producer owns its format. Package every file under its dedicated
    # index directory, not merely the root, when that producer is present.
    digest_dir = root / Path(DIGEST_ROOT).parent
    if digest_dir.exists() or digest_dir.is_symlink():
        relative = digest_dir.relative_to(root).as_posix() + '/'
        if digest_dir.is_symlink() or not digest_dir.is_dir():
            raise ReleaseError('invalid relief digest directory')
        members = set()
        for member in digest_dir.rglob('*'):
            if member.is_symlink():
                raise ReleaseError('symlink in relief digest index')
            if not member.is_dir():
                members.add(member.relative_to(root).as_posix())
        if DIGEST_ROOT not in members or members != {p for p in paths if p.startswith(relative)}:
            raise ReleaseError('the entire relief digest index (root and chunks) must be listed')


def stage_parser(stage: str) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog=f'region.py {stage}')
    out = os.environ.get('SC_RELIEF_OUT') or None
    parser.add_argument('--out', type=Path, default=out, required=out is None)
    parser.add_argument('--region', required=True)
    return parser


def stage_region(out: Path, region_id: str, target: str) -> receipts.Region:
    region = receipts.Region(out, region_id)
    if any(p.is_symlink() for p in (region.dir, region.stages_dir, region.dir / target)):
        raise ReleaseError('symlink in release stage output path')
    return region


def main(argv=None) -> int:
    parser = stage_parser('package')
    parser.add_argument('--manifest', type=Path, required=True, help='public layer inventory and metadata JSON')
    parser.add_argument('--upstream', action='append', required=True, help='contributing stage[:scope]; repeat as needed')
    args = parser.parse_args(argv)
    try:
        region = stage_region(args.out, args.region, 'release')
        refs = [receipts.Ref.parse(text) for text in args.upstream]
        if len(refs) != len(set(refs)) or any(ref.scope not in (None, 'public') or ref.stage in {
                'package', 'qa', 'envelope', 'publish'} for ref in refs):
            raise ReleaseError('package needs unique upstream refs from public layer stages')
        raw = args.manifest.read_bytes()
        manifest = decode_document(raw)
        if manifest.keys() != {*METADATA, 'layer_paths'} or manifest['region'] != region.id:
            raise ReleaseError('invalid layer inventory fields or region')
        if not isinstance(manifest['layer_paths'], list):
            raise ReleaseError('layer_paths must be an array')
        paths = sorted(layer_path(p) for p in manifest['layer_paths'])
        if len(paths) != len(set(paths)) or ARCHIVE not in paths:
            raise ReleaseError('layer_paths must be unique and include relief.pmtiles')

        root = repo_root()
        catalog = root / 'catalog/sources.json'
        contract = root / 'regions' / region.id / 'region.json'
        schema = root / 'catalog/relief/pointer.schema.json'
        code = receipts.stage_digest([('package.py', Path(__file__))])
    except (OSError, ValueError) as exc:
        parser.error(str(exc))

    provenance = {}
    inventory = []

    def plan(upstream):
        # Require every actual layer to come from a current producer receipt.
        provenance.update((row['path'], row) for doc in upstream.values() for row in doc['outputs'])
        if 'inventory' in upstream:
            inventory.extend(upstream['inventory']['outputs'])
        return receipts.Plan([receipts.Input(args.manifest, 'manifest'), receipts.Input(catalog, 'rights'),
                              receipts.Input(contract, 'region'), receipts.Input(schema, 'schema')],
                             params={'region': region.id})

    def build(out_dir):
        pending = receipts.read_receipt(region.receipt_path('package'))
        if pending is None:
            raise ReleaseError('package attempt has no receipt')
        expected = {row['role']: row['sha256'] for row in pending['inputs']}
        if any(ref.stage == 'inventory' for ref in refs) and not any(
                row['path'].endswith('/manifest.json') and row['sha256'] == expected['manifest'] for row in inventory):
            raise ReleaseError('layer inventory is not the current inventory stage output')

        def pinned(path, role):
            data = path.read_bytes()
            if receipts.sha256_bytes(data) != expected[role]:
                raise ReleaseError(f'{role} changed during packaging')
            return decode_document(data)

        if receipts.sha256_bytes(raw) != expected['manifest']:
            raise ReleaseError('layer inventory changed during packaging')
        metadata = {key: manifest[key] for key in METADATA}
        validate_metadata(metadata, pinned(schema, 'schema'), pinned(catalog, 'rights'))
        w, s, e, n = metadata['bounds']
        rw, rs, re_, rn = pinned(contract, 'region')['bounds']
        if not (rw <= w < e <= re_ and rs <= s < n <= rn):
            raise ReleaseError('layer bounds must be clipped to the region')
        for path in paths:
            artifact_path(region.dir, path)
        _check_inventory(region.dir, paths)
        rows = [layer_record(region.dir, path) for path in paths]
        for row in rows:
            producer = provenance.get(row['path'], {})
            if any(producer.get(key) != row[key] for key in ('sha256', 'bytes')):
                raise ReleaseError(f'layer bytes are not in the current upstream outputs: {row["path"]}')
        code_sha = pending['code']['repo_sha']
        if not isinstance(code_sha, str) or not re.fullmatch(r'[a-f0-9]{40}', code_sha):
            raise ReleaseError('package must run from a pinned repository checkout')
        release = dict(metadata, schema=RELEASE_SCHEMA, generation=pending['generation'],
                       code_sha=code_sha, private=False, disclaimer=DISCLAIMER,
                       layers=rows, digest_root_sha256=next((r['sha256'] for r in rows if r['path'] == DIGEST_ROOT), None))
        release_layers(release)
        (out_dir / 'release.json').write_bytes(receipts.canonical(release))

    result = receipts.run_stage(receipts.StageRun(region, 'package', build, code,
                                upstream=refs, plan=plan, target='release/{generation}'))
    print(result.line())
    return result.exit_code
