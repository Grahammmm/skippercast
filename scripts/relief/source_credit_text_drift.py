"""Compare credit text in two explicit, in-memory Sources register snapshots.

The caller supplies the reviewed IDs; this does not decide which rows may be
published or check a page, a region, or the freshness of either snapshot.
"""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from scripts import build_sources_register as register


@dataclass(frozen=True)
class CreditText:
    name: str
    provider: str
    attribution: str | None
    supplemental_credit: str | None


@dataclass(frozen=True)
class CreditFinding:
    source_id: str
    before: CreditText | None
    after: CreditText | None


def _credits(snapshot: dict, reviewed: set[str]) -> dict[str, CreditText]:
    result = {}
    for row in snapshot['sources']:
        source_id = row['id']
        if source_id not in reviewed:
            continue
        if source_id in result:
            raise ValueError(f'duplicate reviewed source ID: {source_id!r}')
        # Mirror the catalogue branch of the generator's _entry, without
        # rendering it. The agency label and the supplemental credit are not
        # substitutes for the source's own (verbatim) attribution.
        result[source_id] = CreditText(
            row['name'], row['provider'], (row.get('rights') or {}).get('attribution') or None,
            register.CSUMB_CREDIT if register.is_csumb(row) else None,
        )
    return result


def compare(before: dict, after: dict, reviewed_ids: Iterable[str]) -> tuple[CreditFinding, ...]:
    """Report changed or missing credit by exact ID, sorted by ID.

    Each snapshot uses the catalogue's ``sources`` list shape. An absent row
    is None; an existing row without attribution has attribution=None. Missing
    credit remains visible even when it was already missing in both snapshots.
    Equal, complete credits are omitted. Supplemental credit describes the
    row's contribution if shown, not whether the page displays it.
    """
    reviewed = set(reviewed_ids)
    old, new = _credits(before, reviewed), _credits(after, reviewed)
    findings = []
    for source_id in sorted(reviewed):
        left, right = old.get(source_id), new.get(source_id)
        if left != right or left is None or left.attribution is None:
            findings.append(CreditFinding(source_id, left, right))
    return tuple(findings)
