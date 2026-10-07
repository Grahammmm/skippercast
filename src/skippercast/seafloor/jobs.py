"""Shared CI orchestration; all geography comes from the catalog and ledger."""
import argparse
import json
import os
import re
import subprocess
import tempfile
import traceback
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from skippercast.platform.contracts import REPO, read_json, atomic_json
from . import state_cache
from .io import sha256
from .publish import credentials, upload
from .restore import restore_reference
from .run import run, apply_ledger
from .screen_sources import refresh
from .rollout import plan, report

WORKER_GROUP_SIZE = 3
REACH_TIMEOUT_SECONDS = 60 * 60
CLASSIFIED_POLICY_PATH = 'catalog/classified-habitat-policy.json'
CLASSIFIED_POLICY_PROFILE = 'original-rugose-classified-area-v1'
CLASSIFIED_POLICY_CHANGELOG = 'CHANGELOG.md'


def publication_origin(error):
    """Report pipeline code locations without exception payloads or data paths."""
    directory = Path(__file__).resolve().parent
    frames = [frame for frame in traceback.extract_tb(error.__traceback__)
              if Path(frame.filename).resolve().parent == directory]
    if not frames:
        return None
    frame = frames[-1]
    return {'module': Path(frame.filename).name, 'function': frame.name, 'line': frame.lineno}


def scoped_policy_change(old, new, changed_paths, reach_rows):
    """Scope policy plus optional changelog deltas; reject every other cochange."""
    if (CLASSIFIED_POLICY_PATH not in changed_paths
            or not set(changed_paths).issubset({CLASSIFIED_POLICY_PATH,
                                                CLASSIFIED_POLICY_CHANGELOG})):
        return None

    def rows(document):
        if (not isinstance(document, dict) or document.get('schema_version') != 1
                or document.get('profile') != CLASSIFIED_POLICY_PROFILE
                or not isinstance(document.get('sources'), list)):
            return None
        result, order = {}, []
        for row in document['sources']:
            if not isinstance(row, dict) or not isinstance(row.get('id'), str):
                return None
            if row['id'] in result:
                return None
            result[row['id']] = row
            order.append(row['id'])
        return result, order

    old_parsed, new_parsed = rows(old), rows(new)
    if old_parsed is None or new_parsed is None:
        return None
    if ({key: value for key, value in old.items() if key != 'sources'}
            != {key: value for key, value in new.items() if key != 'sources'}):
        return None
    old_rows, old_order = old_parsed
    new_rows, new_order = new_parsed
    changed = {ident for ident in old_rows.keys() | new_rows.keys()
               if old_rows.get(ident) != new_rows.get(ident)}
    old_common = [ident for ident in old_order if ident in new_rows]
    new_common = [ident for ident in new_order if ident in old_rows]
    new_position = {ident: index for index, ident in enumerate(new_common)}
    for index, left in enumerate(old_common):
        for right in old_common[index+1:]:
            if new_position[left] > new_position[right]:
                # Only participants in an actual inversion changed relative
                # priority. An unchanged unscoped row elsewhere is irrelevant.
                changed.update((left, right))

    affected = set()
    for ident in changed:
        for row in (old_rows.get(ident), new_rows.get(ident)):
            if row is None:
                continue
            reach_ids = row.get('reach_ids')
            if (not isinstance(reach_ids, list) or not reach_ids
                    or any(not isinstance(value, str) or not value for value in reach_ids)
                    or len(reach_ids) != len(set(reach_ids))):
                return None
            neighbors = row.get('neighbor_reaches', [])
            if (not isinstance(neighbors, list)
                    or ('neighbor_reaches' in row and not neighbors)
                    or any(not isinstance(value, str) or not value for value in neighbors)
                    or len(neighbors) != len(set(neighbors))):
                return None
            affected.update(reach_ids)
            affected.update(neighbors)

    if not affected:
        return None
    reach_map = {}
    for row in reach_rows:
        if (not isinstance(row, dict) or not isinstance(row.get('id'), str)
                or not isinstance(row.get('region'), str) or row['id'] in reach_map):
            return None
        reach_map[row['id']] = row
    if any(ident not in reach_map or reach_map[ident].get('status') == 'unassessed'
           for ident in affected):
        return None
    return {'reach_ids': sorted(affected),
            'regions': sorted({reach_map[ident]['region'] for ident in affected}),
            'changed_policy_ids': sorted(changed)}


