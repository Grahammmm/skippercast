#!/usr/bin/env python3
"""Build a disposable Central Coast Chart from the C47 preview identities.

Input pins come from the existing local readback, not from the input files being tested.
No release pointer, raw survey, Worker, service binding, upload or deployment is produced.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime, timezone
import json
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT)]

from scripts.relief import central_preview_identities as identities  # noqa: E402
from scripts.relief import central_preview_recovery as recovery  # noqa: E402
from scripts.relief import central_preview_tree as tree  # noqa: E402
from scripts.relief.central_sources_overlay import _contour_rows, _credits, register  # noqa: E402
from skippercast.platform import depth_contours as depths  # noqa: E402
from skippercast.relief import envelope, package, receipts  # noqa: E402

BANDS = dict(zip(tree.CONTOURS, identities.CONTOUR_PAIR, strict=True))
LIMITS = {'detail': depths.V2_MAX_BYTES, 'overview': depths.V2_OVERVIEW_MAX_BYTES}
DIGEST_DIR = package.DIGEST_ROOT.removesuffix('root.json')
SCRIPT = 'scripts/relief/central_isolated_preview.mjs'
MARKER = 'CENTRAL-LOOPBACK-BINDINGS.json'


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def pinned(path, sha, size=None):
    require(package.is_sha256(sha), 'expected a SHA-256 pin')
    raw = path.read_bytes()
    require((size is None or len(raw) == size) and receipts.sha256_bytes(raw) == sha, f'bytes differ from pin: {path.name}')
    return raw


def read_identities(path, sha):
    doc = package.decode_document(pinned(path, sha))
    require(doc.get('schema') == identities.SCHEMA and doc.get('purpose') == 'offline-preview-only'
            and set(doc.get('regions', {})) == set(identities.REGIONS), 'expected the exact six Central preview identities')
    return doc['regions']


def derivatives(config, release, catalogue, pair, today: date):
    """Check each QA-bound ft-v3 band, changing only expiry fields from source-review evidence."""
    result, features, shared = {}, {}, None
    admitted = {row['id'] for row in release['sources']}
    require(set(pair) == set(BANDS), 'expected complete overview and detail pair')
    style = release['style']['contours']
    for band, raw in pair.items():
        doc = package.decode_document(raw)
        prov = doc['provenance']
        require(prov['bounds'] == config['bounds'] and 'review_expires' not in prov and 'review_days' not in prov,
                'expected the original unstamped region bounds')
        credits = list(_contour_rows(doc, config['id'], band, style))
        listed = {row[0] for row in credits}
        selected = listed | {row['source_id'] for row in prov['sources_omitted']}
        require(len(listed) == len(credits) and selected <= admitted, 'contour sources differ from exact envelope')
        require(all(text.strip() and text == catalogue[sid]['rights']['attribution'] for sid, text, _ in credits),
                'missing or changed contour credit')
        depths.check_selected_contours(doc, config, catalogue, selected)
        expires = depths.review_expires(doc, catalogue)
        require(all(date.fromisoformat(catalogue[sid]['reviewed_at'][:10]) <= today for sid in listed)
                and today <= date.fromisoformat(expires), 'source review not current')
        binding = (prov['sources'], prov['sources_omitted'], expires)
        require(shared is None or shared == binding, 'mixed pair: the bands disagree on source identity')
        shared = binding
        features[band] = {feature['id']: feature for feature in doc['features']}
        require(len(features[band]) == len(doc['features']), 'duplicate feature ID')
        prov.update(review_expires=expires, review_days=depths.SOURCE_REVIEW_DAYS)
        result[band] = receipts.canonical(doc)
        require(len(result[band]) <= LIMITS[band], f'{band} contour byte budget exceeded')
    require(all(features['detail'].get(key) == feature for key, feature in features['overview'].items()),
            'mixed pair: overview is not part of detail')
    return result


def candidate(repo, relief, identities_path, identity_sha, today):
    rows = read_identities(identities_path, identity_sha)
    catalogue_raw = package.artifact_path(repo, 'catalog/sources.json').read_bytes()
    catalogue_sha = receipts.sha256_bytes(catalogue_raw)
    catalogue = package.decode_document(catalogue_raw)
    by_source = {row['id']: row for row in catalogue['sources']}
    schema = package.decode_document(package.artifact_path(repo, 'catalog/relief/pointer.schema.json').read_bytes())
    result, overlays, feeds, releases = {}, {}, {}, {}
    for name, row in sorted(rows.items()):
        terrain_only = name in identities.TERRAIN_ONLY
        require(row['region'] == name and row['rights_catalogue_sha256'] == catalogue_sha
                and row['candidate_kind'] == ('terrain-only' if terrain_only else 'terrain+contours'),
                f'{name}: wrong region, disposition or rights catalogue')
        root = relief / name
        gen = row['generation']
        require(package.is_sha256(gen), f'{name}: invalid generation')
        verified = envelope.verify_artifacts(package.artifact_path(root, f'review/{gen}/envelope.json'))
        require((verified.envelope_sha256, verified.release_sha256, verified.qa_sha256, verified.layers)
                == (row['envelope_sha256'], row['release_sha256'], row['qa_sha256'], row['layers']),
                f'{name}: pinned envelope, QA or layer inventory changed')
        release = verified.release
        require(release['region'] == name, f'{name}: release region differs')
        package.validate_metadata(release, schema, catalogue)
        releases[name] = release
        pins = {entry['path']: entry for entry in row['contours']}
        require(set(pins) == (set() if terrain_only else set(BANDS.values())) and len(pins) == len(row['contours']),
                f'{name}: unexpected contour pair')
        contours = {}
        if pins:
            config = package.decode_document(package.artifact_path(repo, f'regions/{name}/region.json').read_bytes())
            raw = {band: pinned(package.artifact_path(root, rel), pins[rel]['sha256'], pins[rel]['bytes']) for band, rel in BANDS.items()}
            for band, body in derivatives(config, release, by_source, raw, today).items():
                path = f'/regions/{name}/{tree.CONTOURS[band]}'
                overlays[path] = body
                contours[path] = receipts.sha256_bytes(body)
        archive = next(entry for entry in verified.layers if entry['path'] == package.ARCHIVE)
        stem = f'feeds/tiles/relief/{name}/{archive["sha256"]}'
        root_sha = release['digest_root_sha256']
        require(package.is_sha256(root_sha), f'{name}: no tile integrity root')
        offered = {entry['path']: entry for entry in verified.layers if entry['path'].startswith(DIGEST_DIR)}
        require(offered.get(package.DIGEST_ROOT, {}).get('sha256') == root_sha, f'{name}: tile integrity root changed')
        paths = {f'{stem}.pmtiles': archive, **{f'{stem}.digests/{root_sha}/{key.removeprefix(DIGEST_DIR)}': entry
                                                for key, entry in offered.items()}}
        for path, entry in paths.items():
            feeds[path] = pinned(package.artifact_path(root, entry['path']), entry['sha256'], entry['bytes'])
        # Data for the preview's in-process renderer only. No status, release schema, previous, or review verdict.
        terrain = {key: release[key] for key in (*package.METADATA, 'digest_root_sha256', 'style')}
        terrain.update(sha256=archive['sha256'], bytes=archive['bytes'], private=False,
                       release_sha256=verified.release_sha256, envelope_sha256=verified.envelope_sha256)
        result[name] = {'preview_id': row['preview_id'], 'envelope': verified.envelope_sha256, 'qa': verified.qa_sha256,
                        'rights': catalogue_sha, 'style': release['style']['contours'], 'terrain': terrain, 'contours': contours}
    return result, overlays, feeds, releases


def write(root, name, raw):
    path = root / name
    require(path == path.resolve(), f'linked destination: {name}')
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)


def source_overlay(repo, releases, overlays):
    data = register.collect(repo)
    data['regions'] = [row for row in data['regions'] if row['id'] in releases]
    require({row['id'] for row in data['regions']} == releases.keys(), 'missing Central credits sections')
    for row in data['regions']:
        name = row['id']
        release = releases[name]
        row['layers'][register.DEPTH_SHADING] = _credits(data['sources'],
            ((src['id'], src['attribution'], src['survey_dates']) for src in release['sources']))
        row['layers'].pop(register.DEPTH_CONTOURS, None)
        row['depth_detail'] = register._depth_detail(release)
        path = f'/regions/{name}/{tree.CONTOURS["detail"]}'
        if path in overlays:
            credits = _contour_rows(package.decode_document(overlays[path]), name, 'detail', release['style']['contours'])
            row['layers'][register.DEPTH_CONTOURS] = _credits(data['sources'], credits)
    block, _ = register.render(data)
    base = package.artifact_path(repo, register.PAGE.as_posix()).read_text(encoding='utf-8')
    return register.splice(base, block).replace('<h1>', '<p>Local Central Coast preview; not a release.</p><h1>', 1).encode()


def project_indexes(repo, rows, overlays):
    index = package.decode_document(package.artifact_path(repo, 'dist/regions/index.json').read_bytes())
    index['regions'] = [row for row in index['regions'] if row['id'] in rows]
    require({row['id'] for row in index['regions']} == rows.keys(), 'region picker lacks a Central region')
    index['default_region'] = 'cambria-san-simeon'
    for row in index['regions']:
        name, path = row['id'], 'dist/' + row['config']
        config = package.decode_document(package.artifact_path(repo, path).read_bytes())
        pair = set(tree.CONTOURS.values())
        require(config['id'] == name and path == f'dist/regions/{name}/region.json', 'wrong Chart index scope')
        config['chart_files'] = [leaf for leaf in config['chart_files'] if leaf not in pair]
        config['chart_files'] += sorted(leaf for leaf in pair if f'/regions/{name}/{leaf}' in overlays)
        raw = receipts.canonical(config)
        write(repo, path, raw)
        row['manifest'] = receipts.sha256_bytes(raw)
    write(repo, 'dist/regions/index.json', receipts.canonical(index))


def inventory(root):
    result = {}
    for path in sorted(root.rglob('*')):
        if path.is_symlink():
            raise ValueError(f'linked preview asset: {path.name}')
        if path.is_file():
            raw = path.read_bytes()
            result[path.relative_to(root).as_posix()] = {'sha256': receipts.sha256_bytes(raw), 'bytes': len(raw)}
    return result


def verify_client(client, rows, html):
    build = package.decode_document(package.artifact_path(client, 'precache.json').read_bytes())['build']
    require(tree.generated_block(package.artifact_path(client, f'sources.{build}.html').read_bytes()) == tree.generated_block(html),
            'built /sources credits differ from the verified overlay')
    regions = {p.name for p in (client / 'regions').iterdir() if p.is_dir()}
    require(regions == rows.keys() and not (client / 'catalog/relief').exists(), 'unexpected built region or release pointers')
    for id_, row in rows.items():
        config = package.decode_document(package.artifact_path(client, f'regions/{id_}/region.json').read_bytes())
        known = {path.rsplit('/', 1)[-1] for path in row['contours']}
        actual = {path.name for path in (client / 'regions' / id_).glob('depth-contours*.geojson')}
        require(known == actual and sorted(known) == sorted(set(tree.CONTOURS.values()) & set(config['chart_files'])),
                f'{id_}: built index or contour scope differs')
        for path, sha in row['contours'].items():
            pinned(package.artifact_path(client, path[1:]), sha)
    return build


def assemble(review, head, relief, identities_path, identity_sha, basemap, basemap_sha, out):
    dest = recovery._refuse_checkout_destination(out, 'Central preview')
    require(out.absolute() == dest and not dest.exists() and dest.parent.is_dir(), 'expected a new local preview directory')
    review = review.resolve(strict=True)
    git = ('git', '-C', str(review))
    require(subprocess.check_output((*git, 'rev-parse', '--show-toplevel'), text=True).strip() == str(review)
            and subprocess.check_output((*git, 'rev-parse', 'HEAD'), text=True).strip() == head
            and not subprocess.check_output((*git, 'status', '--porcelain'), text=True), 'expected the clean exact review checkout')
    require(relief.absolute() == relief.resolve(strict=True) and relief.is_dir(), 'expected canonical local relief root')
    base = pinned(basemap, basemap_sha)
    with tempfile.TemporaryDirectory(dir=dest.parent, prefix='.central-loopback-') as scratch:
        tmp = Path(scratch)
        repo, archive, staged = tmp / 'checkout', tmp / 'checkout.tar', tmp / 'result'
        subprocess.run((*git, 'archive', f'--output={archive}', head), check=True, timeout=120)
        with tarfile.open(archive) as bundle:
            bundle.extractall(repo, filter='data')
        rows, overlays, feeds, releases = candidate(repo, relief, identities_path, identity_sha, datetime.now(timezone.utc).date())
        html = source_overlay(repo, releases, overlays)
        write(repo, register.PAGE.as_posix(), html)
        app_path = 'dist/app.html'
        app = package.artifact_path(repo, app_path).read_bytes()
        require(app.count(b'<body>') == 1, 'expected a single app body for local scope notice')
        notice = b'<body><div role="note">Local Central Coast preview - not for navigation or release.</div>'
        write(repo, app_path, app.replace(b'<body>', notice))
        for path, raw in overlays.items():
            write(repo, 'dist' + path, raw)
        project_indexes(repo, rows, overlays)
        bindings = repo / MARKER
        bindings.write_bytes(receipts.canonical(rows))
        subprocess.run(tree.STEPS[0], cwd=repo, check=True, timeout=120, stdout=sys.stderr)
        subprocess.run(('node', SCRIPT, 'build-local', MARKER), cwd=repo, check=True, timeout=300, stdout=sys.stderr)
        client = repo / 'dist/client'
        tree.normalize_vite_index(client, repo)
        subprocess.run(tree.STEPS[2], cwd=repo, check=True, timeout=120, stdout=sys.stderr)
        build = verify_client(client, rows, html)
        staged.mkdir()
        client.rename(staged / 'client')
        key = f'tiles/basemap/{basemap_sha}.pmtiles'
        for path, raw in {**feeds, f'feeds/{key}': base,
                          'feeds/tiles/basemap/manifest.json': receipts.canonical({'key': key})}.items():
            write(staged, path, raw)
        manifest = {'schema': 'sc-central-isolated-preview/1', 'scope': 'loopback-only', 'base': head,
                    'input_sha256': identity_sha, 'build': build, 'basemap_sha256': basemap_sha, 'files': inventory(staged),
                    'regions': {name: {key: val for key, val in row.items() if key != 'terrain'} for name, row in rows.items()}}
        raw = receipts.canonical(manifest)
        write(staged, 'manifest.json', raw)
        staged.rename(dest)
    return receipts.sha256_bytes(raw)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ('review', 'relief', 'identities', 'basemap', 'out'):
        parser.add_argument(f'--{key}', required=True, type=Path)
    for key in ('head', 'identities-sha', 'basemap-sha'):
        parser.add_argument(f'--{key}', required=True)
    args = parser.parse_args()
    try:
        sha = assemble(args.review, args.head, args.relief, args.identities, args.identities_sha,
                       args.basemap, args.basemap_sha, args.out)
    except (OSError, ValueError, KeyError, TypeError, tarfile.TarError, register.RegisterError, subprocess.SubprocessError) as exc:
        print(f'Central preview refused: {exc}', file=sys.stderr)
        return 2
    print(f'LOCAL PREVIEW {sha} {args.out}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
