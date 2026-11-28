#!/usr/bin/env python3
"""Report the first incomplete stage in each region's public relief rollout.

With ``--stages`` it reports every stage of every region instead (a region x stage table of
receipt states: done, stale, failed, held, missing, invalid, unproved, or skipped for a survey stage
the region's inventory receipt does not take), the pipeline's status
page. Only receipt and artifact reads are performed. This is a point-in-time
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

from scripts.relief.run_region import SCOPED_STAGES, STAGES, SURVEY_STAGES
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


class StageState(TypedDict):
    stage: str
    state: str
    reason: str
    generation: str | None


def taken_by_inventory(region: receipts.Region):
    """The upstream keys the region's inventory receipt records, or None before a readable one exists.

    The inventory receipt states which survey stages this region's release takes (run_region.py
    --survey); its outputs are not re-hashed here, so the first-incomplete view stays lazy.
    """
    try:
        path = region.receipt_path('inventory', None)
        if not stat.S_ISREG(path.lstat().st_mode):
            return None
        doc = receipts.read_receipt(path)
    except (OSError, ValueError, RecursionError):
        return None
    if doc is None or receipts.validate_receipt(doc, region.id, 'inventory', None):
        return None
    return {receipts.Ref(row['stage'], row.get('scope')).key for row in doc['upstream']}


def stage_states(region: receipts.Region):
    """Every public stage of the region in rollout order, each with its receipt verdict (lazy).

    A survey stage that the region's inventory receipt does not take is 'skipped' (the run chose
    --survey detail or none); before inventory has a readable receipt every survey stage is judged
    by its own receipt, so a required one that never ran still reads 'missing'.
    """
    reader = ReceiptReader(region)
    taken = taken_by_inventory(region)
    for stage in STAGES:
        ref = receipts.Ref(stage, 'public' if stage in SCOPED_STAGES else None)
        if stage in SURVEY_STAGES and taken is not None and ref.key not in taken:
            yield StageState(stage=ref.key, state='skipped', reason='not taken by the inventory receipt (--survey)',
                             generation=None)
            continue
        verdict = reader.check(ref)
        yield StageState(stage=ref.key, state=verdict.state, reason=verdict.reason,
                         generation=(verdict.receipt or {}).get('generation'))


def region_status(region: receipts.Region) -> Status:
    generation = None
    for row in stage_states(region):
        if row['state'] == 'skipped':
            continue
        generation = row['generation']
        if row['state'] != 'done':
            return Status(region=region.id, **row)
    return Status(region=region.id, stage=None, state='complete', reason=COMPLETE, generation=generation)


def stage_table(matrix):
    """Region x stage table of states, one line per region (the --stages text view)."""
    names = [row['stage'] for row in matrix[0]['stages']] if matrix else []
    width = max([len('region'), *(len(entry['region']) for entry in matrix)])
    cells = [max([len(name), *(len(entry['stages'][i]['state']) for entry in matrix)]) for i, name in enumerate(names)]
    lines = ['  '.join([f'{"region":<{width}}', *(f'{name:<{w}}' for name, w in zip(names, cells))]).rstrip()]
    for entry in matrix:
        states = (f'{row["state"]:<{w}}' for row, w in zip(entry['stages'], cells))
        lines.append('  '.join([f'{entry["region"]:<{width}}', *states]).rstrip())
    return '\n'.join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', required=True, help='relief pipeline output root')
    parser.add_argument('--regions', required=True, help='comma-separated region IDs in rollout order')
    parser.add_argument('--json', action='store_true', help='emit a JSON array instead of one line per region')
    parser.add_argument('--stages', action='store_true',
                        help='every stage of every region (done/stale/failed/held/missing/...), not only the first '
                             'incomplete one: a region x stage table, or with --json one object per region')
    args = parser.parse_args(argv)
    try:
        regions = [receipts.Region(args.out, token.strip()) for token in args.regions.split(',')]
    except (ValueError, OSError, RuntimeError) as exc:
        parser.error(str(exc))

    if args.stages:
        matrix = [{'region': region.id, 'stages': list(stage_states(region))} for region in regions]
        print(json.dumps(matrix, indent=2) if args.json else stage_table(matrix))
        return 0
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