def _policy_snapshot_valid(document, reach_rows):
    """Apply the production policy validator to an immutable snapshot offline."""
    try:
        from .classified_habitat import policies
        with tempfile.TemporaryDirectory(prefix='skippercast-policy-check-') as tmp:
            catalog = Path(tmp)/'catalog'
            catalog.mkdir()
            (catalog/'classified-habitat-policy.json').write_text(
                json.dumps(document, sort_keys=True))
            (catalog/'reaches.json').write_text(json.dumps({'reaches': [
                {'id': row['id']} for row in reach_rows]}))
            policies(tmp)
        return True
    except Exception:
        # A snapshot that the exact production validator cannot accept is not
        # eligible for regional narrowing.
        return False


def _scoped_policy_plan(root, scope, progress):
    """Plan full processed reach closure, but only for policy-affected regions."""
    documents = [plan(root, region, 0, progress=progress) for region in scope['regions']]

    def unique_rows(key):
        seen, result = set(), []
        for document in documents:
            for row in document[key]:
                identity = json.dumps(row, sort_keys=True)
                if identity not in seen:
                    seen.add(identity)
                    result.append(row)
        return result

    combined = dict(documents[0])
    combined['scope'] = 'classified-policy-only:'+','.join(scope['regions'])
    combined['policy_scope'] = scope
    combined['reaches'] = [row for document in documents for row in document['reaches']]
    combined['selected'] = [row for document in documents for row in document['selected']]
    combined['new_reaches'] = []
    combined['execution'] = {
        'new_reach_batch_selected': False,
        'refresh_reaches': [row['reach'] for row in combined['selected']],
        'next_action': 'restage-scoped-classified-policy',
        'next_action_reason': 'Restage changed source interpretations and republish each affected complete region; no new reach is selected.',
        'additional_measured_km2': None,
        'notice': 'This source-policy-only scope is not measured growth; full affected-region publication remains required.'}
    combined['source_review_queue'] = unique_rows('source_review_queue')
    combined['deferred_source_reviews'] = unique_rows('deferred_source_reviews')
    combined['source_review_warnings'] = list(dict.fromkeys(
        warning for document in documents for warning in document['source_review_warnings']))
    combined['notice'] = ('Source-policy-only scoped plan for regions '
                          + ', '.join(scope['regions']) + '. Every processed reach in each affected region '
                          'remains selected so the complete regional archive can be rebuilt and verified.')
    return combined


def regional_batch_rows(all_rows, selected, progress):
    """Keep complete processed-region closure for coherent publication."""
    regions = {row['region'] for row in selected}
    selected_ids = {row.get('reach', row.get('id')) for row in selected}
    return [row for row in all_rows if row['region'] in regions and
            (row['status'] != 'unassessed' or row['id'] in selected_ids or row['id'] in progress)]


