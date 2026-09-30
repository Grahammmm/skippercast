# Ranked reef day plans

In **Export**, select **Best available** to choose up to 20 distinct measured
reef habitat candidates in the selected region. The default plan contains
waypoints and complete reef outlines only. Change the target, limit, nominal
depth (up to 300 ft), map extent and port distance under **Trip filters**.
The default port radius is 20 nautical miles; this is a straight-line reference,
not a navigable route or fuel-range calculation. A new default plan uses the
coming Friday. Keep or change its date before checking conditions.

## Priority, habitat fit and confidence

- **#1–20** is priority within this filtered selection.
- **H3** is the strongest physical habitat fit, **H2** good, **H1** secondary.
  Lingcod + rockfish uses the weaker of the two species fits. The best-set
  selector includes H2/H3 only, fine-resolution surveys (4 m or finer), and an
  evidence index of at least 60%. It returns fewer spots when fewer qualify.
- **C85%** means 85 points on the versioned habitat evidence index. It is not a
  calibrated probability of fish presence, catching fish or safe navigation.
- **A/B/C** remains the terrain grade; it describes ruggedness, not fish abundance.

The title `01 LR H3 C85% 90-120ft` places the priority, species, habitat fit and
confidence near the beginning for plotters that shorten labels. LR means the
combined target, LC lingcod, RF rockfish. The depth range describes the whole
reef's nominal survey depths; its waypoint is an interior reference point,
not a separately sampled point depth. Corresponding outline tracks carry the
same title followed by `reef`.

`habitat-evidence-v1` awards:

| Evidence | Maximum points |
| --- | ---: |
| Reviewed original survey identity | 25 |
| Valid terrain metric support fraction | 25 × fraction |
| Native resolution ≤4 m (≤16 m earns 10) | 20 |
| Interpreted substrate coverage fraction | 20 × fraction |
| Known survey year | 5 |
| Documented independent substrate support | 5 |

Unknown or absent interpolation masks cap the total at 90%. Terrain grade,
species fit and repeated copies of the same survey do not raise confidence.
Missing survey identity, resolution or metric support yields no percentage
and excludes the candidate from this preset. This is a transparent initial
rubric, not a statistical uncertainty model; survey datum and positional
limitations still apply. The substrate layer is interpreted habitat evidence,
not another independent depth measurement.

The selector sorts species fit first, evidence index second, terrain score
third, then stable ID. It avoids shared reef IDs and reference points within
0.15 nm of an already selected reef. On a small screen, nearby priorities
group behind the strongest priority with a `+N` badge; tap to zoom in. All
selected reefs remain in the export. Unchecking a spot retains it in the
candidate list for reconsideration.

## Publication and validation process

1. The existing native-survey pipeline measures terrain, applies the versioned
   species rules and screens **full** habitat polygons against spatial restrictions.
2. Regional publication writes `habitat-export.geojson.gz` from those canonical
   polygons, including holes and separate parts. An interior reference point
   is generated without inventing a sampled waypoint depth. PMTiles remain
   display-only and are never the export geometry.
3. The regional manifest records the canonical file's SHA-256, byte length and
   screening expiry. Publication verifies R2 read-back before making the stable
   manifest ready. The Worker refuses stale, held or mismatched export bytes.
4. The browser loads only the chosen region when requested (32 MiB compressed,
   128 MiB decoded maximum), verifies compressed bytes before bounded gzip
   decoding, retains every original coordinate,
   verifies shape, interior points and provenance, then applies filters
   and the current protected-area screen to both points and entire reefs.
5. Saved plans contain IDs, priorities, species and publication hash, not cached
   geometry. Reopening verifies the current publication before restoration. A
   changed publication requires selection again; it cannot silently replace
   a saved reef or its title.
6. Download repeats publication and whole-reef screening, including when outlines
   are turned off. Expired screening blocks export. Ranked map geometry rechecks
   local expiry and protected areas every minute and checks the live manifest;
   stale geometry is withheld.

Weather is separate from fixed habitat rank. **Check trip conditions** applies
the plan's species, first selected reef and date to the forecast. The conditions
button on an individual ranked reef applies that reef and the same plan date.
These are nearby model forecasts, not routed trip clearance. The selected date
does not grant future regulatory clearance; recheck rules and conditions before
departure. No AIS hotspot or catch probability is inferred by this preset.

## Release and chartplotter checks

This feature requires the client/Worker release and a subsequent regional
seafloor publication with the canonical export. Old manifests display an explicit
"awaiting the next seafloor publication" message. The existing daily seafloor
workflow regenerates this contract for every published region; changing its
publisher also triggers that workflow on main. No separate export pipeline or
per-region scoring code is required.

The offline tests use synthetic geometry and verify complete outlines, hashes,
expiry, current exclusions, ranking and deduplication. Phone and laptop browser
tests exercise selection, saved-plan restoration, rechecking a deselected spot,
map interaction and the actual downloaded GPX.

Import a small set into your device first. GPX labels and track segments vary
by plotter. Twenty outline tracks exceed some devices' total track capacity;
the export screen reports track and vertex counts and links device instructions.
In iNavX, share the GPX to the app and enable imported waypoints and tracks.
