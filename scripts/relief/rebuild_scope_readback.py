"""Compare explicit stage identities with a saved plan accepted by the scope check.

Readback describes identity changes, not what ran or why an identity changed.
It does not discover receipts, execute stages or grant approval.
"""

from skippercast.relief.receipts import HEX64

from .rebuild_scope_check import _allowed_pairs, _check, summarize


def _identities(snapshot):
    if not isinstance(snapshot, dict) or any(
        not isinstance(region, str) or not isinstance(stages, dict)
        for region, stages in snapshot.items()
    ):
        raise ValueError('expected a region-to-stage identity mapping')
    pairs = _allowed_pairs({region: list(stages) for region, stages in snapshot.items()})
    identities = {}
    for region, stage in sorted(pairs):
        digest = snapshot[region][stage]
        if digest is not None and (not isinstance(digest, str) or not HEX64.fullmatch(digest)):
            raise ValueError(f'{region}: {stage}: expected a SHA-256 digest or None')
        identities[region, stage] = digest
    return identities


def compare(plan, ceiling, expected_regions, expected_stages, *, before, after):
    """Read back a saved plan against two in-memory region -> stage -> digest maps.

    Each snapshot must cover every plan pair and both must cover the same pairs.
    Use None for explicitly absent identities, not missing observations. Supply
    additional observed pairs in both snapshots to detect changes outside the plan.
    The independent roster and inventory have the scope checker's semantics.
    """
    expected_regions = tuple(expected_regions)
    review = _check(plan, ceiling, expected_regions, expected_stages)
    if not review['within_ceiling']:
        raise ValueError(f'readback requires a plan within the review ceiling: {review}')

    planned = {(region, row['stage']): row for region, rows in
               summarize(plan, expected_regions)['regions'].items() for row in rows}
    allowed = _allowed_pairs(ceiling)
    old, new = _identities(before), _identities(after)
    if old.keys() != new.keys() or not planned.keys() <= old.keys():
        raise ValueError('snapshots must cover the same pairs and include every plan pair')

    report = {'observed_planned': [], 'unexpected_observed': [], 'planned_unobserved': []}
    for region, stage in sorted(old):
        pair = region, stage
        row = planned.get(pair)
        rebuild = row is not None and row['action'] == 'rebuild'
        entry = {'region': region, 'stage': stage, 'before': old[pair], 'after': new[pair]}
        if old[pair] == new[pair]:
            if rebuild:
                report['planned_unobserved'].append(entry)
        elif rebuild:
            report['observed_planned'].append(entry)
        else:
            report['unexpected_observed'].append({
                **entry, 'outside_ceiling': pair not in allowed,
                'planned_action': row['action'] if row is not None else None,
            })
    return report
