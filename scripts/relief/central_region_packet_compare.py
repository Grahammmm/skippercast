#!/usr/bin/env python3
"""Compare the six Central Coast local evidence packets, without building or publishing.

Read only the named regions in a public relief output root. A verified local
terrain packet with no contour QA is reported separately, never as release-ready.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from stat import S_ISDIR
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src'))

from skippercast.relief import envelope, package, receipts  # noqa: E402

REGIONS = (
    'cambria-san-simeon', 'big-sur-coast', 'south-big-sur-san-simeon',
    'monterey-point-sur', 'point-arguello-conception', 'santa-cruz-monterey-bay',
)


class Incomplete(ValueError):
    """A producer's local evidence has not reached the required stage."""


def _read_stage(root, stage, scope=None):
    name = f'{stage}.{scope}' if scope else stage
    for directory in (root, root / 'stages'):
        if not S_ISDIR(directory.lstat().st_mode):
            raise ValueError(f'not a real stage directory: {directory.name}')
    relative = f'stages/{name}.json'
    (root / relative).lstat()  # missing stage is unfinished, unlike an invalid or symlinked file
    doc = package.decode_document(package.artifact_path(root, relative).read_bytes())
    if ((doc.get('schema'), doc.get('region'), doc.get('stage'), doc.get('scope'))
            != ('sc-stage-receipt/1', root.name, stage, scope)
            or not package.is_sha256(doc.get('generation'))):
        raise ValueError(f'{name}: wrong stage or region identity')
    if doc.get('status') != 'ok':
        raise Incomplete(f'{name}: {doc.get("status", "no status")}')
    return doc


def _link(child, parent):
    ref = {'stage': parent['stage'], 'generation': parent['generation']}
    if parent.get('scope'):
        ref['scope'] = parent['scope']
    if [x for x in child['upstream'] if x['stage'] == parent['stage']] != [ref]:
        raise ValueError(f'{child["stage"]}: current {parent["stage"]} does not match its pinned input')


def _output(root, stage, relative):
    matches = [row for row in stage['outputs'] if row['path'] == relative]
    path = package.artifact_path(root, relative)
    if len(matches) != 1:
        raise ValueError(f'{stage["stage"]}: expected one output {relative}')
    raw = path.read_bytes()
    if len(raw) != matches[0]['bytes'] or receipts.sha256_bytes(raw) != matches[0]['sha256']:
        raise ValueError(f'{stage["stage"]}: output bytes changed: {relative}')
    return package.decode_document(raw), matches[0]['sha256']


def _phone(root, verified, qa):
    lo, hi = (verified.release[field] for field in ('minzoom', 'maxzoom'))
    cameras = sorted({z for z in (lo, 10, 13, 15, hi) if lo <= z <= hi})
    if qa['shots']['cameras'] != cameras:
        raise ValueError('QA cameras do not match the release zoom range')
    expected = {(theme, zoom) for theme in ('light', 'dark') for zoom in cameras}
    views = set()
    for shot in qa['shots']['entries']:
        if shot['device'] != 'phone':
            continue
        theme, zoom = key = (shot['theme'], shot['zoom'])
        relative = f'shots/{theme}-phone-z{zoom}.png'
        if key not in expected or key in views or shot['viewport'] != [390, 844] or shot['path'] != relative:
            raise ValueError('QA phone shot does not match the bound light/dark matrix')
        path = package.artifact_path(root, f'qa/{verified.generation}/{relative}')
        if receipts.sha256_file(path) != shot['sha256']:
            raise ValueError('QA phone shot bytes changed')
        views.add(key)
    if views != expected:
        raise Incomplete('QA phone matrix is incomplete')
    return len(views)


def _packet(root, rights_digest):
    review = _read_stage(root, 'envelope')
    packed = _read_stage(root, 'package')
    qa_stage = _read_stage(root, 'qa')
    mosaic_stage = _read_stage(root, 'mosaic', 'public')
    selected = _read_stage(root, 'select')
    contours = _read_stage(root, 'contours')  # package and QA pin it; a rebuild after QA makes both stale
    for child, parent in ((review, packed), (review, qa_stage), (qa_stage, packed),
                          (qa_stage, mosaic_stage), (qa_stage, contours), (packed, contours),
                          (mosaic_stage, selected)):
        _link(child, parent)
    if [row['sha256'] for row in packed['inputs'] if row['role'] == 'rights'] != [rights_digest]:
        raise ValueError('package rights catalogue digest does not match the current reviewed catalogue')
    gen = packed['generation']
    relative = f'review/{gen}/envelope.json'
    _, digest = _output(root, review, relative)
    verified = envelope.verify_artifacts(package.artifact_path(root, relative))
    if verified.envelope_sha256 != digest or verified.release['region'] != root.name:
        raise ValueError('verified envelope does not match this region or receipt')
    qa, qa_digest = _output(root, qa_stage, f'qa/{gen}/qa.json')
    if qa.get('region') != root.name or qa_digest != verified.qa_sha256:
        raise ValueError('QA does not match this region and envelope')
    selection, _ = _output(root, selected, 'select/selection.json')
    if (selection.get('region'), selection.get('scope')) != (root.name, 'public'):
        raise ValueError('selection is not public evidence for this region')
    included = sum(row['decision'] == 'included' for row in selection['files'])
    mosaic, _ = _output(root, mosaic_stage, 'mosaic/public/manifest.json')
    valid_cells = mosaic['stats']['valid_cells']
    contributors = mosaic['band_0_300ft']['contributor_cells']
    if not included or type(valid_cells) is not int or valid_cells <= 0 or not any(n > 0 for n in contributors.values()):
        raise ValueError('empty public selection or 0–300 ft coverage')
    phone_views = _phone(root, verified, qa)
    counts = qa['metrics']['contour_count_by_interval_ft']
    contour_qa = 'nonempty' if any(type(n) is int and n > 0 for n in counts.values()) else 'none-in-qa'
    return {'status': 'local-ready' if contour_qa == 'nonempty' else 'local-terrain-only',
            'envelope_sha256': digest, 'release_sha256': verified.release_sha256,
            'rights_sha256': rights_digest, 'included_files': included, 'valid_cells': valid_cells,
            'phone_views': phone_views, 'contour_qa': contour_qa}


def compare(out: Path):
    rights = receipts.sha256_file(ROOT / 'catalog/sources.json')
    rows = {}
    for region in REGIONS:
        try:
            rows[region] = _packet(out / region, rights)
        except (FileNotFoundError, Incomplete) as error:
            rows[region] = {'status': 'incomplete', 'reason': str(error)}
        except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
            rows[region] = {'status': 'invalid', 'reason': str(error)}
    ready = all(row['status'] == 'local-ready' for row in rows.values())
    return {'schema': 'sc-central-local-packet-compare/1', 'scope': 'local-evidence-only',
            'status': 'local-ready' if ready else 'incomplete', 'regions': rows}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True, help='public regional build output root')
    receipt = compare(parser.parse_args(argv).out)
    print(json.dumps(receipt, indent=2, sort_keys=True))
    return 0 if receipt['status'] == 'local-ready' else 1


if __name__ == '__main__':
    raise SystemExit(main())
