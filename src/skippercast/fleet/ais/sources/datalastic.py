"""Datalastic: a paid AIS API kept as a stub until the owner decides to pay (design.md sections 10 and 19).

Every call raises ``NotConfigured``. Implementing it is a new paid service, which
needs the owner's authorization (AGENTS.md); until then the region's
``ais.source`` stays ``aisstream``.
"""
from __future__ import annotations

from typing import Iterator

from .base import AisMessage, Bbox, NotConfigured

__all__ = ["SOURCE_ID", "DatalasticSource"]

SOURCE_ID = "datalastic"
_WHY = "the datalastic source is a stub: it needs a paid plan the owner has not approved"


class DatalasticSource:
    id = SOURCE_ID
    realtime = True

    def __init__(self, *args, **kwargs):
        pass

    async def stream(self, bbox: Bbox, mmsis: set[int] | None = None):
        raise NotConfigured(_WHY)
        yield  # pragma: no cover  (makes this an async generator)

    def history(self, day, bbox: Bbox, mmsis: set[int] | None = None) -> Iterator[AisMessage]:
        raise NotConfigured(_WHY)
