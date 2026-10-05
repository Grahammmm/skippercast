"""Registry of fleet source adapters (design section 6).

``REGISTRY`` maps each adapter id a ``fleet.json`` binding may name to its
implementation. Ids are registered before their adapter exists (value ``None``)
so region files validate now; CF-12 to CF-16 and the AIS tasks fill in the
classes. ``config.ADAPTERS`` is this registry's key set.
"""
from __future__ import annotations

from typing import Mapping

from .base import Adapter, Candidate, Fact, RunContext
from .directories import Directories
from .teck_reports import TeckReports

__all__ = ["ADAPTERS", "REGISTRY", "Adapter", "Candidate", "Fact", "RunContext", "get"]

REGISTRY: Mapping[str, type | None] = {
    "fcc-uls": None,        # CF-12
    "uscg-psix": None,      # CF-12
    "teck-reports": TeckReports,
    "directories": Directories,
    "landing-pages": None,  # CF-14
    "operator-site": None,  # CF-16
    "google-places": None,  # CF-16
    "file-import": None,    # CF-16
    "ais-static": None,     # AIS tasks (section 11)
}
ADAPTERS = frozenset(REGISTRY)


def get(ident: str) -> type:
    """The adapter class for ``ident``; KeyError if unknown, NotImplementedError if not built yet."""
    adapter = REGISTRY[ident]
    if adapter is None:
        raise NotImplementedError(f"adapter {ident!r} is registered but not implemented yet")
    return adapter
