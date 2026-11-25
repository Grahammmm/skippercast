#!/usr/bin/env python3
"""Build a disposable Central Coast rehearsal client; no hosting or release approval.

Pass the reviewed candidate worktree with its fourteen local overlay files, the
Central sources-renderer pins and the independently pinned C27 bundle. The build
runs from a Git archive, not from the reviewed tree or any production checkout.
Only the client tree is collected; /feeds archives stay outside this build.
"""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import re
import subprocess
import sys
import tarfile
import tempfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'src'))

from scripts.relief import central_sources_overlay as sources  # noqa: E402
from scripts.relief.central_stage_handoff import CENTRAL_RELEASES  # noqa: E402
from skippercast.relief.package import artifact_path, decode_document  # noqa: E402

TERRAIN_ONLY = {'monterey-point-sur', 'santa-cruz-monterey-bay'}
CONTOURS = {'detail': 'depth-contours.geojson', 'overview': 'depth-contours-overview.geojson'}
STEPS = (('pnpm', 'install', '--offline', '--frozen-lockfile', '--ignore-scripts'),
         ('pnpm', 'build'), ('node', 'scripts/check_client.mjs'))


def digest(raw):
    return sha256(raw).hexdigest()


def candidate(review, pins, bundle):
    """Join independent regional identities and snapshot the exact overlay bytes."""
    regions = set(CENTRAL_RELEASES)
    if (bundle['schema'] != 'sc-central-preview-bundle/1' or set(bundle['regions']) != regions
            or set(pins['regions']) != regions):
        raise ValueError('exactly the six Central scopes are required')
    snapshot = {}
    for region in sorted(regions):
        row, pin = bundle['regions'][region], pins['regions'][region]
        terrain = region in TERRAIN_ONLY
        kind = 'terrain-only' if terrain else 'terrain+contours'
        if row['region'] != region or row['kind'] != kind:
            raise ValueError(f'{region}: wrong bundle scope or terrain classification')
        pointer_path = f'catalog/relief/{region}.json'
        paths = {'pointer': pointer_path}
        for key, name in CONTOURS.items():
            path = f'regions/{region}/{name}'
            if not terrain:
                paths[key] = path
            elif (review / 'dist' / path).exists() or (review / 'dist' / path).is_symlink():
                raise ValueError(f'{region}: terrain-only cannot carry contours')
        served = {url: entry['sha256'] for url, entry in row['served'].items()
                  if not url.startswith(f'/feeds/tiles/relief/{region}/')}
        if set(pin) != set(paths) or served != {
            '/sources': bundle['sources_page_sha256'], **{f'/{url}': pin[key] for key, url in paths.items()}
        }:
            raise ValueError(f'{region}: overlay paths or pins differ from bundle')
        for key, path in paths.items():
            source_path = path if key == 'pointer' else f'dist/{path}'
            raw = artifact_path(review, source_path).read_bytes()
            if digest(raw) != pin[key]:
                raise ValueError(f'{region}: {key} does not match the pinned bytes')
            snapshot[path] = raw
        pointer = decode_document(snapshot[pointer_path])
        if (pointer['schema'] != 'sc-relief-pointer/1' or pointer['private'] is not False
                or pointer['region'] != region or any(pointer[key] != row[key] for key in
                                                      ('generation', 'envelope_sha256', 'release_sha256'))):
            raise ValueError(f'{region}: pointer does not identify the pinned regional envelope')
    return snapshot


def generated_block(page):
    begin, end = sources.register.BEGIN.encode(), sources.register.END.encode()
    if page.count(begin) != 1 or page.count(end) != 1 or page.index(begin) >= page.index(end):
        raise ValueError('sources: missing or invalid generated credits block')
    return page.split(begin, 1)[1].split(end, 1)[0]


