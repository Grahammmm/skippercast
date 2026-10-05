"""AIS sources (design.md section 10). ``get_source(id)`` builds one by its region-config id."""
from __future__ import annotations

from .aisstream import AisstreamSource
from .base import AisSource, NotConfigured, Unsupported
from .datalastic import DatalasticSource

__all__ = ["SOURCES", "get_source", "AisSource", "AisstreamSource", "DatalasticSource", "NotConfigured", "Unsupported"]

# MarineCadastre (history only) joins in CF-47.
SOURCES = {AisstreamSource.id: AisstreamSource, DatalasticSource.id: DatalasticSource}


def get_source(ident: str, **options) -> AisSource:
    """The source registered as ``ident`` (``KeyError`` for an unknown id)."""
    return SOURCES[ident](**options)
