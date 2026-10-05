"""AIS sources (design.md section 10). ``get_source(id)`` builds one by its region-config id."""
from __future__ import annotations

from .aisstream import AisstreamSource
from .base import AisSource, NotConfigured, Unsupported
from .datalastic import DatalasticSource
from .marinecadastre import MarineCadastreSource

__all__ = ["SOURCES", "get_source", "AisSource", "AisstreamSource", "DatalasticSource", "MarineCadastreSource",
           "NotConfigured", "Unsupported"]

SOURCES = {AisstreamSource.id: AisstreamSource, DatalasticSource.id: DatalasticSource,
           MarineCadastreSource.id: MarineCadastreSource}   # MarineCadastre: history only (the backfill)


def get_source(ident: str, **options) -> AisSource:
    """The source registered as ``ident`` (``KeyError`` for an unknown id)."""
    return SOURCES[ident](**options)