def contour_indexes(root, snapshot, *, update=False):
    """Bind the Chart loader's region-local index to the exact preview overlay."""
    names = set(CONTOURS.values())
    for region in sorted(CENTRAL_RELEASES):
        if f'catalog/relief/{region}.json' not in snapshot:
            continue
        index = artifact_path(root, f'regions/{region}/region.json')
        doc = decode_document(index.read_bytes())
        files = doc.get('chart_files')
        if doc.get('id') != region or not isinstance(files, list) or not all(isinstance(f, str) for f in files):
            raise ValueError(f'{region}: invalid region or chart_files in Chart index')
        wanted = sorted(name for name in names if f'regions/{region}/{name}' in snapshot)
        listed = sorted(name for name in files if name in names)
        if listed == wanted:
            continue
        if not update:
            raise ValueError(f'{region}: chart_files does not match pinned contours')
        doc['chart_files'] = [name for name in files if name not in names] + wanted
        index.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def check_client(client, snapshot, html, baseline):
    build = decode_document((client / 'precache.json').read_bytes())['build']
    if not isinstance(build, str) or not re.fullmatch(r'[0-9a-f]{10}', build):
        raise ValueError('invalid client build ID')
    shell = f'sources.{build}.html'
    if generated_block((client / shell).read_bytes()) != generated_block(html):
        raise ValueError('built sources shell has stale credits')
    expected = snapshot | baseline
    for path, raw in expected.items():
        if artifact_path(client, path).read_bytes() != raw:
            raise ValueError(f'built bytes differ: {path}')
    actual = {p.relative_to(client).as_posix() for p in (client / 'catalog/relief').glob('*.json')}
    actual |= {p.relative_to(client).as_posix() for p in (client / 'regions').glob('*/depth-contours*.geojson')}
    if actual != expected.keys():
        raise ValueError(f'wrong Central scope: {sorted(actual ^ expected.keys())}')
    contour_indexes(client, snapshot)
    return build, shell


def normalize_vite_index(client, repo):
    # Vite emits some CSS keys and src values as absolute paths. They are
    # build metadata, not URLs; preserve their asset mappings without host paths.
    index = client / '.vite/manifest.json'
    original = decode_document(index.read_bytes())
    prefix = f'{repo}/'
    normalized = {}
    for key, row in original.items():
        relative = key.removeprefix(prefix)
        if relative in normalized:
            raise ValueError(f'duplicate normalized Vite key: {relative}')
        if isinstance(row.get('src'), str):
            row['src'] = row['src'].removeprefix(prefix)
        normalized[relative] = row
    text = json.dumps(normalized, sort_keys=True, indent=2) + '\n'
    if prefix in text:
        raise ValueError('Vite index still contains the disposable checkout path')
    index.write_text(text, encoding='utf-8')


