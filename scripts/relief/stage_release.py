#!/usr/bin/env python3
"""Controller entry point. Read selected Git blobs; never import candidate code."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import re
import subprocess
import sys

CONTROLLER = Path(__file__).resolve().parents[2]
if __name__ == '__main__':
    sys.path[:0] = [str(CONTROLLER / 'src'), str(CONTROLLER)]

from scripts import check_deploy_source as source  # noqa: E402
from skippercast.relief import package, stage_transport as stage  # noqa: E402


def deploy_mode(env, event):
    if (env.get('GITHUB_REPOSITORY') != stage.REPOSITORY or env.get('GITHUB_REF') != 'refs/heads/main'
            or env.get('GITHUB_REF_PROTECTED') != 'true' or env.get('RUNNER_ENVIRONMENT') != 'github-hosted'):
        raise stage.StageError('STAGE requires the protected SkipperCast main path on a hosted runner')
    name = env.get('GITHUB_EVENT_NAME')
    if name == 'workflow_dispatch' and event.get('inputs', {}).get('action') == 'deploy':
        return 'read-back'  # manual deploy does not authorize new objects
    run = event.get('workflow_run', {})
    if (name == 'workflow_run' and event.get('action') == 'completed'
            and run.get('path') == '.github/workflows/ci.yml' and run.get('name') == 'Offline checks'
            and run.get('event') == 'push' and run.get('head_branch') == 'main'
            and run.get('status') == 'completed' and run.get('conclusion') == 'success'
            and (run.get('head_repository') or {}).get('full_name') == stage.REPOSITORY):
        return 'copy'
    raise stage.StageError('event cannot copy or verify staged relief')


def pointers(tree, sha):
    """Only regular top-level regional JSON blobs from this exact commit can opt in."""
    if not source.is_sha(sha):
        raise stage.StageError('invalid CI-selected SHA')
    source.verify_checkout(str(tree), sha)

    def git(*args):
        return subprocess.run(['git', '-C', str(tree), *args], check=True, capture_output=True, timeout=30).stdout

    # Include tree records to reject a symlink or unexpected subtree instead of
    # treating it as an empty catalogue. Old commits may lack the directory.
    catalog = git('ls-tree', '-z', sha, '--', 'catalog')
    if catalog and not catalog.startswith(b'040000 tree '):
        raise stage.StageError('selected catalogue is not a Git tree')
    result = []
    for entry in git('ls-tree', '-rtz', sha, '--', 'catalog/relief').split(b'\0'):
        if not entry:
            continue
        meta, path = entry.split(b'\t', 1)
        mode, kind, oid = meta.decode('ascii').split()
        if path in {b'catalog', b'catalog/relief'} and kind == 'tree':
            continue
        if mode not in {'100644', '100755'} or kind != 'blob':
            raise stage.StageError('non-regular file in selected relief catalogue')
        name = path.decode('ascii').removeprefix('catalog/relief/')
        if name in {'README.md', 'pointer.schema.json'}:
            continue
        region = name.removesuffix('.json')
        if (not name.endswith('.json') or len(region) > 64 or not stage.REGION.fullmatch(region)
                or not re.fullmatch('[0-9a-f]{40}', oid) or int(git('cat-file', '-s', oid)) > 1 << 20):
            raise stage.StageError('invalid selected relief pointer path or size')
        pointer = package.decode_document(git('cat-file', 'blob', oid))
        if pointer.get('region') != region:
            raise stage.StageError('relief pointer region does not match its selected path')
        result.append(pointer)
    return result


def run(env, *, probe):
    event = package.decode_document(Path(env['GITHUB_EVENT_PATH']).read_bytes())
    mode = deploy_mode(env, event)
    sha = env['DEPLOY_SHA']
    selected = pointers(Path(env['STAGE_TREE']), sha)
    if probe:
        with Path(env['GITHUB_OUTPUT']).open('a') as stream:
            stream.write('required=' + ('true' if selected else 'false') + '\n')
    if not selected:
        print('No reviewed relief pointers in the selected commit.')
        return
    if probe:
        return
    try:
        # No relief deployment is admitted before DL-10 is actually on the controller.
        from skippercast.relief.publish import plan as _publish_plan  # noqa: F401
    except ImportError:
        raise stage.StageError('DL-10 publish core unavailable on the controller') from None
    # Use the controller's reviewed schema and current source policy. The
    # selected commit is a data input, not a source of scripts or validators.
    schema = package.pointer_schema()
    registry = package.decode_document((CONTROLLER / 'catalog/sources.json').read_bytes())
    for pointer in selected:
        package.validate_schema(pointer, schema)
        package.validate_metadata(pointer, schema, registry)
    gh = stage.GitHubRelease(env['STAGE_GITHUB_READ_TOKEN'])

    def recheck():
        source.verify_source(stage.REPOSITORY, env['GITHUB_REF'], sha, read=gh.metadata)

    recheck()
    r2 = stage.R2.connect(env.get('R2_PUBLISH_TOKEN', ''), env.get('CLOUDFLARE_ACCOUNT_ID', ''))
    for pointer in selected:
        count = stage.copy_release(pointer, gh, r2, allow_create=(mode == 'copy'), recheck=recheck)
        print(f"Relief verified: {pointer['region']} ({count} objects), selected commit {sha}.")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--probe', action='store_true', help='report whether the selected commit needs a relief copy')
    args = parser.parse_args(argv)
    try:
        run(os.environ, probe=args.probe)
    except stage.StageError as error:
        print(f'::error::Relief STAGE held: {error}', file=sys.stderr)
        return 1
    except Exception as error:
        # SDK, serde and transport exceptions may contain headers, a signed
        # media URL, or untrusted metadata. Never log their bodies/tracebacks.
        print(f'::error::Relief STAGE held ({type(error).__name__}); no pointer deployed.', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
