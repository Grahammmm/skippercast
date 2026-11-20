# Tasks · 07 subsurface depth ladder

- [ ] T0 **Owner confirmation** of scope ("subsea weather") and frame cadence. Stop here until it's answered.
- [ ] T1 Refactor the WCOFS discovery and contract into a shared helper (with spec 05), keeping `wcofs_surface` byte-identical in output (regression test).
- [ ] T2 `wcofs_depth.py` slab read, measure bytes, derive the thermocline and MLD. Synthetic column tests (R1, R2).
- [ ] T3 Publish the layers plus catalog and region bindings, then rebuild the platform output (R3).
- [ ] T4 Client parse, subsurface layer, DepthLadder, salinity layer, `depth` link param (R4, R5).
- [ ] T5 Point-readout profile sparkline (R6).
- [ ] T6 Offline note (R7), strings en+es, docs (`docs/web-app.md`, `docs/data-feed-readme.md`).
- [ ] T7 Full checks plus a performance check on a phone.

## Verification

Record dated bytes per frame and region, timings, and a visual comparison with the surface SST.
