#!/usr/bin/env python3
"""Assemble the deployable Morro stage-preview asset tree from a pinned preview identity.

Offline only: no network, credentials, workflow or deployment. ``assemble`` takes a disposable
candidate checkout that already holds the four candidate files, plus the preview identity
(``sc-morro-preview-identity/1``) derived without approval from the real release envelope. It:

1. refuses the identity unless it is a preview-only identity for the real envelope (no publication
   signature), the four candidate files match its pins, and the pointer is not the placeholder
   fixture (placeholder envelope, missing survey-detail pair, or the known fixture bytes) and binds the
   survey-gap companion that draws the no-survey cue with Layers closed (M32);
2. renders the /sources credits from those exact files and refuses them unless they equal the
   identity's pinned page, all before any output exists;
3. feeds the page into the build input, runs the client build (which fingerprints the shells),
   restores the input page, and checks the built copies of the pointer and contours;
4. writes a new output directory with ``client/``, ``server/`` and ``manifest.json``.

``verify`` rechecks an output directory against its manifest. Neither grants release authority:
the R8 verdict and G's preview authorization are separate.
"""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.relief import morro_sources_overlay as overlay  # noqa: E402

REGION = 'morro-bay'
IDENTITY_SCHEMA = 'sc-morro-preview-identity/1'
MANIFEST_SCHEMA = 'sc-morro-preview-assets/1'
FILES = {
    'pointer': f'catalog/relief/{REGION}.json',
    'catalog_contours': f'catalog/depth-contours/{REGION}.geojson',
    'detail': f'dist/regions/{REGION}/depth-contours.geojson',
    'overview': f'dist/regions/{REGION}/depth-contours-overview.geojson',
}
# Where the client build must carry each pinned file (M8 copies the pointer, the build copies regions).
BUILT = {
    'pointer': f'client/catalog/relief/{REGION}.json',
    'detail': f'client/regions/{REGION}/depth-contours.geojson',
    'overview': f'client/regions/{REGION}/depth-contours-overview.geojson',
}
# The schema-valid synthetic M9/M10 fixture pointer: placeholder envelope and no survey-detail pair.
PLACEHOLDER_POINTERS = frozenset({'0730f89f0165b751502b831c4f12c95b30086499d0fbb22b666ffbf7ef700cfc'})
BUILD_STEPS = (('pnpm', 'build'), ('node', 'scripts/check_client.mjs'))
BUILD_ID = re.compile(r'^[0-9a-f]{10}$')
SHA256 = re.compile(r'^[0-9a-f]{64}$')


class Held(ValueError):
    """The candidate may not be assembled; nothing was written to the output."""


def digest(data: bytes) -> str:
    return sha256(data).hexdigest()


def _sha(value, what):
    if not isinstance(value, str) or not SHA256.match(value):
        raise Held(f'{what}: not a SHA-256')
    if len(set(value)) == 1:
        raise Held(f'{what}: placeholder digest')
    return value


def load_identity(path: Path) -> dict:
    raw = path.read_bytes()
    ident = json.loads(raw)
    if not isinstance(ident, dict) or ident.get('schema') != IDENTITY_SCHEMA or ident.get('region') != REGION:
        raise Held('identity: not a Morro preview identity')
    if 'publication_signature' not in ident or ident['publication_signature'] is not None:
        raise Held('identity: carries a publication signature; preview assets need the unsigned identity')
    for key in ('envelope_sha256', 'release_sha256', 'generation', 'pointer_sha256', 'sources_overlay_html_sha256'):
        _sha(ident.get(key), f'identity {key}')
    files = ident.get('files')
    if not isinstance(files, dict) or set(files) != set(FILES):
        raise Held('identity: must pin exactly the four candidate files')
    for name in FILES:
        _sha(files[name], f'identity {name}')
    if files['pointer'] != ident['pointer_sha256']:
        raise Held('identity: pointer pin disagrees with pointer_sha256')
    if ident['pointer_sha256'] in PLACEHOLDER_POINTERS:
        raise Held('identity: pins the placeholder fixture pointer')
    return {**ident, 'identity_sha256': digest(raw)}


