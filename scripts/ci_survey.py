"""Run the unchanged full pytest collection in balanced, audited CI shards.

Weights affect placement ONLY. Every collected node (including new tests) is
assigned exactly once. Each shard collects all default testpaths with GIS
required; its receipt binds collected, selected and actually executed node IDs.
"""
import argparse
from collections import Counter
import json
import math
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
WEIGHTS = ROOT / 'scripts/ci-survey-weights.json'


def junit_id(nodeid):
    parts = nodeid.split('::')
    return '.'.join([parts[0].removesuffix('.py').replace('/', '.'), *parts[1:-1]]) + '::' + parts[-1]


def partition(nodeids, count, weights):
    if count < 1 or not nodeids or len(set(nodeids)) != len(nodeids):
        raise ValueError('invalid shard count, empty collection or duplicate node IDs')
    if any(not isinstance(v, (int, float)) or not math.isfinite(v) or v <= 0 for v in weights.values()):
        raise ValueError('weights must be finite and positive')
    groups, loads = [[] for _ in range(count)], [0.0] * count
    for node in sorted(nodeids, key=lambda n: (-weights.get(junit_id(n), 0.1), n)):
        index = min(range(count), key=lambda i: (loads[i], i))
        groups[index].append(node)
        loads[index] += weights.get(junit_id(node), 0.1)
    return [sorted(group) for group in groups]


def verify(receipts, count, head):
    if len(receipts) != count or {r['shard'] for r in receipts} != set(range(1, count + 1)):
        raise ValueError('missing, duplicate or extra shard receipts')
    reference = receipts[0]['collected']
    if not reference or len(set(reference)) != len(reference):
        raise ValueError('empty or duplicate full collection')
    selected = []
    for receipt in receipts:
        if receipt['count'] != count or receipt['head'] != head or receipt['exit_code'] != 0:
            raise ValueError('wrong head, count or failing pytest exit')
        if receipt['collected'] != reference:
            raise ValueError('shards collected different test universes')
        if not receipt['selected'] or Counter(receipt['executed']) != Counter(receipt['selected']):
            raise ValueError('selected tests did not all execute exactly once')
        selected.extend(receipt['selected'])
    if Counter(selected) != Counter(reference):
        raise ValueError('shards omit or repeat collected tests')
    return len(reference)


def make_plugin(pytest, receipt, count, shard, weights):
    class Shard:
        @pytest.hookimpl(wrapper=True, tryfirst=True)
        def pytest_collection_modifyitems(self, config, items):
            # Outermost wrapper: partition only after built-in marking/selection.
            yield
            receipt['collected'] = sorted(item.nodeid for item in items)
            assigned = partition(receipt['collected'], count, weights)[shard - 1]
            receipt['selected'] = assigned
            selected = set(assigned)
            omitted = [item for item in items if item.nodeid not in selected]
            items[:] = [item for item in items if item.nodeid in selected]
            config.hook.pytest_deselected(items=omitted)

        def pytest_runtest_logreport(self, report):
            if report.when == 'call' or (report.when == 'setup' and (report.skipped or report.failed)):
                receipt['executed'].append(report.nodeid)

    return Shard()


def run(args):
    import pytest

    if os.environ.get('SKIPPERCAST_REQUIRE_GIS') != '1' or os.environ.get('PYTEST_ADDOPTS'):
        raise ValueError('GIS must be required and PYTEST_ADDOPTS must be empty')
    if not 1 <= args.shard <= args.count:
        raise ValueError('shard index out of range')
    if args.output.resolve() == ROOT or ROOT in args.output.resolve().parents:
        raise ValueError('reports must stay outside the scanned checkout')
    args.output.mkdir(parents=True, exist_ok=True)
    os.chdir(ROOT)
    sys.path.insert(0, str(ROOT))  # Same root import behavior as python -m pytest.
    weights = json.loads(WEIGHTS.read_text())['seconds']
    receipt = {
        'shard': args.shard, 'count': args.count,
        'head': subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip(),
        'collected': [], 'selected': [], 'executed': [], 'exit_code': None,
    }

    plugin = make_plugin(pytest, receipt, args.count, args.shard, weights)
    code = pytest.main(['--durations=15', f'--junitxml={args.output / "pytest-survey.xml"}'], plugins=[plugin])
    receipt['exit_code'] = int(code)
    (args.output / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
    if code == 0 and (not receipt['selected'] or Counter(receipt['selected']) != Counter(receipt['executed'])):
        raise ValueError('successful pytest run did not execute its exact partition')
    return code


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    runner = sub.add_parser('run')
    runner.add_argument('--shard', type=int, required=True)
    runner.add_argument('--count', type=int, default=4)
    runner.add_argument('--output', type=Path, required=True)
    checker = sub.add_parser('verify')
    checker.add_argument('directory', type=Path)
    checker.add_argument('--count', type=int, default=4)
    checker.add_argument('--head', required=True)
    args = parser.parse_args()
    if args.command == 'run':
        return run(args)
    receipts = [json.loads(path.read_text()) for path in sorted(args.directory.glob('*/receipt.json'))]
    total = verify(receipts, args.count, args.head)
    print(f'PASS: {total} collected tests executed exactly once across {args.count} successful shards at {args.head}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
