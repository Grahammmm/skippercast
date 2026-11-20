#!/usr/bin/env python3
"""Report the first incomplete stage in each region's public relief rollout.

Only receipt and artifact reads are performed. This is a point-in-time
observation, not a release check. An interrupted attempt may still be active:
this diagnostic does not probe or acquire stage locks.
"""
import argparse
import json
from pathlib import Path
import stat
import sys
from typing import TypedDict

if __package__ in (None, ''):
    root = Path(__file__).resolve().parents[2]
    sys.path[:0] = [str(root), str(root / 'src')]

from scripts.relief.run_region import SCOPED_STAGES, STAGES
from skippercast.relief import receipts

COMPLETE = 'complete through envelope (ready for review, not live)'


class Status(TypedDict):
    region: str
    stage: str | None
    state: str
    reason: str
    generation: str | None


class ReceiptReader:
    """Apply the receipt done rule without receipts.check's exclusive lock probe."""

    def __init__(self, region):
        self.region = region
        self.memo = {}

    def check(self, ref):
        if ref not in self.memo:
            self.memo[ref] = receipts.Verdict('invalid', 'upstream cycle')
            self.memo[ref] = self.read(ref)
        return self.memo[ref]

    def read(self, ref):
        try:
            path = self.region.receipt_path(ref.stage, ref.scope)
            if not stat.S_ISREG(path.lstat().st_mode):
                return receipts.Verdict('invalid', 'receipt is not a regular file')
            doc = receipts.read_receipt(path)
        except FileNotFoundError:
            doc = None
        except (OSError, ValueError, RecursionError) as exc:
            return receipts.Verdict('invalid', f'cannot read receipt: {exc}')
        if doc is None:
            return receipts.Verdict('missing', 'no receipt')
        if problem := receipts.validate_receipt(doc, self.region.id, ref.stage, ref.scope):
            return receipts.Verdict('invalid', problem)
        if doc['status'] == 'held':
            return receipts.Verdict('held', str(doc.get('held_reason') or 'held'), doc)
        if doc['status'] == 'failed':
            reason = f'attempt {doc["attempt"]}: {doc.get("error") or doc.get("rc")}'
            if doc.get('error') == receipts.INTERRUPTED:
                reason += ' (activity not checked)'
            return receipts.Verdict('failed', reason, doc)
        try:
            return self.verify_outputs_and_upstream(doc)
        except RecursionError:
            return receipts.Verdict('invalid', 'upstream graph too deeply nested', doc)

    def verify_outputs_and_upstream(self, doc):
        for output in doc['outputs']:
            name = output['path']
            try:
                if '\x00' in name:
                    raise receipts.ReceiptError('output path contains a NUL')
                path = self.region.resolve(name)
                info = path.lstat()
                if not stat.S_ISREG(info.st_mode):
                    return receipts.Verdict('unproved', f'output is not a regular file: {name}', doc)
                if info.st_size != output['bytes'] or receipts.sha256_file(path) != output['sha256']:
                    return receipts.Verdict('unproved', f'output changed: {name}', doc)
            except receipts.ReceiptError as exc:
                return receipts.Verdict('invalid', str(exc), doc)
            except FileNotFoundError:
                return receipts.Verdict('unproved', f'output missing: {name}', doc)
            except (OSError, ValueError) as exc:
                return receipts.Verdict('unproved', f'cannot read output {name!r}: {exc}', doc)
        for upstream in doc['upstream']:
            ref = receipts.Ref(upstream['stage'], upstream.get('scope'))
            verdict = self.check(ref)
            if not verdict.done:
                return receipts.Verdict('stale', f'upstream {ref.key} not done ({verdict.state}): '
                                        f'{verdict.reason}', doc)
            if verdict.receipt['generation'] != upstream['generation']:
                return receipts.Verdict('stale', f'upstream {ref.key} generation changed', doc)
        return receipts.Verdict('done', 'outputs re-hash; upstream current', doc)


def region_status(region: receipts.Region) -> Status:
    reader = ReceiptReader(region)
    generation = None
    for stage in STAGES:
        ref = receipts.Ref(stage, 'public' if stage in SCOPED_STAGES else None)
        verdict = reader.check(ref)
        generation = (verdict.receipt or {}).get('generation')
        if not verdict.done:
            return Status(region=region.id, stage=ref.key, state=verdict.state,
                          reason=verdict.reason, generation=generation)
    return Status(region=region.id, stage=None, state='complete', reason=COMPLETE, generation=generation)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', required=True, help='relief pipeline output root')
    parser.add_argument('--regions', required=True, help='comma-separated region IDs in rollout order')
    parser.add_argument('--json', action='store_true', help='emit a JSON array instead of one line per region')
    args = parser.parse_args(argv)
    try:
        regions = [receipts.Region(args.out, token.strip()) for token in args.regions.split(',')]
    except (ValueError, OSError, RuntimeError) as exc:
        parser.error(str(exc))

    rows = [region_status(region) for region in regions]
    if args.json:
        print(json.dumps(rows, indent=2))
    else:
        for row in rows:
            reason = ' '.join(row['reason'].splitlines())
            if row['state'] == 'complete':
                print(f'{row["region"]}: {reason}; generation {row["generation"]}')
            else:
                print(f'{row["region"]}: {row["stage"]} {row["state"]}; '
                      f'generation {row["generation"] or "-"}; {reason}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
