# Map protection, drift guides and forecast ratings

The September 21 update makes the map useful without opening a target sheet and puts daily and hourly conditions beside the time selector. It does not change the personal forecast monitor's separate, fixed 9/10 rubric.

## Protected areas

Eight local CDFW ds582 MPA polygons are bundled in `dist/data/protected-areas.geojson`, with the retrieval date and exact official query. The app displays them continuously in pink, then requests the official service again at each page load. A failed live read leaves the dated snapshot visibly identified in Map Options. Without a valid boundary dataset, fishing targets are withheld.

All MPAs are excluded from fishing targets regardless of species, including SMCAs that legally allow some fisheries. This implements the user's preference to avoid every MPA; it is not a claim that all fishing is prohibited in every conservation area. Tapping a polygon links to its official CDFW rules. Legal coordinates take precedence over GIS portrayal.

Point and geometry screening includes boundaries, segment crossings, polygon containment and holes. An intersecting fishing outline or proposed drift is withheld as a whole; effort is not redistributed into a clipped commercial cell. Weather samples are regional environmental context, not fishing targets. This is not a complete real-time closure, security-zone or navigation service. The underlying atlas retains its original conservative depth and closure screening.

## Reef footprints and drift

Linked reef footprints and brown structure alignments appear at zoom 13 and above; the selected reef can display at any zoom. Markers remain clustered at wider views.

Blue lines are six-minute, constant-vector **surface-current projections** through visible targets. The hollow circle is a trial setup position three minutes upstream. They update with the map's selected forecast hour, use the nearest requested regional Météo-France/Copernicus sample, and preserve the source's actual populated forecast horizon. The source describes currents as including Eulerian, wave and tidal effects; Port San Luis tide height is never converted into flow. See [the provider's definitions](https://open-meteo.com/en/docs/marine-weather-api).

These are not calibrated boat-drift predictions or anchoring/navigation instructions. The model is about 8 km, local windage and bottom flow are unresolved, and sounder depth must be checked along the proposed drift. A separate gray wind arrow at the selected target shows the forecast's downwind direction; no generic percentage of wind speed is added to the current. [Current-source research](current-data-research.md) explains better regional observations/forecasts and their gaps.

Map Options → Map layers → Drift setup guides also accepts a measured boat speed and course toward true north. Enter a test drift taken at the selected reef: it applies only to that reef, expires after 30 minutes, and is withheld for distant future times or when another reef is selected. Invalid/missing currents, near-zero flow, stale runs and MPA intersections cannot create setup lines. Structure alignments remain distinct from the current-guided projection.

GPX links are enabled only when every included waypoint, footprint and structure line passes the current map's MPA screen. If a refreshed boundary excludes any included geometry, the affected export is withheld, including the complete atlas package. Bundled files remain dated research snapshots; imported files cannot refresh closures themselves.

## Forecast scores and density

Date buttons show X/10 conditions, confidence and provisional status. Future dates use the minimum hourly score over 7 a.m.–1 p.m.; today uses its remaining displayed hours once the morning has passed. A partial morning is labeled and cannot earn 8+. The top banner still ranks only complete future mornings.

The selected hour has its own X/10 score, plus wind/gust/direction, combined sea height/period/direction, NOAA primary and secondary swell, wind chop, Port San Luis tide, modeled surface current, air/sea temperature, visibility/rain and the independent model's wind/sea comparison. Detailed wave/tide charts and sources remain below the compact instruments. Phone layouts use two instrument columns and a horizontally scrolling date strip.

The existing [score formula](species-research.md#morning-ratings) remains a disclosed comfort/gear-control heuristic. It does not estimate fish presence or bite probability. Confidence is separate. Sustained winds and combined seas use both models' rougher values; wave components come from GFS because this ECMWF endpoint does not provide those parts.

A gust below its own model's sustained wind is flagged and omitted. If the other model supplies a valid gust, the numerical estimate can continue using that gust, both sustained winds, Low confidence and a 7.9 maximum. The invalid value remains visible in its source display. If both gusts are inconsistent, critical fields are missing, source runs stale, alerts unavailable, or weather hazards apply, a score is withheld with a reason. This fixes unnecessary blank days without filling missing observations or pretending sources agree. The older qualitative comfort screen remains conservative and can still say Uncertain.

## AIS evidence and sharing

Broad Morro Bay catch-report outlines are removed from the map. Pecho Rock and Diablo are still approximate named vicinities supported by 31 dated reports; exact charter stops remain unknown. The separate optional [commercial AIS layer](commercial-ais-research.md) contains three original statistical cells from sampled 2024 data, with unknown depths and no target-species attribution.

The link-preview image now uses a period-informed Parker 2320 Sport Cabin illustration and stronger contour artwork. See the [image sources and generation notes](social-preview-image-sources.md).

## Validation

Offline checks cover malformed/missing weather, single/both inconsistent gusts, day-window completeness, MPA boundary and crossing cases, upstream/downstream drift geometry and unchanged atlas/export consistency. The published rocky targets, footprints, structure lines and commercial cells were checked against the fresh CDFW polygons. Browser review covers the phone forecast, zoomed map, species filtering and commercial layer controls.
