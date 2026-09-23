# Coastal regions and seasonal species

The masthead's **Region** selector covers the California outer coast using CDFW's five ocean/groundfish regions: Northern, Mendocino, San Francisco, Central and Southern. These are browsing groups, not the legal boundary system for every species. Bay rules, salmon management zones, groundfish depth lines, state waters and federal waters still need their own evaluation.

The guide also exposes 19 smaller [discovery sectors](statewide-buildout.md). They let a visitor zoom to a local stretch and see dated NOAA survey-catalog leads. They are not precise fishing areas; qualifying an original survey and local rules is a separate step.

`catalog/coasts.json` owns the latitude boundaries, display extent, species order, seasonal candidates and official references. `platform/coasts.py` validates and compiles it to `dist/data/coasts.json`. Shared `dist/coasts.js` owns URLs, selection and source freshness. A regional species label can be overridden without changing the biological species or its legal limits: the Southern reef selector reads **Rockfish**, while lingcod remains a separate regulated species in the underlying evidence.

## Browsing versus detailed coverage

The statewide directory does not create fishing spots. Northern, Mendocino and San Francisco initially open the shared coastal guide, with potential targets, source links and CDFW MPAs. Central opens the Morro Bay–Avila fishing map. Its full-coast overview remains available in Options, with links to the Morro Bay–Avila and Cambria–San Simeon data packages. Zooming into a mapped area at level 9 or closer loads that package automatically. Southern opens its existing detailed package. **Options → Mapped area** lets a visitor move between a coastal overview and detailed maps.

Changing coast clears the previous spot, focus and incompatible target. Panning beyond a detailed package opens the appropriate coastal guide when its browsing extent covers the point. Crossing a coastal boundary updates the guide and species. Uncovered coasts never inherit Morro Bay forecasts, ratings, tide stations, legal-open badges or exported waypoints. Survey-qualified targets remain governed by the regional contracts and MPA geometry screen.

## Daily source flow

The existing **Daily fishing evidence** workflow now runs one additional shared collector:

```sh
PYTHONPATH=src python -m skippercast.pipeline.coastal_watch \
  --output var/daily --previous-root var/published --report-root var/daily
```

It checks the five official CDFW regional summary pages, NOAA CPC's ENSO discussion and the statewide CDFW MPA service. It compares the MPA feature count against the complete geometry response and rejects truncation. Requests retain source URL, HTTP status, content hash and retrieval time. CDFW source-update dates and NOAA advisory dates stay separate from retrieval clocks. On macOS a CDFW certificate-chain failure can recover through system curl with normal TLS verification, a fixed URL allowlist, no redirects and bounded downloads. TLS is never disabled.

The workflow atomically publishes `coastal/latest.json` (including boundaries) and `coastal/status.json` (small status/species feed) on GitHub's `data` branch. It reports missing or degraded sources as failures after preserving the status. Existing scheduled jobs are reused. A saved website fallback retains its source dates; reading it does not refresh the source. Source checks expire after 36 hours and ENSO discussions after 45 days. Document hashes flag changes without approving new fishing regulations automatically.

### New seasonal targets

Reviewed baseline species remain stable. A NOAA El Niño advisory adds climate context, never a catch location. Seasonal candidates may join **coastal guide** selectors only when the daily collector has at least two distinct reviewed original publishers and two observation dates within 14 days, with reviewed fishing coordinates inside the coastal extent. Repeated or syndicated reports share their original publisher identity. Stale, future, unlocated, port-only and neighboring-region records cannot promote a candidate.

Required normalized observation fields are `date`, WGS84 `coordinates: [longitude, latitude]`, `coordinate_role: "fishing-observation"`, `location_review: "reviewed"`, `source_url`, `original_publisher_id`, `publisher_review: "reviewed"`, and `catches` with canonical species IDs and positive counts. The current imported port reports do not satisfy this location contract. The watch therefore remains a watch until suitable evidence arrives; it does not manufacture new positions.

Promotion is a report flag, not a probability, verified hotspot, open season, or permission to transfer another area's habitat. Publishing detailed maps for that target still requires the normal biological, source-coverage and regulatory review. Native SST, ocean color and currents remain in the existing habitat-dynamics pipeline and preserve their real coverage and timestamps.

## Adding coverage

1. Extend the reviewed target matrix and cite local biological evidence. Use the existing data-discovery skill for providers with different geographic coverage.
2. Add location-bearing report adapters with reviewed original-publisher identities; keep missing coordinates missing.
3. For detailed spots, follow `docs/regions.md` to create a full regional package with surveys, species evidence, local weather bindings, official rules and closures.
4. Bind the new package in the coastal directory; rebuild, test boundaries and URL handoffs, then run the daily collector against live sources.

The fishing basemap uses NOAA groups 0, 1, 2 and 6: chart display, coastal features, depths and navigation aids. Cables/seabed symbols, traffic and extra chart-area markings are omitted by default. Full NOAA restores those symbols. CDFW MPAs and imported groundfish exclusion areas are independent, always-visible layers. Context polygons become more detailed as the visitor zooms; drift alignments are optional.

## Validation for this release

On September 22, 2026, all seven source jobs completed successfully; the MPA service returned 155 features. NOAA's advisory was dated September 10. CDFW summary dates ranged from August 10 to September 11. These dates are source receipts, not universal legal or fishing clearance.

Tests cover boundary membership, target overrides, geographic isolation, old URL cleanup, source aging, publisher/date/location evidence requirements and chart-layer selection. Browser-based mobile visual review was unavailable because the browser tool could not verify its administrator-enforced policy. No alternate browser automation was used to bypass that restriction.

Panning performance: MPA shapes are reused, point screening rejects nonoverlapping bounds before scanning vertices, and full-geometry results are cached only for the current closure revision. Protected-area refresh starts before optional habitat downloads. Overview habitat badges count screened source polygons and zoom to their outlines; they are not fishing waypoints. A reef coverage prompt links to matching grounds outside the current viewport.
