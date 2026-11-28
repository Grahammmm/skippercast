#!/usr/bin/env python3
"""Preview relief rebuilds from receipts; do not run stages or verify their outputs."""
import argparse
from importlib import import_module
from importlib.util import find_spec
import json
import os
from pathlib import Path
import stat

from skippercast.relief import rebuild_plan, receipts

if __package__:
    from .run_region import STAGES, SURVEY_STAGES
else:
    from run_region import STAGES, SURVEY_STAGES

HEAVY = {'mosaic', 'tiles'}


def _stage_digests():
    """Hash the installed code once, using the exact receipt producer labels."""
    from skippercast.relief import package, qa

    package_file = ('package.py', package.__file__)
    # These five stages own their receipts in main(), not region.py's build adapter.
    # Select only hashes its own file, so locate it without loading the GIS stack.
    select_spec = find_spec('skippercast.relief.select')
    if select_spec is None or select_spec.origin is None:
        raise receipts.ReceiptError('select has no installed source file')
    current = {'select': receipts.stage_digest([('select.py', select_spec.origin)])}
    for stage in STAGES:
        if stage == 'select':
            continue
        module = import_module(f'skippercast.relief.{stage}')
        if stage == 'package':
            files = package.code_files()
        elif stage in ('digests', 'envelope'):
            files = [(f'{stage}.py', module.__file__), package_file]
        elif stage == 'qa':
            files = [('qa.py', qa.__file__),
                     ('pmtiles_reader', qa.read_tiles.__code__.co_filename),
                     ('contour_contract', Path(qa.__file__).parent.parent / 'platform/depth_contours.py')]
        else:
            files = receipts.module_code_files(module)
        digest = receipts.stage_digest(files)
        for scope in getattr(module, 'SCOPES', (None,)):
            current[receipts.Ref(stage, scope).key] = digest
    return current


def _input_hasher(location, memo):
    """Read-only sha256 of a recorded input, ``None`` when it is no file; memoised by real path.

    Only a genuinely absent path (or a non-file) is ``None``. Path.is_file() would also turn a
    PermissionError into False, so stat directly and let access errors reach the CLI.
    """
    def hasher(recorded):
        path = location.resolve(recorded)
        if path not in memo:
            try:
                is_file = stat.S_ISREG(os.stat(path).st_mode)
            except (FileNotFoundError, NotADirectoryError):
                is_file = False
            memo[path] = receipts.sha256_file(path) if is_file else None
        return memo[path]
    return hasher


def _region_plan(out, region, current, memo=None, *, default=None, pin=None, survey=(), inputs_at=None):
    """``survey`` names the opt-in survey stages this run selects (run_region's ``--survey``).

    A survey stage is planned only when it is selected, has a receipt, or a receipt takes it
    upstream (plan() adds such links itself, as ``missing`` without a receipt); otherwise a
    region that never runs them would always show two missing rebuilds.

    ``inputs_at`` (``{receipt key: {role: path}}``) is where the run will read those inputs; they
    are compared there instead of at the recorded path, as the stage itself keys them by content
    (a run from a moved checkout reuses, and re-records the path).
    """
    # run_region's dry run calls this without a memo; each call then hashes for itself.
    memo = {} if memo is None else memo
    # Region.keys() globs, which can hide permission errors as an empty directory.
    # A missing stages directory is normal for a region that has not been run.
    location = receipts.Region(out, region)
    try:
        with os.scandir(location.stages_dir):
            pass
    except FileNotFoundError:
        pass
    docs = rebuild_plan.load_receipts(out, region)
    for key, paths in (inputs_at or {}).items():
        doc = docs.get(key)
        if doc is not None and isinstance(doc.get('inputs'), list):
            docs[key] = dict(doc, inputs=[
                dict(item, path=location.record(paths[item['role']]))
                if isinstance(item, dict) and item.get('role') in paths else item for item in doc['inputs']])
    styles = rebuild_plan.style_digests(region, default=default, pin=pin)
    # Compare existing scoped receipts too, even if the current runner doesn't emit that scope.
    by_stage = {key.partition('.')[0]: digest for key, digest in current.items()}
    digests = {key: digest for key, digest in current.items()
               if key.partition('.')[0] not in SURVEY_STAGES or key.partition('.')[0] in survey}
    for key in docs:
        stage = key.partition('.')[0]
        if stage in by_stage:
            digests[key] = by_stage[stage]
    return rebuild_plan.plan(docs, {'stage_digest': digests, 'style': styles},
                             _input_hasher(location, memo))


def main(argv=None):
    parser = argparse.ArgumentParser(prog='rebuild_plan.py', description=__doc__)
    parser.add_argument('--out', required=True, type=Path, help='existing relief output root')
    parser.add_argument('--json', action='store_true', help='print one JSON document')
    parser.add_argument('--style-default', metavar='VERSION', help='simulate a different default style')
    parser.add_argument('--style-pin', metavar='REGION=VERSION', action='append', default=[],
                        help='simulate a pin for a requested region (repeatable)')
    parser.add_argument('regions', metavar='REGION', nargs='+')
    args = parser.parse_intermixed_args(argv)

    pins = {}
    for assignment in args.style_pin:
        region, _, version = assignment.partition('=')
        if not region or not version or '=' in version:
            parser.error('--style-pin requires REGION=VERSION')
        if region not in args.regions:
            parser.error(f'--style-pin region not in report: {region}')
        if region in pins:
            parser.error(f'duplicate --style-pin for region: {region}')
        pins[region] = version

    try:
        out = args.out.expanduser()
        with os.scandir(out):
            pass
        current = _stage_digests()
        memo = {}
        blocks = [
            {'region': region, 'stages': _region_plan(out, region, current, memo,
                                                     default=args.style_default, pin=pins.get(region))}
            for region in args.regions
        ]
    except (OSError, ValueError) as exc:
        parser.error(str(exc))

    heavy = sum(row['action'] == 'rebuild' and row['stage'].partition('.')[0] in HEAVY
                for block in blocks for row in block['stages'])
    summary = {'regions': len(blocks), 'rebuild_heavy': heavy}
    if args.json:
        print(json.dumps({'regions': blocks, 'summary': summary}))
    else:
        for block in blocks:
            print(f"region {block['region']}")
            for row in block['stages']:
                reasons = ', '.join(row['reasons']) or '-'
                print(f"  {row['stage']}  {row['action']}  {reasons}")
        print(f'regions={len(blocks)} rebuild_heavy={heavy}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
