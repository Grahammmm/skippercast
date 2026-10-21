"""Bounded 1..4-source admission population for synthetic sign-off integration.

Uses the current real catalog bridge producer, not the old multi-cell-grid shape.
Larger population sampling stays in the shared sampler tests; current bridge
MAX_JOBS=4 does not admit a fictitious sixteen-window single plan.
"""
from copy import deepcopy
from pathlib import Path

from tests.coast_real_admission_factory import refs, sampling
from tests import _coastal_catalog_fixture as fx
from skippercast.coastal.coordinator import catalog_bridge as bridge
from skippercast.coastal.coordinator.stages import digest


def expand(admission, bindings, count):
    if not 1 <= count <= bridge.MAX_JOBS:
        raise ValueError('current native bridge admits only 1..4 sources')
    queue = Path(bindings['queue:synthetic'])
    result = deepcopy(admission)
    if count == 1:
        return result
    def put(path, value):
        raw = value if isinstance(value, bytes) else refs.canonical(value)
        target = queue / path
        target.parent.mkdir(parents=True, exist_ok=True)
        refs.write_once(target, value) if not isinstance(value, bytes) else target.write_bytes(raw)
        return dict(root_id='queue:synthetic', path=path, sha256=refs.sha256(raw), bytes=len(raw))
    record = refs.loads((queue / admission['segment_record']['path']).read_bytes())
    old_plan = refs.loads((queue / admission['plan_file']['path']).read_bytes())
    old_campaign = refs.loads((queue / admission['campaign']['path']).read_bytes())
    selection = old_plan['selections'][0]
    template = admission['windows'][0]
    rows, selections, sources, grids, windows = [], [], [], [], []
    for i in range(count):
        name = f'population-{i}.bag'
        source = fx.cache_file(queue, 'cache/' + name, data=f'Synthetic non-raster sign-off input {i}\n'.encode())
        row = fx.candidate(name, size=source['bytes'], source_hash=source['sha256'])
        rows.append(row)
        selections.append(dict(deepcopy(selection), source_id=row['source_id'], source=source))
        definition = dict(admission['grids'][0]['definition'], source_sha256=source['sha256'])
        grid_sha = digest(definition)
        grids.append(dict(source_id=row['source_id'], grid_sha256=grid_sha, definition=definition, cols=1, rows=1, total=1))
        key = sampling.window_key(row['source_id'], grid_sha, 0)
        windows.append(dict(deepcopy(template), source_id=row['source_id'], grid_sha256=grid_sha, idx=0, window_key=key, window_dir=sampling.window_dir(key)))
        raw_root = Path(bindings['raw:campaign'])
        (raw_root / name).write_bytes((queue / source['path']).read_bytes())
        hot = dict(root_id='queue:synthetic', **{k: source[k] for k in ('path', 'sha256', 'bytes')})
        sources.append(dict(admission['sources'][0], source_id=row['source_id'], hot_cache=[hot],
                            raw_provenance=[dict(hot, root_id='raw:campaign', path=name)]))
    catalog = fx.frozen_catalog(rows)
    catalog_ref = put('population/catalog.json', catalog)
    plan = dict(old_plan, catalog_id=catalog['catalog_id'], catalog_sha256=catalog_ref['sha256'], selections=selections)
    plan_ref = put('population/plan.json', plan)
    dry = queue / 'population/dry'
    bridge.dry_run(queue, queue / catalog_ref['path'], plan, dry, now=1792540800)
    dry_path = dry / 'bridge-dry-run-receipt.json'
    raw = dry_path.read_bytes()
    dry_ref = dict(root_id='queue:synthetic', path=dry_path.relative_to(queue).as_posix(), sha256=refs.sha256(raw), bytes=len(raw))
    campaign = dict(old_campaign, source_inventory=[r['source_id'] for r in rows], intended_windows=[w['window_key'] for w in windows])
    campaign_ref = put('population/campaign.json', campaign)
    discovery = refs.loads((queue / admission['discovery']['path']).read_bytes())
    discovery_ref = put('population/discovery.json', dict(discovery, catalog=catalog_ref))
    result.update(plan_file=plan_ref, catalog=catalog_ref, campaign=campaign_ref, discovery=discovery_ref,
                  dry_run=dry_ref, plan_sha256=digest(plan), sources=sources, grids=grids, windows=windows,
                  would_enqueue_count=count, selected_source_ids=[r['source_id'] for r in rows])
    return result
