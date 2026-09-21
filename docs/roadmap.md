# Roadmap

This separates shipped functionality from future work. The domain **skippercast.com** is registered by the project owner. The first web app is a static map and forecast-evidence workspace; see [its guide](web-app.md).

## Shipped in the initial research release

- A responsive web map with habitat filters, target notes, reef/drift layers, GPX downloads, and on-demand wind/wave model comparisons.
- A portable, explicit forecast-evidence collector for a documented Morro Bay example.
- Alert lifecycle functions with offline tests.
- A dated public atlas with per-target notes, terrain priorities, reef outlines, optional alignments, and reproducible GPX/GeoJSON/HTML exports.
- Source attribution, licensing boundaries, operating rubric, and documentation for a new reader.

## Next development priorities

1. **Reliable monitoring integration:** durable state and locked outbox, delivery receipts, stable event IDs, scheduler health and missed-run reporting. Keep personal destinations out of the public code.
2. **Configurable regions:** explicit source/station/zone profiles, charted trip routes and travel-time windows, and current regulation checks. A coordinate change alone is insufficient.
3. **Reproducible GIS pipeline:** provider downloads with metadata and checksums, native-grid analysis, closure geometry, and review artifacts. Resolve held data rights before adding the excluded Cambria and charter layers.
4. **Trip planning:** editable boat/trip preferences, charted routes, daylight and fishing-time calculations, private saved trips, and authenticated integration with the collector. The current map and forecast viewer does not calculate a trip or assign a go/no-go score.
5. **Better fishing evidence:** verified charter identities and defensible AIS stop/effort analysis, with coverage limits separated from habitat priority. Do not label sites as charter hotspots without evidence.

Any later commercial offering would require separate rights for the original project material and compliance with each provider's data and service terms.
