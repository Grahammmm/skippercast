"""Conservative CI selection and fail-closed aggregate checks (stdlib only)."""
import json
import os
from pathlib import Path
import re
import subprocess
import sys


# These files configure contribution forms, not product/test inputs. Core Python,
# repository scans, web checks and DCO still run. Do NOT blanket-ignore docs/:
# claims/contract tests read documentation and receipts there.
def forms_only(path):
    return path == '.github/pull_request_template.md' or path.startswith('.github/ISSUE_TEMPLATE/')


def e2e_irrelevant(path):
    # The browser serves the committed dist/ + JS/TS build, not the Python
    # source or Python test tree. Generated outputs are separate changed paths.
    return forms_only(path) or (
        path.endswith('.py') and path.startswith(('src/skippercast/', 'tests/', 'research/tests/'))
    )


def plan(event, branch, paths=None):
    full = event != 'pull_request' or branch == 'main' or branch.startswith('batch/')
    paths = paths or []
    known = bool(paths) and all(isinstance(p, str) and p and not p.startswith('/') and '..' not in p.split('/') for p in paths)
    return {
        'python': ['3.11', '3.12', '3.13'] if full else ['3.13'],
        'survey': full or not known or not all(forms_only(p) for p in paths),
        'e2e': full or not known or not all(e2e_irrelevant(p) for p in paths),
    }


def changed_paths(env):
    base, head = env.get('CI_BASE_SHA', ''), env.get('CI_HEAD_SHA', '')
    if not all(re.fullmatch(r'[0-9a-f]{40}', sha) for sha in (base, head)):
        return None
    try:
        subprocess.run(['git', 'fetch', '--no-tags', '--depth=1', 'origin', base, head], check=True, timeout=120)
        # Comparing the two complete trees is conservative if main advanced;
        # --no-renames includes both old and new paths. No API pagination limit.
        raw = subprocess.check_output(['git', 'diff', '--no-renames', '--name-only', '-z', base, head], timeout=30)
        return raw.decode('utf-8').rstrip('\0').split('\0') if raw else []
    except (subprocess.SubprocessError, UnicodeError):
        print('Changed paths unavailable; running all suites.', file=sys.stderr)
        return None


def check_gate(needs, target):
    if needs['changes']['result'] != 'success':
        raise ValueError('selection job did not succeed')
    outputs = needs['changes']['outputs']
    suites = [('e2e-tests', 'e2e')]
    if target == 'survey-science':
        suites += [('survey-shard', 'survey')]
        for name in ('check', 'web'):
            if needs[name]['result'] != 'success':
                raise ValueError(f'{name} did not succeed')
    for job, selector in suites:
        expected = outputs.get(selector)
        if expected not in ('true', 'false'):
            raise ValueError(f'missing or invalid {selector} selection')
        required = 'success' if expected == 'true' else 'skipped'
        if needs[job]['result'] != required:
            raise ValueError(f'{job}: expected {required}, got {needs[job]["result"]}')
    return 'All selected checks passed; irrelevant suites explicitly accounted for.'


def main():
    if len(sys.argv) == 3 and sys.argv[1] == 'gate':
        if sys.argv[2] not in ('e2e', 'survey-science'):
            raise ValueError('unknown aggregate')
        print(check_gate(json.loads(os.environ['NEEDS_JSON']), sys.argv[2]))
        return
    if len(sys.argv) != 1:
        raise ValueError('usage: ci_plan.py [gate e2e|survey-science]')
    event = os.environ['GITHUB_EVENT_NAME']
    branch = os.environ.get('GITHUB_HEAD_REF') or os.environ.get('GITHUB_REF_NAME', '')
    paths = changed_paths(os.environ) if event == 'pull_request' and not branch.startswith('batch/') else None
    result = plan(event, branch, paths)
    print(json.dumps({'selection': result, 'changed_paths': paths}, indent=2))
    with Path(os.environ['GITHUB_OUTPUT']).open('a') as output:
        for key, value in result.items():
            output.write(f'{key}={json.dumps(value, separators=(",", ":"))}\n')


if __name__ == '__main__':
    main()
