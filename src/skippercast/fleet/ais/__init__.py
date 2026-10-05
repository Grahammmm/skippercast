"""AIS activity for the charter fleet (design.md sections 10 and 11).

``sources`` defines the ``AisSource`` interface, the normalised ``AisPosition``
and ``AisStatic`` records and the provider adapters (aisstream; Datalastic as a
stub). ``store`` is the raw day-file store under ``$SKIPPERCAST_FLEET_VAR`` with
its retention. The listener, processor and backfill build on these in later
tasks. Raw positions never enter D1 or git.
"""
from .sources.base import AisMessage, AisPosition, AisSource, AisStatic, NotConfigured, Unsupported
from .store import AisStore, RetentionLimits, fleet_var, retention_limits

__all__ = ["AisMessage", "AisPosition", "AisSource", "AisStatic", "AisStore", "NotConfigured", "RetentionLimits",
           "Unsupported", "fleet_var", "retention_limits"]
