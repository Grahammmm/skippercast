"""AIS activity for the charter fleet (design.md sections 10 and 11).

``sources`` defines the ``AisSource`` interface, the normalised ``AisPosition``
and ``AisStatic`` records and the provider adapters (aisstream; Datalastic as a
stub). ``store`` is the raw day-file store under ``$SKIPPERCAST_FLEET_VAR`` with
its retention. ``segment`` splits one vessel's positions into trips and
``classify`` labels each trip's segments (pure functions over positions);
``events`` turns fishing segments into events and ``simplify`` encodes segment
geometry; ``aggregate`` bins events into map cells through pluggable modules.
``listener`` is the always-on service (``python -m skippercast.fleet.ais listen
--region CA``) with its ``watch`` list and standard-library WebSocket client
``ws``; ``process`` is the scheduled processor job that pushes derived rows to
the Worker; the backfill builds on these in a later task. Raw positions never
enter D1 or git.
"""
from .sources.base import AisMessage, AisPosition, AisSource, AisStatic, NotConfigured, Unsupported
from .store import AisStore, RetentionLimits, fleet_var, retention_limits

__all__ = ["AisMessage", "AisPosition", "AisSource", "AisStatic", "AisStore", "NotConfigured", "RetentionLimits",
           "Unsupported", "fleet_var", "retention_limits"]
