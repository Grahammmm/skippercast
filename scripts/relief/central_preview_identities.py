#!/usr/bin/env python3
"""Print a local Central preview manifest, not a release pointer or approval.

Use the admitted readback and its independently recorded SHA-256. Contour files
are raw QA inputs, not browser-ready or approved for upload. The next stage
must rehash any bytes it consumes and validate its own served derivatives.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT)]

from scripts.relief.central_region_packet_compare import REGIONS, _link, _output, _read_stage  # noqa: E402
from skippercast.relief import envelope, package, receipts  # noqa: E402

TERRAIN_ONLY = frozenset({'monterey-point-sur', 'santa-cruz-monterey-bay'})
CONTOUR_PAIR = ('layers/contours/contours.geojson', 'layers/contours/contours-overview.geojson')
SCHEMA = 'sc-central-preview-identities/1'


def _region(root: Path, pin: dict, rights: str) -> dict:
    for key in ('envelope_sha256', 'release_sha256', 'qa_sha256', 'archive_sha256'):
        if not package.is_sha256(pin.get(key)):
            raise ValueError(f'invalid readback field {key}')
    if 'publication_signature' not in pin or pin['publication_signature'] is not None:
        raise ValueError('expected an unsigned local readback')
    if pin.get('rights_catalogue_sha256') != rights:
        raise ValueError('rights catalogue does not match pinned readback')

    packed = _read_stage(root, 'package')
    gen = packed['generation']
    path = package.artifact_path(root, f'review/{gen}/envelope.json')
    if receipts.sha256_file(path) != pin['envelope_sha256']:
        raise ValueError('envelope differs from pinned readback')
    verified = envelope.verify_artifacts(path)
    layers = verified.layers
    archive = next(row for row in layers if row['path'] == package.ARCHIVE)
    if (verified.release['region'] != root.name or verified.envelope_sha256 != pin['envelope_sha256']
            or verified.release_sha256 != pin['release_sha256'] or verified.qa_sha256 != pin['qa_sha256']
            or archive['sha256'] != pin['archive_sha256'] or len(layers) != pin.get('layers_rehashed')):
        raise ValueError('verified artifacts differ from pinned readback')
    if [row['sha256'] for row in packed['inputs'] if row['role'] == 'rights'] != [rights]:
        raise ValueError('rights catalogue does not match the package receipt')

    qa_stage = _read_stage(root, 'qa')
    contour_stage = _read_stage(root, 'contours')
    for child, parent in ((qa_stage, packed), (qa_stage, contour_stage), (packed, contour_stage)):
        _link(child, parent)
    qa, qa_sha = _output(root, qa_stage, f'qa/{gen}/qa.json')
    if qa_sha != verified.qa_sha256:
        raise ValueError('QA receipt does not match verified envelope')
    counts = qa['metrics']['contour_count_by_interval_ft']
    has_contours = root.name not in TERRAIN_ONLY
    kind = 'terrain+contours' if has_contours else 'terrain-only'
    if (pin.get('candidate_kind') != kind or not isinstance(counts, dict)
            or any(type(n) is not int or n < 0 for n in counts.values()) or any(counts.values()) != has_contours):
        raise ValueError('pinned disposition does not match bound QA contour coverage')
    contour_rows = []
    detail_features = {}
    for relative in CONTOUR_PAIR:
        doc, digest = _output(root, contour_stage, relative)
        features = doc.get('features')
        provenance = doc.get('provenance', {})
        if (doc.get('type') != 'FeatureCollection' or not isinstance(features, list)
                or bool(features) != has_contours or provenance.get('region_id') != root.name
                or provenance.get('publication_held')):
            raise ValueError('contour pair does not match pinned region or disposition')
        by_id = {feature['id']: feature for feature in features}
        if len(by_id) != len(features):
            raise ValueError('duplicate feature IDs in contour pair')
        if relative == CONTOUR_PAIR[0]:
            detail_features = by_id
        elif any(detail_features.get(key) != feature for key, feature in by_id.items()):
            raise ValueError('overview is not a subset of the QA-bound detail')
        size = next(row['bytes'] for row in contour_stage['outputs'] if row['path'] == relative)
        contour_rows.append(dict(path=relative, sha256=digest, bytes=size))
    detail = contour_rows[0]
    bound = [(row['path'], row['sha256']) for row in qa_stage['inputs'] if row['role'] == 'contours']
    if bound != [(detail['path'], detail['sha256'])]:
        raise ValueError('contour detail is not the bound QA input')

    row = dict(region=root.name, generation=gen, envelope_sha256=verified.envelope_sha256,
               release_sha256=verified.release_sha256, qa_sha256=verified.qa_sha256,
               rights_catalogue_sha256=rights, candidate_kind=kind, layers=layers,
               contours=contour_rows if has_contours else [])
    return {**row, 'preview_id': 'central-preview:' + receipts.sha256_bytes(receipts.canonical([SCHEMA, row]))}


def build(out: Path, readback: Path, expected_sha256: str) -> dict:
    raw = readback.read_bytes()
    if receipts.sha256_bytes(raw) != expected_sha256:
        raise ValueError('readback sha256 mismatch')
    pins = package.decode_document(raw).get('regions')
    if not isinstance(pins, dict) or set(pins) != set(REGIONS):
        raise ValueError('readback must contain exactly the six Central regions')
    rights = receipts.sha256_file(envelope.repo_root() / 'catalog/sources.json')
    if out.absolute() != out.resolve(strict=True) or not out.is_dir():
        raise ValueError('expected a canonical local relief output root')
    rows = {}
    for name in sorted(REGIONS):
        try:
            rows[name] = _region(out / name, pins[name], rights)
        except (OSError, ValueError, KeyError, TypeError, AttributeError, RecursionError) as exc:
            raise ValueError(f'{name}: {exc}') from exc
    return dict(schema=SCHEMA, purpose='offline-preview-only', readback_sha256=expected_sha256, regions=rows)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True, help='admitted local relief output root (read-only)')
    parser.add_argument('--readback', type=Path, required=True, help='previously verified six-envelope digest receipt')
    parser.add_argument('--readback-sha256', required=True, help='independently recorded SHA-256 of that receipt')
    args = parser.parse_args(argv)
    try:
        print(receipts.canonical(build(args.out, args.readback, args.readback_sha256)).decode())
    except (OSError, ValueError, RecursionError) as exc:
        print(f'OFFLINE PREVIEW REFUSED: {exc}', file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    sys.exit(main())
