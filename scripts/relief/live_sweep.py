#!/usr/bin/env python3
"""Check every reviewed relief pointer in a clean clone, without rolling back.

Keep fresh receipts in a new live-sweep-* directory under OUT. A dash in the
requests column means live-check did not provide a usable receipt.
"""
import argparse
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys
from tempfile import mkdtemp


_REGION_CLI = Path(__file__).resolve().with_name('region.py')


def _check_region(region, repo, run_out, base):
    command = [sys.executable, '-B', str(_REGION_CLI), 'live-check',
               '--region', region, '--repo', str(repo), '--out', str(run_out)]
    if base is not None:
        command.append(f'--base={base}')
    try:
        result = subprocess.run(command, check=False)
        if result.returncode not in (0, 1):
            raise ValueError(f'live-check exited {result.returncode}')
        verdict = 'PASS' if result.returncode == 0 else 'FAIL'
        receipts = list((run_out / region / 'live').glob('*/live.json'))
        if len(receipts) != 1:
            raise ValueError('expected exactly one fresh live-check receipt')
        doc = json.loads(receipts[0].read_text(encoding='utf-8'))
        if (not isinstance(doc, dict) or doc.get('region') != region
                or doc.get('verdict') != verdict or type(doc.get('requests')) is not int
                or doc['requests'] < 0):
            raise ValueError('invalid live-check receipt')
        return verdict, doc['requests']
    except (OSError, ValueError) as exc:
        print(f'{region}: {exc}', file=sys.stderr)
        return 'FAIL', '-'


def main(argv=None):
    parser = argparse.ArgumentParser(prog='live_sweep.py', description=__doc__)
    parser.add_argument('--repo', required=True, type=Path)
    parser.add_argument('--out', required=True, type=Path)
    parser.add_argument('--base')
    args = parser.parse_args(argv)
    try:
        repo, out = args.repo.resolve(), args.out.resolve()
        if out.is_relative_to(repo):
            raise ValueError('OUT must stay outside --repo')
        # Select region filenames, not pointer.schema.json; live-check validates the pointers.
        regions = sorted(path.stem for path in (repo / 'catalog' / 'relief').iterdir()
                         if re.fullmatch(r'[a-z0-9][a-z0-9-]{0,63}\.json', path.name)
                         and path.is_file())
        run_out = out
        if regions:
            out.mkdir(parents=True, exist_ok=True)
            run_out = Path(mkdtemp(prefix='live-sweep-', dir=out))
    except (OSError, ValueError) as exc:
        print(f'{parser.prog}: {exc}', file=sys.stderr)
        return 2

    print('region verdict requests', flush=True)
    failed = []
    for region in regions:
        verdict, requests = _check_region(region, repo, run_out, args.base)
        print(f'{region} {verdict} {requests}', flush=True)
        if verdict == 'FAIL':
            failed.append(region)

    for region in failed:
        print(shlex.join(['python', 'scripts/relief/region.py', 'rollback',
                          '--region', region, '--repo', str(repo)]))
    if failed:
        print('FAIL regions: ' + ', '.join(failed))
        return 1
    print('ALL PASS')
    return 0


if __name__ == '__main__':
    sys.exit(main())
