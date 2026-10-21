"""Freeze a one-owner bridge plan and the complete generated lattice record."""
import re
from admit_common import (absolute, bridge, check_stage, cli, context, directory_fd, ensure_dir,
                          file_ref, freeze, geometry, read_json)


def make_plan(*, root, campaign, catalog, selection, cache_receipt, out_dir):
    """Refuse multi-owner selections and unsupported PC-6 shapes before writing."""
    camp, sel, queue, queue_id = context(campaign, selection)
    if absolute(root) != queue:
        raise ValueError('root must be the campaign queue, never a per-plan Store')
    if file_ref(catalog, queue_id, queue) != sel['catalog']:
        raise ValueError('catalog differs from pinned selection')
    stage = check_stage(read_json(cache_receipt), camp, sel)
    record, grids, windows = geometry(camp, sel, stage, queue)
    plan = dict(schema=bridge.PLAN, catalog_id=read_json(catalog)['catalog_id'],
                catalog_sha256=sel['catalog']['sha256'],
                segment={k: record[k] for k in ('segment_id', 'bbox_crs84')},
                synthetic=False, max_total_bytes=sel['max_total_bytes'], budget=sel['budget'], selections=[])
    for w, s in zip(sel['windows'], stage['sources']):
        source = {k: s['hot_cache'][k] for k in ('path', 'sha256', 'bytes')}
        source['contract'] = w['reader']
        plan['selections'].append(dict(source_id=w['source_id'], source=source,
                                       window=w['pixel_window'], vertical=w['vertical'], rights=w['rights']))
    bridge.check_catalog(read_json(catalog))
    bridge.check_plan(plan, absolute(catalog).read_bytes(), read_json(catalog))
    # Do not drop held/unknown candidates: evaluate returns them; admission keeps
    # those windows even when dry-run would_enqueue is empty.
    bridge.evaluate(queue, catalog, plan)
    out_dir = absolute(out_dir)
    if out_dir.parent != queue/'plans' or not re.fullmatch('[A-Za-z0-9_-]+', out_dir.name):
        raise ValueError('plan output must be C/plans/<safe-plan-id>')
    ensure_dir(out_dir.parent)
    with directory_fd(out_dir.parent):
        out_dir.mkdir(mode=0o700)  # existing directory refuses, including partial attempts
    freeze(out_dir/'plan.json', plan)
    freeze(out_dir/'segment.json', record)
    chosen = {w['window_key'] for w in windows}
    return dict(plan_id=out_dir.name, coordinator_segment_id=record['segment_id'],
                window_keys=sorted(chosen), remaining_inventory=sorted(set(camp['intended_windows'])-chosen),
                grids=grids, review_required=True)


if __name__ == '__main__':
    cli(make_plan, ('root', 'campaign', 'catalog', 'selection', 'cache-receipt', 'out-dir'))
