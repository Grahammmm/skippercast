# Location-aware targets and rules

The map uses the selected spot or area while its details are open and preserves that choice when opening its forecast. Returning to the map or panning resumes following the map center. A short caption always identifies the controlling location. Changing species does not move the map.

`dist/location-context.js` resolves the point against the **published fishing footprints**, choosing the smallest matching footprint when packages overlap. Entering another package reloads the complete regional app with the same coordinates, zoom and preferred target. This also replaces captured forecast points, feeds, protected-area queries and legal registry; changing only a global region variable would leave those stale.

The separately configured `discovery_bounds` retain offshore forecasts and search references beyond the reviewed fishing footprint. Only offshore targets appear there, and local legal clearance stays unknown; broader data coverage never expands approved rules.

Target relevance and legal status are separate. Closed-season targets remain available for future-date planning. Southern California omits Dungeness from its researched target list, and island contexts omit bay-specific spotted sand bass. Neither omission declares a blanket legal prohibition. In particular, Point Conception's groundfish boundary is distinct from the Point Arguello crab trap/snare restriction.

Each regional `map` configuration supplies:

- `local_areas`: named discovery extents with nearby `notice_ids` and optional `hidden_targets` containing a reason and evidence URL.
- `region_notice_ids`: notices relevant everywhere, such as health advice.
- `unavailable_targets`: explanations for a preferred target that cannot transfer to this package.

These extents prioritize relevant information; they are **not legal closure polygons**. All other regional access notices remain accessible in the rules card. The authoritative MPA and groundfish-exclusion screen checks the selected point or entire selected geometry separately. An intersecting protected area receives an exclusion badge, never a seasonal open badge. Missing or stale boundary checks withhold local clearance. Areas crossing reviewed coverage, exact package edges, and unsupported locations receive an explicit coverage warning instead of neighboring rules.

For another geography, add the reviewed species list and legal registry through the existing regional pipeline, then add discovery extents and notice bindings. The regional build rejects unknown or unbound notices, duplicate local IDs, and hidden targets without an evidence URL. `python -m skippercast.platform.build` compiles the routing footprints into the region directory. No separate scheduled job is needed: the existing daily regulatory and protected-area updates supply freshness to this same screen.

Validation: `tests/test_location_context.mjs` covers region transitions, overlapping packages, unsupported gaps, target filtering, nearby notices, geometry crossing coverage, protected areas, stale checks, and handoff URL validation. Browser checks cover actual map movement, selected features and mobile controls.

The UI provides regional planning guidance. It does not claim a species is present at the map center or that a season badge authorizes an exact fishing operation. Local depth lines, trip-wide possession rules, time-dependent access and current operational clearance still require the linked official rules.