def assemble(review, pins_path, bundle_path, bundle_sha256, out):
    review, out = review.resolve(strict=True), out.resolve()
    if out.exists() or out.is_relative_to(review) or out.is_relative_to(ROOT) or not out.parent.is_dir():
        raise ValueError('output must be a new tree outside both checkouts with an existing parent')
    bundle_raw, pins_raw = bundle_path.read_bytes(), pins_path.read_bytes()
    if digest(bundle_raw) != bundle_sha256:
        raise ValueError('bundle differs from independent pin')
    bundle, pins = decode_document(bundle_raw), decode_document(pins_raw)
    snapshot = candidate(review, pins, bundle)
    html, credits = sources.render(review, pins)
    if credits['html_sha256'] != bundle['sources_page_sha256']:
        raise ValueError('generated sources page differs from the pinned bundle')
    git = ('git', '-C', str(review))
    if subprocess.check_output((*git, 'rev-parse', '--show-toplevel'), text=True).strip() != str(review):
        raise ValueError('review must be the root of a candidate Git worktree')
    head = subprocess.check_output((*git, 'rev-parse', 'HEAD'), text=True).strip()
    overlay_paths = {path if path.startswith('catalog/') else f'dist/{path}' for path in snapshot}
    status = subprocess.check_output((*git, 'status', '--porcelain=v1', '-z', '--no-renames', '--untracked-files=all'), text=True)
    if any(row[3:] not in overlay_paths for row in status.rstrip('\0').split('\0') if row):
        raise ValueError('review tree changes files outside the Central overlay')
    with tempfile.TemporaryDirectory(dir=out.parent, prefix='.central-preview-') as scratch:
        tmp = Path(scratch)
        repo = tmp / 'checkout'
        archive = tmp / 'checkout.tar'
        subprocess.run((*git, 'archive', f'--output={archive}', head), check=True, timeout=120)
        with tarfile.open(archive) as tar:
            tar.extractall(repo, filter='data')
        for path, raw in snapshot.items():
            target = repo / (path if path.startswith('catalog/') else f'dist/{path}')
            # Only known overlay paths may be overwritten in the disposable archive.
            if target.resolve() != target:
                raise ValueError(f'overlay path traverses a link: {path}')
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)
        contour_indexes(repo / 'dist', snapshot, update=True)
        baseline = {}
        for name in CONTOURS.values():  # retain only these ordinary Morro v1 base assets, byte for byte
            rel = f'regions/morro-bay/{name}'
            if (repo / 'dist' / rel).exists():
                baseline[rel] = artifact_path(repo, f'dist/{rel}').read_bytes()
        page = artifact_path(repo, sources.register.PAGE.as_posix())
        page.write_bytes(html)
        for step in STEPS[:2]:
            subprocess.run(step, cwd=repo, check=True, timeout=300, stdout=sys.stderr)
        client = repo / 'dist/client'
        normalize_vite_index(client, repo)
        subprocess.run(STEPS[2], cwd=repo, check=True, timeout=300, stdout=sys.stderr)
        build, shell = check_client(client, snapshot, html, baseline)
        staged = tmp / 'result'
        staged.mkdir()
        files = {}
        for path in sorted(client.rglob('*')):
            if path.is_symlink():
                raise ValueError(f'built client contains a link: {path.relative_to(client)}')
            if path.is_file():
                raw = path.read_bytes()
                files[f'client/{path.relative_to(client).as_posix()}'] = {'bytes': len(raw), 'sha256': digest(raw)}
        client.rename(staged / 'client')
        manifest = {'schema': 'sc-central-stage-tree/1', 'scope': 'local rehearsal; no R8, hosting or release',
                    'regions': sorted(CENTRAL_RELEASES), 'base': head, 'pins_sha256': digest(pins_raw),
                    'bundle_sha256': bundle_sha256, 'sources_overlay_html_sha256': credits['html_sha256'],
                    'pinned': {f'/{path}': digest(raw) for path, raw in snapshot.items()},
                    'envelopes': {region: row['envelope_sha256'] for region, row in bundle['regions'].items()},
                    'build': build, 'sources_shell': f'client/{shell}', 'files': files,
                    'served': {**{f'/{path}': f'client/{path}' for path in snapshot}, '/sources': f'client/{shell}'}}
        (staged / 'manifest.json').write_text(json.dumps(manifest, sort_keys=True, indent=2) + '\n', encoding='utf-8')
        staged.rename(out)
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for option in ('review', 'pins', 'bundle', 'out'):
        parser.add_argument(f'--{option}', type=Path, required=True)
    parser.add_argument('--bundle-sha256', required=True)
    args = parser.parse_args()
    try:
        result = assemble(args.review, args.pins, args.bundle, args.bundle_sha256, args.out)
    except (ValueError, OSError, KeyError, TypeError, tarfile.TarError, subprocess.SubprocessError,
            sources.register.RegisterError) as exc:
        print(f'Central preview held: {exc}', file=sys.stderr)
        return 2
    print(json.dumps({'build': result['build'], 'files': len(result['files']), 'hosted': False}, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