def check_candidate(tree: Path, ident: dict) -> dict:
    """Return the decoded pointer once the tree holds exactly the identity's real-envelope candidate."""
    for name, rel in FILES.items():
        path = tree / rel
        if path.is_symlink() or not path.is_file():
            raise Held(f'{name}: missing or not a regular file')
        if digest(path.read_bytes()) != ident['files'][name]:
            raise Held(f'{name}: SHA-256 differs from the preview identity')
    pointer = json.loads((tree / FILES['pointer']).read_bytes())
    if pointer.get('region') != REGION or pointer.get('status') != 'reviewed' or pointer.get('private') is not False:
        raise Held('pointer: not a reviewed public Morro pointer')
    _sha(pointer.get('envelope_sha256'), 'pointer envelope_sha256')
    for key in ('envelope_sha256', 'release_sha256', 'generation'):
        if pointer.get(key) != ident[key]:
            raise Held(f'pointer: {key} differs from the preview identity')
    detail = pointer.get('survey_detail')
    if not isinstance(detail, dict) or set(detail) != {'decoded', 'wire'}:
        raise Held('pointer: no survey-detail pair; the gap cue would not draw')
    gap = pointer.get('survey_gap')
    if not isinstance(gap, dict) or set(gap) != {'decoded', 'wire'}:
        raise Held('pointer: no survey-gap companion; the no-survey cue would not draw with Layers closed')
    if any(gap[kind] == detail[kind] for kind in ('decoded', 'wire')):
        raise Held('pointer: survey-gap companion repeats the survey detail')
    return pointer


def render_credits(tree: Path, ident: dict, catalogue_sha256: str) -> tuple[bytes, dict]:
    pins = {'pointer': ident['files']['pointer'], 'detail': ident['files']['detail'],
            'overview': ident['files']['overview'], 'catalogue': catalogue_sha256}
    html, receipt = overlay.render(tree, pins)
    if receipt['html_sha256'] != ident['sources_overlay_html_sha256']:
        raise Held('credits: rendered /sources page differs from the preview identity')
    return html, receipt


def run_build(tree: Path) -> None:
    for step in BUILD_STEPS:
        result = subprocess.run(step, cwd=tree, capture_output=True, text=True, timeout=1800)
        if result.returncode:
            raise Held(f'build: {" ".join(step)} exited {result.returncode}: {(result.stdout + result.stderr)[-1500:]}')


def _files(root: Path) -> dict:
    rows = {}
    for path in sorted(root.rglob('*')):
        if path.is_symlink():
            raise Held(f'output: link {path.relative_to(root)}')
        if path.is_file() and path != root / 'manifest.json':
            raw = path.read_bytes()
            rows[path.relative_to(root).as_posix()] = {'sha256': digest(raw), 'bytes': len(raw)}
    return rows


