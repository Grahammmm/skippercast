#!/usr/bin/env python3
"""Assemble one sc-run-inputs/1 record from reviewed pins in a local scratch tree.

This checks local bytes, not source rights, stage readiness or clearance. It
never runs a stage, binds a census or reads receipts. The runner rechecks pins
and applies its own host guards if the record is later used.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path

from skippercast.relief import census_bind

if __package__:
    from . import run_region
else:
    import run_region


def require_local(role, path, root):
    # Both the spelling and its filesystem target must stay in the scratch tree.
    if ('\x00' in str(path)
            or not Path(os.path.abspath(path)).is_relative_to(root)
            or not run_region.real(path).is_relative_to(root.resolve())):
        raise ValueError(f'{role}: path must stay inside --scratch-root')


def assemble(args):
    if not run_region.REGION_ID.fullmatch(args.region):
        raise ValueError('invalid region ID')
    if not args.scratch_root.strip() or not args.norm.strip():
        raise ValueError('--scratch-root and --norm must be non-empty paths')
    root = Path(os.path.abspath(run_region.spelled(args.scratch_root)))
    cfg = run_region.Config(basemap_roots=(root,))
    if ('\x00' in str(root) or not root.is_dir()
            or run_region.real(args.scratch_root) != root.resolve()
            or run_region.under(root, cfg.forbidden_root)):
        raise ValueError('--scratch-root must be a local directory outside the forbidden root')

    inputs, pins = {}, {}
    runner_argv = [args.region, '--out', str(root), '--through', args.through, f'--norm={args.norm}']
    for role, path, pin in args.input:
        if role not in run_region.RECORD_FILES:
            raise ValueError(f'unknown input role {role!r}')
        if role in pins:
            raise ValueError(f'duplicate input role {role!r}')
        if not path.strip():
            raise ValueError(f'{role}: expected a non-empty path')
        if not run_region.HEX64.fullmatch(pin.lower()):
            raise ValueError(f'{role}: sha256 must be 64 hexadecimal digits')
        pins[role] = pin.lower()
        runner_argv.append(f'--{role.replace("_", "-")}={path}')
    if args.through == 'envelope' and not {'census', 'basemap'} <= pins.keys():
        raise ValueError('envelope requires pinned census and basemap')
    if args.fresh_out and 'select' in run_region.chain_through(args.through) and 'census' not in pins:
        raise ValueError('fresh OUT requires pinned census for select')
    if ('coarse' in pins) != ('water' in pins):
        raise ValueError('supply pinned coarse and water together, or omit both')
    if 'census' in pins:
        runner_argv.extend(['--census-sha256', pins['census']])
    for field in ('coarse_source', 'coarse_date'):
        if (value := getattr(args, field)) is not None:
            if not value.strip():
                raise ValueError(f'{field} must not be blank')
            runner_argv.append(f'--{field.replace("_", "-")}={value}')

    # parse calls resolve_options for flags, using the same spellings as --inputs.
    _, options = run_region.parse(runner_argv)
    if missing := run_region.missing_inputs(options, args.through):
        raise ValueError('runner requires ' + ', '.join(flag for _, flags in missing for flag in flags))
    require_local('norm', options.norm, root)
    if run_region.under(options.norm, cfg.forbidden_root):
        raise ValueError('norm: path is under the forbidden root')
    for role, pin in pins.items():
        path = getattr(options, role)
        require_local(role, path, root)
        if problem := run_region.input_problem(cfg, role, path, pin):
            raise ValueError(f'{role}: {problem}')
        inputs[role] = {'path': path, 'sha256': pin}
    if 'coarse' in pins and os.path.samefile(options.coarse, options.water):
        raise ValueError('coarse and water must refer to distinct files')
    if 'census' in pins:
        data = Path(options.census).read_bytes()
        # Check the exact bytes we interpret, not only the earlier file read.
        if hashlib.sha256(data).hexdigest() != pins['census']:
            raise ValueError('census: sha256 mismatch while reading summary')
        census_bind._validate_census(data, args.region)
    return {'schema': 'sc-run-inputs/1', 'region': args.region, 'inputs': inputs,
            'norm': str(options.norm), 'coarse_source': options.coarse_source,
            'coarse_date': options.coarse_date}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--scratch-root', required=True, help='local root containing every input and cache path')
    parser.add_argument('--region', required=True)
    parser.add_argument('--norm', required=True, help='explicit normalized-cache path')
    parser.add_argument('--through', choices=run_region.STAGES, default='envelope',
                        help='check required inputs through this stage (default: envelope); run nothing')
    parser.add_argument('--fresh-out', action='store_true',
                        help='require a pinned census for select without relying on one already in OUT')
    parser.add_argument('--input', action='append', nargs=3, required=True, metavar=('ROLE', 'PATH', 'SHA256'),
                        help='repeat for each reviewed file; roles: ' + ', '.join(sorted(run_region.RECORD_FILES)))
    parser.add_argument('--coarse-source')
    parser.add_argument('--coarse-date')
    args = parser.parse_args(argv)
    try:
        record = assemble(args)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    print(json.dumps(record, indent=2, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
