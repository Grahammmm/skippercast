"""Registry of fleet source adapters (design section 6).

``REGISTRY`` maps each adapter id a ``fleet.json`` binding may name to its
implementation. Ids are registered before their adapter exists (value ``None``)
so region files validate now; CF-12 to CF-16 and the AIS tasks fill in the
classes. A value may be ``"module:Class"`` (relative to this package), imported
on first use: adapters that fetch import ``fleet.net``, which imports
``fleet.config``, which imports this registry, so they cannot be imported here.
``config.ADAPTERS`` is this registry's key set.
"""
from __future__ import annotations

from importlib import import_module
from typing import Mapping

from .base import Adapter, Candidate, Departure, Fact, Offering, RunContext
from .directories import Directories
from .fcc_uls import FccUls
from .landing_pages import LandingPages
from .teck_reports import TeckReports
from .uscg_psix import UscgPsix

__all__ = ["ADAPTERS", "REGISTRY", "Adapter", "Candidate", "Departure", "Fact", "Offering", "RunContext", "get"]

REGISTRY: Mapping[str, type | str | None] = {
    "fcc-uls": FccUls,
    "uscg-psix": UscgPsix,
    "teck-reports": TeckReports,
    "directories": Directories,
    "landing-pages": LandingPages,
    "operator-site": "operator_site:OperatorSite",
    "google-places": "google_places:GooglePlaces",
    "file-import": "file_import:FileImport",
    "ais-static": None,     # AIS tasks (section 11)
}
ADAPTERS = frozenset(REGISTRY)


def get(ident: str) -> type:
    """The adapter class for ``ident``; KeyError if unknown, NotImplementedError if not built yet."""
    adapter = REGISTRY[ident]
    if adapter is None:
        raise NotImplementedError(f"adapter {ident!r} is registered but not implemented yet")
    if isinstance(adapter, str):
        module, _, name = adapter.partition(":")
        return getattr(import_module(f"{__name__}.{module}"), name)
    return adapter
