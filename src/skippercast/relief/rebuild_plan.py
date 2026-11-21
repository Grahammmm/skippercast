"""Preview code and style rebuilds without checking or changing stage outputs."""
from collections.abc import Mapping
from pathlib import Path

from skippercast.relief import receipts as receipt_io

# scripts/relief/run_region.py STAGES, for ordering independent stages only.
_ORDER = {stage: index for index, stage in enumerate((
    'select', 'mosaic', 'tiles', 'zone', 'digests', 'inventory', 'contours',
    'package', 'shots', 'qa', 'envelope',
))}
_STYLE_GROUPS = ('baked', 'contours', 'habitat')


def _priority(key: str) -> tuple[int, str]:
    return _ORDER.get(key.partition('.')[0], len(_ORDER)), key


def plan(receipts: Mapping[str, Mapping | None], current: Mapping) -> list[dict]:
    """Explain rebuilds for one region, in upstream-first order.

    Use receipt keys (e.g. ``tiles.public``) consistently in both maps. Stages
    named by ``current['stage_digest']`` or by upstream links may lack a receipt.
    An upstream reason names a direct dependency, not every ancestor. This is
    not the runner's done check or permission to rerun a held stage.
    """
    digests = current['stage_digest']
    style = current['style']
    needs = {
        key: {receipt_io.Ref(link['stage'], link.get('scope')).key
              for link in (doc or {}).get('upstream', ())}
        for key, doc in receipts.items()
    }
    for key in digests.keys() | set().union(*needs.values()):
        needs.setdefault(key, set())

    rows = []
    decided = set()
    rebuilds = set()
    while needs:
        ready = (key for key, deps in needs.items() if deps <= decided)
        key = min(ready, key=_priority, default=None)
        if key is None:
            raise receipt_io.ReceiptError('cycle in rebuild plan upstream links')

        reasons = [f'upstream:{dep}' for dep in needs.pop(key) & rebuilds]
        doc = receipts.get(key)
        if doc is None:
            reasons.append('missing')
        else:
            status = doc.get('status')
            if status in ('failed', 'held'):
                reasons.append(f'status:{status}')
            if key in digests and doc.get('code', {}).get('stage_digest') != digests[key]:
                reasons.append('code')
            params = doc.get('params', {})
            for group in _STYLE_GROUPS:
                if group in params and params[group] != style[group]:
                    reasons.append(f'style:{group}')

        if reasons:
            rebuilds.add(key)
        rows.append({'stage': key, 'action': 'rebuild' if reasons else 'reuse',
                     'reasons': sorted(reasons)})
        decided.add(key)
    return rows


def load_receipts(out: str | Path, region: str) -> dict[str, dict]:
    """Read the region's stage documents, preserving scoped receipt keys."""
    location = receipt_io.Region(out, region)
    loaded = {}
    for stage, scope in location.keys():
        doc = receipt_io.read_receipt(location.receipt_path(stage, scope))
        if doc is not None:
            loaded[receipt_io.Ref(stage, scope).key] = doc
    return loaded