def _push_policy_scope(root):
    """Inspect a push's exact Git delta; uncertainty returns global fallback."""
    if os.environ.get('GITHUB_EVENT_NAME') != 'push':
        return None
    try:
        event = read_json(Path(os.environ['GITHUB_EVENT_PATH']))
        before, after = event['before'], event['after']
        if (not re.fullmatch(r'[0-9a-f]{40,64}', before or '')
                or not re.fullmatch(r'[0-9a-f]{40,64}', after or '')
                or set(before) == {'0'}):
            return {'mode': 'global-fallback', 'reason': 'push base/target identity unavailable'}
        def git(*args, check=True):
            return subprocess.run(['git', *args], cwd=Path(root), stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL, check=check, timeout=30).stdout
        head = git('rev-parse', 'HEAD').decode().strip()
        if head != after:
            return {'mode': 'global-fallback', 'reason': 'checkout does not match push target'}
        def is_ancestor():
            return subprocess.run(['git', 'merge-base', '--is-ancestor', before, after],
                cwd=Path(root), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                timeout=30).returncode == 0
        if not is_ancestor():
            shallow = git('rev-parse', '--is-shallow-repository').decode().strip() == 'true'
            if shallow:
                # Deepen from the exact checked-out target. Fetching the base
                # at depth one alone leaves both commits as shallow boundaries,
                # so merge-base cannot prove their relationship.
                subprocess.run(['git', 'fetch', '--no-tags', '--deepen=64', 'origin', after],
                    cwd=Path(root), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    check=True, timeout=60)
        if subprocess.run(['git', 'cat-file', '-e', before+'^{commit}'],
                cwd=Path(root), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                timeout=30).returncode != 0 or not is_ancestor():
            return {'mode': 'global-fallback', 'reason': 'push base is not an ancestor'}
        changed_paths = git('diff', '--name-only', '-z', before, after).decode().split('\0')
        changed_paths = sorted(path for path in changed_paths if path)
        old_raw = git('show', f'{before}:{CLASSIFIED_POLICY_PATH}')
        target_raw = git('show', f'{after}:{CLASSIFIED_POLICY_PATH}')
        working_raw = (Path(root)/CLASSIFIED_POLICY_PATH).read_bytes()
        if target_raw != working_raw:
            return {'mode': 'global-fallback', 'reason': 'policy file differs from push target'}
        old, new = json.loads(old_raw), json.loads(target_raw)
        reach_rows = read_json(Path(root)/'dist/data/seafloor-ledger.json')['reaches']
        if (not _policy_snapshot_valid(old, reach_rows)
                or not _policy_snapshot_valid(new, reach_rows)):
            return {'mode': 'global-fallback', 'reason': 'policy snapshot failed production validation'}
        scope = scoped_policy_change(old, new, changed_paths, reach_rows)
        if scope is None:
            return {'mode': 'global-fallback',
                    'reason': 'policy delta is cochanged, unscoped, or unresolved'}
        return {'mode': 'scoped', **scope}
    except (KeyError, OSError, ValueError, TypeError, json.JSONDecodeError,
            subprocess.SubprocessError):
        return {'mode': 'global-fallback', 'reason': 'push policy comparison failed'}


def worker_groups(matrix):
    """Partition exact reach assignments; never broaden or drop publication work."""
    regions, seen = {}, set()
    for row in matrix['include']:
        reach, region = row['reach'], row['region']
        state_cache.scope_name(reach)
        state_cache.scope_name(region)
        if reach in seen:
            raise ValueError('Duplicate reach in worker matrix')
        seen.add(reach)
        regions.setdefault(region, []).append(reach)
    return {'include': [
        {'region': region, 'group': index // WORKER_GROUP_SIZE + 1,
         'reaches': reaches[index:index + WORKER_GROUP_SIZE]}
        for region, reaches in regions.items()
        for index in range(0, len(reaches), WORKER_GROUP_SIZE)]}


def select(root, region=None, reach=None):
    rows = read_json(Path(root)/'dist/data/seafloor-ledger.json')['reaches']
    if reach:
        selected = [r for r in rows if r['id'] == reach and (not region or r['region'] == region)]
    else:
        selected = [r for r in rows if r['status'] != 'unassessed' and (not region or r['region'] == region)]
    if not selected:
        raise ValueError('No processed reaches in requested scope; qualify a reach before publishing')
    return selected


def read_progress(s3, bucket, reaches):
    """Lightweight scheduling state; never publishes or credits unmerged results."""
    def read(ident):
        try:
            with s3.get_object(Bucket=bucket, Key=f'seafloor-review/progress/{ident}.json')['Body'] as stream:
                raw = stream.read(1_000_001)
            if len(raw) > 1_000_000:
                raise ValueError('Oversized progress receipt')
            value = json.loads(raw)
            if value['reach'] != ident or value['status'] not in ('complete', 'coverage-only'):
                raise ValueError('Invalid progress receipt')
            return ident, value
        except Exception as error:
            if state_cache.missing(error):
                return ident, None
            raise
    with ThreadPoolExecutor(max_workers=4) as pool:
        return {ident: value for ident, value in pool.map(read, reaches) if value is not None}


