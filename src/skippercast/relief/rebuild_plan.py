"""Preview code and style rebuilds without checking or changing stage outputs."""
from collections.abc import Mapping
from pathlib import Path

from skippercast import style
from skippercast.paths import repo_root
from skippercast.relief import receipts as receipt_io, render_config

# scripts/relief/run_region.py STAGES, for ordering independent stages only.
_ORDER = {stage: index for index, stage in enumerate((
    'select', 'mosaic', 'tiles', 'zone', 'digests', 'inventory', 'contours',
    'package', 'shots', 'qa', 'envelope',
))}
_STYLE_GROUPS = ('baked', 'contours', 'habitat')


def _priority(key: str) -> tuple[int, str]:
    return _ORDER.get(key.partition('.')[0], len(_ORDER)), key


def _input_reasons(key, doc, hasher, hashed):
    """``input:<role>`` / ``input-missing:<role>`` for the inputs this receipt recorded."""
    inputs = doc.get('inputs', ())
    if not isinstance(inputs, (list, tuple)):
        raise receipt_io.ReceiptError(f'{key}: malformed input records')
    reasons = set()
    for item in inputs:
        if not isinstance(item, Mapping) or not all(
                isinstance(item.get(field), str) for field in ('path', 'role', 'sha256')):
            raise receipt_io.ReceiptError(f'{key}: malformed input record')
        path = item['path']
        if path not in hashed:  # One shared file is hashed once per plan.
            hashed[path] = hasher(path)
        now = hashed[path]
        if now is None:
            reasons.add(f"input-missing:{item['role']}")
        elif now != item['sha256']:
            reasons.add(f"input:{item['role']}")
    return reasons


def plan(receipts: Mapping[str, Mapping | None], current: Mapping, hasher=None) -> list[dict]:
    """Explain rebuilds for one region, in upstream-first order.

    Use receipt keys (e.g. ``tiles.public``) consistently in both maps. Stages
    named by ``current['stage_digest']`` or by upstream links may lack a receipt.
    An upstream reason names a direct dependency, not every ancestor. This is
    not the runner's done check or permission to rerun a held stage.

    ``hasher(recorded_path)`` returns the file's current sha256, or ``None``
    when it is missing; the caller owns path resolution and all file reads.
    With it, a receipt's recorded inputs (never others) add ``input:<role>``
    on a different hash and ``input-missing:<role>``; without it inputs are
    not examined. Either reason makes the stage rebuild, so each stage that
    links it upstream follows.
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
    hashed = {}
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
            if hasher is not None:
                reasons.extend(_input_reasons(key, doc, hasher, hashed))

        if reasons:
            rebuilds.add(key)
        rows.append({'stage': key, 'action': 'rebuild' if reasons else 'reuse',
                     'reasons': sorted(reasons)})
        decided.add(key)
    return rows


def style_digests(region, *, default=None, pin=None, root=None):
    """Resolve build digests with a proposed pin > saved pin > proposed default."""
    directory = repo_root() / 'style' if root is None else Path(root)
    config = render_config._config(region) or {}
    selected_pin = config.get('style') if pin is None else pin
    if default is not None and selected_pin is not None:
        # A bad proposal is still an error if a pin hides it in this region.
        render_config._select({'style': default}, directory)
    selection = selected_pin if selected_pin is not None else default
    version, _ = render_config._select({} if selection is None else {'style': selection}, directory)
    selected = None if version == render_config.LEGACY else style.load(version, root=directory)
    return {group: selected.digest(group) if selected is not None else None for group in _STYLE_GROUPS}


def simulate_style(region, receipts, *, default=None, pin=None, root=None):
    """Preview a style-only change for one region, leaving code digests unexamined.

    ``pin`` overrides the saved pin for this region only. Like the render
    resolver, ``root`` overrides the style directory, not the region tree.
    """
    styles = style_digests(region, default=default, pin=pin, root=root)
    return plan(receipts, {'stage_digest': {}, 'style': styles})


def load_receipts(out: str | Path, region: str) -> dict[str, dict]:
    """Read the region's stage documents, preserving scoped receipt keys."""
    location = receipt_io.Region(out, region)
    loaded = {}
    for stage, scope in location.keys():
        doc = receipt_io.read_receipt(location.receipt_path(stage, scope))
        if doc is not None:
            loaded[receipt_io.Ref(stage, scope).key] = doc
    return loaded
