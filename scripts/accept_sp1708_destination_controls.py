#!/usr/bin/env python3
"""Offline, file-based SP-17 acceptance runner. Every child is an explicit argv."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

SCRIPT = Path(__file__).resolve()
REPO = SCRIPT.parents[1]
WRITE_ROOT = REPO.parent
MANIFEST = WRITE_ROOT / 'SOURCE-MANIFEST.json'
TEST = 'tests/test_sp1708_destination_controls.mjs'
BASE = '8a805820c30895f5f037e26af9079fd3dc015b0f'

def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

def run_child(argv: list[str], cwd: Path, output: Path, label: str) -> dict:
    started = time.time()
    proc = subprocess.run(argv, cwd=cwd, capture_output=True, text=True, check=False)
    stdout, stderr = proc.stdout.encode(), proc.stderr.encode()
    stdout_path, stderr_path = output / f'{label}.stdout', output / f'{label}.stderr'
    stdout_path.write_bytes(stdout)
    stderr_path.write_bytes(stderr)
    text = proc.stdout + proc.stderr
    counts = {}
    for key in ('tests', 'pass', 'fail', 'cancelled', 'skipped', 'todo'):
        match = re.search(rf'^# {key} (\d+)$', proc.stdout, re.M)
        if match:
            counts[key] = int(match.group(1))
    return {'argv': argv, 'cwd': str(cwd), 'exit': proc.returncode, 'duration_seconds': round(time.time()-started, 3),
            'counts': counts, 'stdout_path': str(stdout_path), 'stderr_path': str(stderr_path),
            'stdout_sha256': sha(stdout), 'stderr_sha256': sha(stderr), 'combined_sha256': sha(text.encode()),
            'output': text[-12000:]}

def node_test(args: list[str]) -> list[str]:
    return ['pnpm', 'exec', 'node', '--experimental-strip-types', '--test', *args]

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--phase', required=True, choices=('baseline','focused','regression','repository','typecheck','build'))
    parser.add_argument('--output', required=True)
    ns = parser.parse_args()
    out = Path(ns.output).resolve()
    out.mkdir(parents=True, exist_ok=False)
    manifest = json.loads(MANIFEST.read_text(encoding='utf-8'))
    if manifest.get('schema') != 'agentorange.source-manifest/v1' or manifest.get('repo') != str(REPO) or manifest.get('head') != BASE:
        print('source manifest identity mismatch', file=sys.stderr)
        return 2
    head_proc = subprocess.run(['git','rev-parse','HEAD'],cwd=REPO,capture_output=True,text=True,check=False)
    if head_proc.returncode:
        print('could not identify candidate HEAD',file=sys.stderr)
        return 2
    record = {'schema':'skippercast.sp1708.acceptance/v1','phase':ns.phase,'source_manifest_sha256':sha(MANIFEST.read_bytes()),
              'pinned_base':BASE,'candidate_head':head_proc.stdout.strip(),'runtime':manifest.get('runtime',{}),'source_files':{
                  name:sha((REPO/name).read_bytes()) for name in ('server/fleet/go.ts',TEST,'scripts/accept_sp1708_destination_controls.py','tests/fixtures/sp1708_destination_controls/cases.json','docs/engineering/sp1708_destination_controls.md') if (REPO/name).is_file()},
              'children':[],'result':'FAIL'}
    commands = []
    if ns.phase == 'baseline':
        commands = [('baseline-pair', node_test(['--test-reporter=tap','--test-name-pattern=SP1708 (A1 baseline|healthy control)',TEST]))]
    elif ns.phase == 'focused':
        commands = [('focused', node_test(['--test-reporter=tap',TEST]))]
    elif ns.phase == 'regression':
        commands = [('fleet-go-regression', node_test(['--test-reporter=tap','tests/test_fleet_go.mjs']))]
    elif ns.phase == 'repository':
        commands = [('repository-scan',[manifest['runtime']['credential_scan_python3'],'scripts/check_repository.py'])]
    elif ns.phase == 'typecheck':
        commands = [('typecheck-root',['pnpm','exec','tsc','--noEmit','--project','tsconfig.json']),
                    ('typecheck-web',['pnpm','exec','tsc','--noEmit','--project','web/tsconfig.json']),
                    ('typecheck-coast',['pnpm','exec','tsc','--noEmit','--project','packages/coast/tsconfig.json'])]
    elif ns.phase == 'build':
        commands = [('build',['pnpm','build'])]
    for label, argv in commands:
        result = run_child(argv, REPO, out, label)
        record['children'].append({'label':label,**result})
        if ns.phase == 'baseline':
            # Expected diagnostic: one real assertion failure and one healthy pass; no setup failure/skip.
            ok = (result['exit'] == 1 and result['counts'].get('tests') == 2 and result['counts'].get('pass') == 1
                  and result['counts'].get('fail') == 1 and result['counts'].get('skipped') == 0
                  and 'AssertionError' in result['output'] and 'bo-control-ok' in result['output'])
        else:
            ok = result['exit'] == 0
        if not ok:
            record['failure'] = f'{label} did not meet phase contract'
            break
    if ns.phase == 'focused' and record['children']:
        counts = record['children'][0]['counts']
        if not (counts.get('tests') == 5 and counts.get('pass') == 5 and counts.get('fail') == 0 and counts.get('skipped') == 0):
            record['failure'] = 'focused suite count/skip contract mismatch'
    record['result'] = 'PASS' if 'failure' not in record else 'FAIL'
    record_path = out / 'acceptance.json'
    record_path.write_text(json.dumps(record,indent=2,sort_keys=True)+'\n',encoding='utf-8')
    print(json.dumps({'result':record['result'],'record':str(record_path),'children':[
        {'label':x['label'],'argv':x['argv'],'cwd':x['cwd'],'exit':x['exit'],'counts':x['counts'],'stdout_sha256':x['stdout_sha256'],'stderr_sha256':x['stderr_sha256']} for x in record['children']]},indent=2))
    return 0 if record['result'] == 'PASS' else 1

if __name__ == '__main__':
    raise SystemExit(main())
