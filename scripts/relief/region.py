#!/usr/bin/env python3
"""Relief pipeline region CLI (E2E-PIPELINE §2-§3).

    region.py status --region <id> --out <OUT> [--json]
    region.py <stage> --region <id> --out <OUT> [--scope <scope>] [stage options]

``<stage>`` runs module ``skippercast.relief.<stage>`` (a hyphen in the name becomes an
underscore), found by name: adding a stage adds a module and never edits this file. A
name with no such module, or a module that is not a stage, is refused (exit 2).

A module with ``build(ctx, out_dir)`` runs under the receipt rules of
``skippercast.relief.receipts``: it is a no-op when done, it builds into a temporary
directory renamed into place, and its receipt goes to ``OUT/<id>/stages/<stage>.json``.
A module with only ``main(argv)`` gets the remaining arguments and manages its own receipts.

``status`` prints every receipt of the region in upstream-first order with the done rule's
verdict: done, stale (an upstream generation changed or is not done), unproved (an output
no longer re-hashes), failed, running, held, invalid.

``--out`` defaults to ``$SC_RELIEF_OUT``. Exit codes: 0 done or ok, 1 failed, 2 usage or
unknown stage, 3 blocked by an upstream stage or a missing input, 4 held, 5 already running.
Nothing here downloads, uploads or publishes.
"""
import argparse
import importlib
import importlib.util
import json
import os
from pathlib import Path
import sys

# Prefer this checkout before the first import can cache another editable install.
source_root = Path(__file__).resolve().parents[2] / 'src'
if (source_root / 'skippercast' / 'relief' / 'receipts.py').is_file():
    sys.path.insert(0, str(source_root))

from skippercast.relief import receipts

PACKAGE = 'skippercast.relief'
# Modules of the package that are never stages, and the CLI's own command names.
NOT_STAGES = frozenset({'receipts', 'status'})


class UnknownStage(LookupError):
    pass


def resolve_stage(name):
    """The stage module for ``name`` (by name only), or :class:`UnknownStage`."""
    module_name = name.replace('-', '_')
    if not receipts.STAGE_NAME.fullmatch(module_name) or module_name in NOT_STAGES:
        raise UnknownStage(f'unknown stage {name!r}')
    full = f'{PACKAGE}.{module_name}'
    if full not in sys.modules:
        try:
            spec = importlib.util.find_spec(full)
        except (ImportError, ValueError):
            spec = None
        if spec is None:
            raise UnknownStage(f'unknown stage {name!r}: no module {full}')
    module = importlib.import_module(full)
    if not callable(getattr(module, 'build', None)) and not callable(getattr(module, 'main', None)):
        raise UnknownStage(f'unknown stage {name!r}: {full} defines neither build() nor main()')
    return module


def default_out():
    return os.environ.get('SC_RELIEF_OUT') or None


def add_common(parser, scope=True):
    parser.add_argument('--region', required=True, help='region id (a line of regions.tsv)')
    parser.add_argument('--out', default=default_out(), required=default_out() is None,
                        help='pipeline output root OUT (default $SC_RELIEF_OUT)')
    if scope:
        parser.add_argument('--scope', help='scope of a scoped stage (for example public or private)')


def status(argv):
    parser = argparse.ArgumentParser(prog='region.py status', description='Print the stage chain of a region.')
    add_common(parser, scope=False)
    parser.add_argument('--json', action='store_true', help='machine-readable output')
    args = parser.parse_args(argv)
    try:
        region = receipts.Region(args.out, args.region)
    except receipts.ReceiptError as exc:
        parser.error(str(exc))
    rows = receipts.chain(region)
    if args.json:
        print(json.dumps({'region': region.id, 'dir': str(region.dir), 'stages': [
            {'key': key, 'state': v.state, 'reason': v.reason,
             'generation': (v.receipt or {}).get('generation'), 'attempt': (v.receipt or {}).get('attempt'),
             'upstream': (v.receipt or {}).get('upstream') or []} for key, v in rows]}, indent=1))
        return 0
    print(f'region {region.id}  ({region.dir})')
    if not rows:
        print('  no stage receipts')
        return 0
    width = max(len(key) for key, _ in rows)
    for key, verdict in rows:
        doc = verdict.receipt or {}
        gen = str(doc.get('generation') or '-')[:12]
        ups = ', '.join(f'{u.get("stage")}{"." + u["scope"] if u.get("scope") else ""}@{str(u.get("generation"))[:12]}'
                        for u in doc.get('upstream') or [] if isinstance(u, dict)) or '-'
        print(f'  {key:<{width}}  {verdict.state:<8}  gen {gen:<12}  attempt {doc.get("attempt", "-")}  '
              f'<- {ups}  | {verdict.reason}')
    counts = {}
    for _, verdict in rows:
        counts[verdict.state] = counts.get(verdict.state, 0) + 1
    print('chain: ' + ', '.join(f'{n} {state}' for state, n in sorted(counts.items())))
    return 0


def run_module(name, module, argv):
    if not callable(getattr(module, 'build', None)):
        return int(module.main(argv) or 0)
    stage = module.__name__.rsplit('.', 1)[-1]
    parser = argparse.ArgumentParser(prog=f'region.py {name}', description=(module.__doc__ or '').strip() or None)
    add_common(parser)
    if callable(getattr(module, 'add_arguments', None)):
        module.add_arguments(parser)
    args = parser.parse_args(argv)
    scopes = getattr(module, 'SCOPES', None)
    if scopes is None and args.scope is not None:
        parser.error(f'stage {stage} takes no --scope')
    if scopes is not None and args.scope not in scopes:
        parser.error(f'stage {stage} needs --scope, one of {", ".join(scopes)}')
    try:
        region = receipts.Region(args.out, args.region)
        refs = [receipts.Ref.parse(text, args.scope) for text in getattr(module, 'UPSTREAM', ())]
        digest = receipts.stage_digest(receipts.module_code_files(module))
    except receipts.ReceiptError as exc:
        parser.error(str(exc))
    ctx = receipts.StageContext(region=region, scope=args.scope, args=args)

    def plan(upstream):
        ctx.upstream = upstream
        return module.plan(ctx) if callable(getattr(module, 'plan', None)) else receipts.Plan()

    run = receipts.StageRun(region=region, stage=stage, scope=args.scope, build=lambda out: module.build(ctx, out),
                            code_digest=digest, upstream=refs, plan=plan, target=getattr(module, 'TARGET', None))
    result = receipts.run_stage(run)
    print(result.line())
    return result.exit_code


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in {'-h', '--help'}:
        print((__doc__ or '').strip())
        return 0 if argv else 2
    name, rest = argv[0], argv[1:]
    if name == 'status':
        return status(rest)
    try:
        module = resolve_stage(name)
    except UnknownStage as exc:
        print(f'region.py: {exc}', file=sys.stderr)
        return 2
    return run_module(name, module, rest)


if __name__ == '__main__':
    sys.exit(main())
