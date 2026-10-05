"""Charter fleet registry and AIS activity (docs/plans/charter-fleet/).

Regions are configuration: everything state-specific lives in
``regions/<STATE>/fleet.json`` and the region-independent rules in
``catalog/fleet/``. Nothing in this package names a state, port or landing.
``config`` loads a region; ``profile`` validates the OSINT agent's boat
profiles (design.md section 8).
"""