def prepare(root, region=None, reach=None, max_new=3):
    s3, bucket = credentials()
    root = Path(root)
    state_cache.restore(s3, bucket, root, 'shared')
    state_cache.restore(s3, bucket, root, 'source-review')
    reference = root/'var/seafloor/reference/cells.json'
    expected = read_json(root/'dist/data/seafloor-ledger.json')['reference_cells_sha256']
    if not reference.exists() or sha256(reference) != expected:
        restore_reference(root=root, fetch=True)
    all_rows = read_json(root/'dist/data/seafloor-ledger.json')['reaches']
    policy_change = _push_policy_scope(root) if region is None and reach is None else None
    if policy_change and policy_change['mode'] == 'scoped':
        affected_regions = set(policy_change['regions'])
        progress_ids = [r['id'] for r in all_rows if r['region'] in affected_regions]
        progress = read_progress(s3, bucket, progress_ids)
        rollout = _scoped_policy_plan(root, policy_change, progress)
    else:
        progress = read_progress(s3, bucket, [r['id'] for r in all_rows])
        rollout = plan(root, region, max_new, progress=progress)
        if policy_change and policy_change['mode'] == 'global-fallback':
            rollout['policy_scope_fallback'] = policy_change['reason']
            rollout['notice'] += ' Policy-only scope fell back to the global planner: '+policy_change['reason']+'.'
    atomic_json(root/'var/seafloor/rollout-plan.json', rollout, indent=2)
    (root/'var/seafloor/rollout-plan.md').write_text(report(rollout))
    selected = select(root, region, reach) if reach else rollout['selected']
    regions = sorted({r['region'] for r in selected})
    rows = regional_batch_rows(all_rows, selected, progress)
    # Fail closed during this update, but do not let refresh failure stop the
    # physical mapping workers. Their new candidates will remain private/held.
    for name in regions:
        s3.put_object(Bucket=bucket, Key=f'tiles/seafloor/manifest-{name}.json',
            Body=b'{"status":"updating"}', ContentType='application/json', CacheControl='no-store')
    try:
        refresh(root=root)
    except Exception as error:
        atomic_json(root/'var/seafloor/screen/refresh-failure.json',
                    {'status': 'failed', 'error_type': type(error).__name__})
        for name in regions:
            s3.put_object(Bucket=bucket, Key=f'tiles/seafloor/manifest-{name}.json',
                Body=b'{"status":"held","reason":"screen-refresh-failed"}',
                ContentType='application/json', CacheControl='no-store')
    state_cache.save(s3, bucket, root, 'shared', state_cache.shared_paths(root))
    return {'include': [{'reach': row['id'], 'region': row['region']} for row in rows]}


def batch_key(batch, reach):
    if not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_-]{0,99}', batch or ''):
        raise ValueError('A unique safe batch ID is required')
    state_cache.scope_name(reach)
    return f'seafloor-review/batches/{batch}/{reach}.json'