def assemble(tree: Path, identity: Path, catalogue_sha256: str, out: Path, build=None) -> dict:
    build = build or run_build
    tree, out = tree.resolve(strict=True), out.resolve()
    if out.exists():
        raise Held('output: already exists')
    if any(out.is_relative_to(root) for root in (tree, ROOT)):
        raise Held('output: must be outside the controller and candidate trees')
    _sha(catalogue_sha256, 'catalogue pin')
    ident = load_identity(identity)
    pointer = check_candidate(tree, ident)
    html, credits = render_credits(tree, ident, catalogue_sha256)

    page = tree / overlay.register.PAGE
    original = page.read_bytes()
    for stale in ('client', 'server'):
        shutil.rmtree(tree / 'dist' / stale, ignore_errors=True)
    page.write_bytes(html)  # the build fingerprints the shell from this input page
    try:
        build(tree)
    finally:
        page.write_bytes(original)
    dist = tree / 'dist'
    precache = json.loads((dist / 'client/precache.json').read_bytes())
    build_id = precache.get('build')
    if not isinstance(build_id, str) or not BUILD_ID.match(build_id):
        raise Held('build: no fingerprint in precache.json')
    shell = dist / f'client/sources.{build_id}.html'
    if not shell.is_file():
        raise Held('build: no fingerprinted /sources shell')
    for name, rel in BUILT.items():
        built = dist / rel
        if not built.is_file() or digest(built.read_bytes()) != ident['files'][name]:
            raise Held(f'build: {rel} is not the pinned {name}')
    if not (dist / 'server/index.js').is_file():
        raise Held('build: no Worker bundle')
    check_candidate(tree, ident)  # the build must not rewrite the candidate inputs

    with tempfile.TemporaryDirectory(dir=out.parent, prefix=f'.{out.name}.') as temp:
        staged = Path(temp) / 'tree'
        staged.mkdir()
        for part in ('client', 'server'):
            shutil.copytree(dist / part, staged / part, symlinks=True)
        manifest = {
            'schema': MANIFEST_SCHEMA, 'region': REGION,
            'scope': 'stage preview assets only; not a release, R8 verdict or deployment',
            'publication_signature': None,
            'identity_sha256': ident['identity_sha256'],
            **{key: ident[key] for key in ('envelope_sha256', 'release_sha256', 'generation')},
            'candidate': dict(ident['files']), 'catalogue_sha256': catalogue_sha256,
            'survey_detail': pointer['survey_detail'], 'survey_gap': pointer['survey_gap'],
            'sources_overlay_html_sha256': credits['html_sha256'],
            'shading_sources': credits['shading_sources'], 'contour_sources': credits['contour_sources'],
            'build': build_id, 'sources_shell': f'client/sources.{build_id}.html',
            'served': {'/catalog/relief/morro-bay.json': 'pointer', f'/regions/{REGION}/depth-contours.geojson': 'detail',
                       f'/regions/{REGION}/depth-contours-overview.geojson': 'overview',
                       '/sources': f'client/sources.{build_id}.html'},
            'files': _files(staged),
        }
        (staged / 'manifest.json').write_bytes(json.dumps(manifest, indent=2, sort_keys=True).encode() + b'\n')
        os.rename(staged, out)
    return manifest


def verify(out: Path) -> dict:
    manifest = json.loads((out / 'manifest.json').read_bytes())
    if manifest.get('schema') != MANIFEST_SCHEMA or manifest.get('publication_signature') is not None:
        raise Held('manifest: not an unsigned Morro preview asset manifest')
    if _files(out) != manifest['files']:
        raise Held('manifest: output files differ from the manifest')
    for name, rel in BUILT.items():
        if manifest['files'].get(rel, {}).get('sha256') != manifest['candidate'][name]:
            raise Held(f'manifest: {rel} is not the pinned {name}')
    if manifest['sources_shell'] not in manifest['files']:
        raise Held('manifest: no /sources shell')
    return manifest


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest='command', required=True)
    make = sub.add_parser('assemble', help='build the preview asset tree')
    make.add_argument('--tree', type=Path, required=True, help='disposable candidate checkout (it is built in place)')
    make.add_argument('--identity', type=Path, required=True, help='sc-morro-preview-identity/1 document')
    make.add_argument('--catalogue-sha256', required=True, help="release rights pin for catalog/sources.json")
    make.add_argument('--out', type=Path, required=True, help='new directory outside both checkouts')
    check = sub.add_parser('verify', help='recheck an assembled tree against its manifest')
    check.add_argument('--out', type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == 'assemble':
            manifest = assemble(args.tree, args.identity, args.catalogue_sha256, args.out)
        else:
            manifest = verify(args.out)
    except (OSError, ValueError, KeyError, TypeError, overlay.register.RegisterError) as error:
        print(f'Morro preview assets held: {error}', file=sys.stderr)
        return 2
    summary = {k: manifest[k] for k in ('build', 'envelope_sha256', 'identity_sha256', 'sources_shell')}
    summary['files'] = len(manifest['files'])
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
