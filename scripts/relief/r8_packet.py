#!/usr/bin/env python3
"""Print evidence for R8 review without approving or publishing a release."""
import argparse
from html import escape
import json
from pathlib import Path
import sys

if __name__ == '__main__':
    sys.dont_write_bytecode = True
    # Use the same checkout as the CLI, not another editable install.
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'src'))

from skippercast.relief import envelope, package, receipts

_QA_METRICS = (
    'z16plus_uncertified_pixels',
    'measured_label_uncertified_cells',
    'land_leak_pct',
    'contour_count_by_interval_ft',
)


def _current_envelope(out: Path, region_id: str) -> Path:
    region = receipts.Region(out, region_id)
    # The package receipt selects the current release generation. Do not scan
    # historical envelopes or run receipt checks that can take stage locks.
    receipt = package.artifact_path(region.dir, 'stages/package.json')
    doc = package.decode_document(receipt.read_bytes())
    problem = receipts.validate_receipt(doc, region_id, 'package', None)
    if problem:
        raise package.ReleaseError(f'invalid package receipt: {problem}')
    if doc['status'] != 'ok':
        raise package.ReleaseError(f'package receipt status is {doc["status"]}')
    return region.dir / 'review' / doc['generation'] / 'envelope.json'


def _qa_rows(root: Path, verified: envelope.VerifiedArtifacts) -> list[tuple[str, str]]:
    relative = f'qa/{verified.generation}'
    raw = package.artifact_path(root, f'{relative}/qa.json').read_bytes()
    # Display only the exact QA bytes already bound by the envelope verifier.
    if receipts.sha256_bytes(raw) != verified.qa_sha256:
        raise package.ReleaseError('qa.json does not match envelope')
    qa = package.decode_document(raw)
    metrics = qa.get('metrics', {})
    if not isinstance(metrics, dict):
        raise package.ReleaseError('invalid QA metrics')
    rows = [('status', qa['status'])]
    rows.extend((key, json.dumps(metrics[key], sort_keys=True) if key in metrics else 'absent')
                for key in _QA_METRICS)

    shots = qa.get('shots', {'entries': []})
    if not isinstance(shots, dict) or not isinstance(shots.get('entries'), list):
        raise package.ReleaseError('invalid QA shot inventory')
    for shot in shots['entries']:
        if (not isinstance(shot, dict) or not all(isinstance(shot.get(key), str)
                for key in ('path', 'theme', 'device', 'sha256')) or type(shot.get('zoom')) is not int):
            raise package.ReleaseError('invalid QA shot entry')
        file = shot['path']
        try:
            if not file.startswith('shots/') or not file.endswith('.png'):
                raise ValueError('expected a QA PNG')
            sha = receipts.sha256_file(package.artifact_path(root, f'{relative}/{file}'))
        except (OSError, ValueError):
            raise package.ReleaseError(f'shot {file} differs') from None
        if sha != shot['sha256']:
            raise package.ReleaseError(f'shot {file} differs')
        rows.append(('shot', f'theme={shot["theme"]} device={shot["device"]} zoom={shot["zoom"]} '
                             f'path={file} sha256={sha}'))
    return rows


def _markdown_cell(text: str) -> str:
    return escape(' '.join(text.splitlines()), quote=False).replace('\\', '\\\\').replace('|', r'\|')


def _print_region(heading: str, rows: list[tuple[str, str]], markdown: bool) -> None:
    if markdown:
        print('| Field | Value |\n| --- | --- |')
        for key, value in [(heading, ''), *rows]:
            print(f'| {_markdown_cell(key)} | {_markdown_cell(value)} |')
        print()
    else:
        print(heading)
        for key, value in rows:
            print(value if key == 'verdict' else f'  {key}: {value}')


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog='r8_packet.py', description=__doc__)
    parser.add_argument('--out', required=True, type=Path, metavar='OUT')
    parser.add_argument('--markdown', action='store_true', help='print one review table per region')
    parser.add_argument('regions', nargs='+', metavar='REGION')
    args = parser.parse_args(argv)
    if len(args.regions) > 3:
        parser.error('expected at most 3 regions')
    for region in args.regions:
        try:
            receipts.check_names('envelope', region=region)
        except receipts.ReceiptError as exc:
            parser.error(str(exc))

    status = 0
    for region in args.regions:
        try:
            review = _current_envelope(args.out, region)
            verified = envelope.verify_artifacts(review)
            qa_rows = _qa_rows(review.parents[2], verified)
        except (OSError, ValueError) as exc:
            reason = ' '.join(str(exc).splitlines())
            _print_region(f'NOT READY {region}: {reason}', [], args.markdown)
            status = 1
            continue
        _print_region(f'READY {region}', [
            ('generation', verified.generation),
            ('envelope.json sha256', verified.envelope_sha256),
            ('release.json sha256', verified.release_sha256),
            ('qa.json sha256', verified.qa_sha256),
            ('layers', str(len(verified.layers))),
            *qa_rows,
            ('verdict', f'APPROVED release {region} envelope={verified.envelope_sha256}'),
        ], args.markdown)
    return status


if __name__ == '__main__':
    sys.exit(main())