def process(root, reach, batch):
    s3, bucket = credentials()
    key = batch_key(batch, reach)
    root = Path(root)
    folder = root/'var/seafloor/reaches'/reach
    checkpoint = folder/'coverage-checkpoint.json'
    result = {'reach': reach, 'batch': batch, 'status': 'failed'}
    started_run = False
    try:
        state_cache.restore(s3, bucket, root, reach)
        state_cache.restore(s3, bucket, root, 'shared')
        checkpoint.unlink(missing_ok=True)  # never credit a previous failed attempt
        started_run = True
        receipt, unchanged = run(reach, root=root, fetch=True)
        from .classified_habitat import stage
        classified = stage(reach, root=root, fetch=True)
        state_cache.save(s3, bucket, root, reach, state_cache.reach_paths(root, reach))
        result.update(status='complete', unchanged=unchanged, input_hash=receipt['input_hash'],
                      physical_reused=receipt.get('physical_reused', False),
                      summary=receipt['ledger_summary'])
        if classified is not None:
            result['classified'] = {'input_hash': classified['input_hash'], 'summary': classified['summary']}
        for name in ('run.json', 'atlas-comparison.json'):
            s3.put_object(Bucket=bucket, Key=f'seafloor-review/{reach}/{receipt["input_hash"]}/{name}',
                Body=(folder/name).read_bytes(), ContentType='application/json', CacheControl='private, no-store')
    except Exception as error:
        traceback.print_exc()
        result = {'reach': reach, 'batch': batch, 'status': 'failed'}
        result['error_type'] = type(error).__name__
        result['reason'] = ('normalized-source-review-mismatch' if 'Normalized' in str(error)
                            else 'habitat-window-limit' if '20 million pixels' in str(error)
                            else 'processing-failed; inspect this reach before retry')
        if started_run and checkpoint.exists():
            saved = read_json(checkpoint)
            if sha256(folder/'coverage-cells.json') == saved['cells_sha256']:
                result.update(status='coverage-only', summary=saved['ledger_summary'])
                state_cache.save(s3, bucket, root, reach, state_cache.reach_paths(root, reach))
    # A same-batch result is mandatory. An interrupted/missing worker can never
    # be mistaken for a success restored from a previous run.
    s3.put_object(Bucket=bucket, Key=key, Body=json.dumps(result).encode(),
                  ContentType='application/json', CacheControl='private, no-store')
    if result['status'] in ('complete', 'coverage-only'):
        s3.put_object(Bucket=bucket, Key=f'seafloor-review/progress/{reach}.json',
                      Body=json.dumps(result).encode(), ContentType='application/json', CacheControl='private, no-store')
    return result


def group_member(root, reach, batch):
    """Keep each reach's process lifetime and 60-minute processing limit separate."""
    command = [sys.executable, '-m', 'skippercast.seafloor.jobs', 'run',
               '--reach', reach, '--batch', batch]
    completed = subprocess.run(command, cwd=Path(root), stdout=subprocess.PIPE,
                               text=True, check=True, timeout=REACH_TIMEOUT_SECONDS)
    result = json.loads(completed.stdout)
    if (result.get('reach') != reach or result.get('batch') != batch
            or result.get('status') not in ('complete', 'coverage-only', 'failed')):
        raise ValueError('Grouped worker returned an invalid receipt identity')
    return result


def process_group(root, reaches, region, batch):
    """Run a bounded regional group sequentially, preserving per-reach receipts.

    A failed restore, computation or receipt write must not prevent the remaining
    assigned reaches from running. Missing receipts still fail final publication.
    No successful result is synthesized here and no worker skips native checks.
    """
    state_cache.scope_name(region)
    if (not isinstance(reaches, list) or not 1 <= len(reaches) <= WORKER_GROUP_SIZE
            or any(not isinstance(reach, str) for reach in reaches)
            or len(set(reaches)) != len(reaches)):
        raise ValueError('Worker group must contain one to three unique reaches')
    known = {row['id']: row['region'] for row in
             read_json(Path(root)/'catalog/reaches.json')['reaches']}
    for reach in reaches:
        batch_key(batch, reach)
        if known.get(reach) != region:
            raise ValueError('Worker group contains an unknown or cross-region reach')
    results = []
    for reach in reaches:
        print(f'worker group: process {reach}', file=sys.stderr, flush=True)
        try:
            result = group_member(root, reach, batch)
        except Exception as error:
            traceback.print_exc()
            # This is diagnostic only. Without its checked per-reach receipt,
            # finish() treats the reach as incomplete and blocks that region.
            result = {'reach': reach, 'batch': batch, 'status': 'failed',
                      'reason': 'worker interrupted before retaining its result',
                      'error_type': type(error).__name__}
        results.append(result)
    return {'region': region, 'batch': batch, 'results': results,
            'complete': all(row['status'] == 'complete' for row in results)}


def publication_key(batch, region):
    # Reuse the checked batch-name boundary; region is a private scope name.
    batch_key(batch, state_cache.scope_name(region))
    return f'seafloor-review/batches/{batch}/publish-{region}.json'


