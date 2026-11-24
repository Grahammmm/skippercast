#!/usr/bin/env python3
"""Report locally reusable prior generations for one stage, without restoring anything."""
import argparse
import json
from os.path import realpath
from pathlib import Path

from skippercast.relief import receipts


def inventory(region: receipts.Region, ref: receipts.Ref) -> dict:
    """Inspect a stable local output tree; this is not a rebuild or release decision."""
    path = region.receipt_path(ref.stage, ref.scope)
    current = receipts.read_receipt(path)
    if current is None:
        raise receipts.ReceiptError(f'{path.name}: no receipt')
    problem = receipts.validate_receipt(current, region.id, ref.stage, ref.scope)
    if problem:
        raise receipts.ReceiptError(f'{path.name}: {problem}')

    # run_stage stores history inside the current receipt and refuses malformed
    # history as a whole. The same generation can appear in both places.
    history = current.get('generation_history', {})
    if not isinstance(history, dict) or any(
        not isinstance(doc, dict)
        or receipts.validate_receipt(doc, region.id, ref.stage, ref.scope)
        or doc['generation'] != key
        for key, doc in history.items()
    ):
        raise receipts.ReceiptError(f'{path.name}: generation history malformed')

    # Cache current generation checks. None marks missing proof or a check in
    # progress, so upstream cycles (including a link back to this stage) fail closed.
    verified: dict[receipts.Ref, str | None] = {ref: None}

    def current_generation(dep: receipts.Ref) -> str | None:
        if dep not in verified:
            verified[dep] = None
            try:
                doc = receipts.read_receipt(region.receipt_path(dep.stage, dep.scope))
                if (doc is not None
                        and not receipts.validate_receipt(doc, region.id, dep.stage, dep.scope)
                        and done(doc)):
                    verified[dep] = doc['generation']
            except (OSError, ValueError):
                pass  # Missing or unreadable evidence cannot qualify a candidate.
        return verified[dep]

    def done(doc: dict, *, historical: bool = False) -> bool:
        # Same byte and upstream checks as the receipt done rule. Do not use
        # receipts.check here: classifying interrupted attempts can take a lock.
        if doc['status'] != 'ok':
            return False
        try:
            target = None
            if historical:
                # run_stage saves the expanded target in each generation's own receipt.
                recorded = doc.get('target')
                if not isinstance(recorded, str) or not recorded:
                    return False
                target = region.resolve(recorded)
            for output in doc['outputs']:
                file = region.resolve(output['path'])
                if target is not None and (
                        target not in file.parents or realpath(file, strict=True) != str(file)):
                    return False
                if (file.is_symlink() or not file.is_file()
                        or file.stat().st_size != output['bytes']
                        or receipts.sha256_file(file) != output['sha256']):
                    return False
        except (OSError, ValueError):
            return False
        return all(current_generation(receipts.Ref(up['stage'], up.get('scope'))) == up['generation']
                   for up in doc['upstream'])

    return {
        'region': region.id,
        'stage': ref.key,
        'current': {'generation': current['generation'], 'receipt_status': current['status']},
        # A receipt with no outputs may be done, but proves no saved bytes to reuse.
        'reusable_history': [
            {'generation': key, 'output_count': len(doc['outputs'])}
            for key, doc in sorted(history.items())
            if key != current['generation'] and doc['outputs'] and done(doc, historical=True)
        ],
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', required=True, type=Path, help='existing relief output root')
    parser.add_argument('region')
    parser.add_argument('stage', help='stage or stage:scope (for example, mosaic:public)')
    args = parser.parse_args(argv)
    try:
        report = inventory(receipts.Region(args.out, args.region), receipts.Ref.parse(args.stage))
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    print(json.dumps(report, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