def read_publication(s3, bucket, batch, region):
    with s3.get_object(Bucket=bucket, Key=publication_key(batch, region))['Body'] as stream:
        raw = stream.read(5_000_001)
    if len(raw) > 5_000_000:
        raise ValueError('Oversized publication receipt')
    value = json.loads(raw)
    if (value.get('version') != 1 or value.get('batch') != batch
            or value.get('region') != region):
        raise ValueError('Publication receipt identity mismatch')
    for field in ('published', 'ready_regions', 'held_regions', 'failures'):
        if not isinstance(value.get(field), list):
            raise ValueError('Invalid publication receipt inventory')
    if (set(value['ready_regions']) | set(value['held_regions'])) - {region}:
        raise ValueError('Publication receipt region mismatch')
    if set(value['ready_regions']) & set(value['held_regions']):
        raise ValueError('Conflicting publication state')
    if not value['failures'] and not (value['ready_regions'] or value['held_regions']):
        raise ValueError('Missing publication state')
    return value


def finish(root, matrix, batch, *, region=None, ledger_only=False):
    if region is not None:
        state_cache.scope_name(region)
        selected = [row for row in matrix['include'] if row['region'] == region]
        if not selected:
            raise ValueError('Publication region absent from this batch')
        matrix = {'include': selected}
    s3, bucket = credentials()
    state_cache.restore(s3, bucket, root, 'shared')
    before = read_json(Path(root)/'dist/data/seafloor-ledger.json')
    failures, results, blocked_regions = [], [], set()
    for row in matrix['include']:
        ident = row['reach']
        print(f'finish: restore checked batch result {ident}', file=sys.stderr, flush=True)
        try:
            with s3.get_object(Bucket=bucket, Key=batch_key(batch, ident))['Body'] as stream:
                status = json.loads(stream.read(5_000_000))
            if status['batch'] != batch or status['reach'] != ident:
                raise ValueError('Batch result mismatch')
            if status['status'] == 'failed':
                failures.append({'reach': ident, 'reason': status.get('reason', 'processing-failed'),
                                 'error_type': status.get('error_type', 'unknown')})
                blocked_regions.add(row['region'])
                continue
            if not state_cache.restore(s3, bucket, root, ident, include_cache=not ledger_only):
                raise ValueError('Missing reach state')
            if status['status'] == 'complete':
                receipt = read_json(Path(root)/'var/seafloor/reaches'/ident/'run.json')
                if receipt['input_hash'] != status['input_hash'] or receipt['ledger_summary'] != status['summary']:
                    raise ValueError('Reach state differs from this batch')
            elif status['status'] == 'coverage-only':
                checkpoint = read_json(Path(root)/'var/seafloor/reaches'/ident/'coverage-checkpoint.json')
                if checkpoint['ledger_summary'] != status['summary']:
                    raise ValueError('Coverage checkpoint differs from this batch')
                failures.append({'reach': ident, 'reason': status['reason']})
            else:
                raise ValueError('Unknown reach result')
            apply_ledger(Path(root), ident, status['summary'])
        except Exception as error:
            failures.append({'reach': ident, 'reason': type(error).__name__+': no current completed result'})
            blocked_regions.add(row['region'])
    for target_region in ([] if ledger_only else sorted({r['region'] for r in matrix['include']} - blocked_regions)):
        try:
            print(f'finish: build and verify region {target_region}', file=sys.stderr, flush=True)
            results.append(upload(target_region, root=root))
            print(f'finish: retained publication receipt {target_region}', file=sys.stderr, flush=True)
        except Exception as error:
            failure = {'region': target_region, 'reason': type(error).__name__+': publication failed'}
            origin = publication_origin(error)
            if origin is not None:
                failure['origin'] = origin
            print('finish: '+json.dumps(failure), file=sys.stderr, flush=True)
            failures.append(failure)
    if (Path(root)/'var/seafloor/screen/refresh-failure.json').exists():
        failures.append({'reason': 'screen-refresh-failed; physical work retained, habitat held'})
    published = [r['key'] for r in results]
    ready = [r['manifest']['region'] for r in results if r['manifest']['status'] == 'ready']
    held = [r['manifest']['region'] for r in results if r['manifest']['status'] != 'ready']
    if ledger_only:
        for target_region in sorted({r['region'] for r in matrix['include']}):
            try:
                publication = read_publication(s3, bucket, batch, target_region)
                published.extend(publication['published'])
                ready.extend(publication['ready_regions'])
                held.extend(publication['held_regions'])
                failures.extend(publication['failures'])
            except Exception as error:
                failures.append({'region': target_region,
                                 'reason': type(error).__name__+': no verified current publication receipt'})
    elif region is not None:
        receipt = {'version': 1, 'batch': batch, 'region': region,
                   'published': published, 'ready_regions': ready,
                   'held_regions': held, 'failures': failures}
        s3.put_object(Bucket=bucket, Key=publication_key(batch, region),
                      Body=json.dumps(receipt, sort_keys=True).encode(),
                      ContentType='application/json')
    after = read_json(Path(root)/'dist/data/seafloor-ledger.json')
    old = {r['id']: r for r in before['reaches']}
    lines = ['Automated screened seafloor update. No fish-presence claim.', '',
             '| Reach | Tier 1 km² before → after | Tier 2 km² before → after |',
             '| --- | ---: | ---: |']
    for row in after['reaches']:
        prior = old[row['id']]
        if row != prior:
            lines.append(f"| {row['id']} | {prior['tier1_km2']:.6f} → {row['tier1_km2']:.6f} | "
                         f"{prior['tier2_km2']:.6f} → {row['tier2_km2']:.6f} |")
    lines += ['', 'Failures / incomplete stages: '+json.dumps(failures),
              'Published bundles: '+str(len(published)),
              'Ready regions: '+json.dumps(sorted(set(ready))),
              'Held regions: '+json.dumps(sorted(set(held)))]
    lines += ['', 'Zero area delta means refreshed screening/provenance only. Source grids and review receipts remain private.',
              ('Validation: checked worker receipts. Regional PMTiles/R2 results are reported from current-batch publication receipts; ready regions: '+json.dumps(sorted(set(ready)))+'. Coverage totals are not proof of live publication.' if ledger_only else
               'Validation: current source hashes and full-polygon spatial screening; PMTiles build and R2 byte read-back apply only to successful ready regions: '+json.dumps(sorted(set(ready)))+'.')]
    destination = Path(root)/'var/seafloor/ledger-pr.md'
    destination.write_text('\n'.join(lines)+'\n')
    delta = after['totals']['tier2_km2']-before['totals']['tier2_km2']
    return {'published': published, 'failures': failures,
            'ready_regions': sorted(set(ready)), 'held_regions': sorted(set(held)),
            'title': f'Refresh seafloor ledger ({delta:+.3f} km² tier 2)'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage', choices=('prepare', 'run', 'run-group', 'finish'))
    parser.add_argument('--region')
    parser.add_argument('--reach')
    parser.add_argument('--reaches', type=json.loads,
                        help='JSON list of one to three reaches for a regional worker')
    parser.add_argument('--matrix', type=Path)
    parser.add_argument('--ledger-only', action='store_true', help='Reconcile checked batch reach results without scientific rebuild or publication')
    parser.add_argument('--max-new', type=int, default=3)
    parser.add_argument('--batch', default=os.environ.get('SEAFLOOR_BATCH') or os.environ.get('GITHUB_RUN_ID', '')+'-'+os.environ.get('GITHUB_RUN_ATTEMPT', ''))
    args = parser.parse_args()
    if args.stage == 'prepare':
        result = prepare(REPO, args.region, args.reach, args.max_new)
    elif args.stage == 'run':
        result = process(REPO, args.reach, args.batch)
    elif args.stage == 'run-group':
        result = process_group(REPO, args.reaches, args.region, args.batch)
    else:
        result = finish(REPO, read_json(args.matrix), args.batch,
                        region=args.region, ledger_only=args.ledger_only)
    print(json.dumps(result))
    if args.stage == 'run-group' and not result['complete']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
