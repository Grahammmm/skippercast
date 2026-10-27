# SP1704: a closed trip counts its observed return leg

Card SP1704-TRIP-RETURN-DISTANCE, spec SP-17-v1. Product change: `src/skippercast/fleet/ais/segment.py` only.

## Behavior

`split_trips` closes a trip at the return fix: the first fix of a stay inside a harbor geofence that is held for `in_port_debounce_min`. `Trip.positions` stop before that fix, as before. Until this change `Trip.distance_nm` summed only the legs between `positions`, so a closed trip lost its final observed leg, the run from the last fix at sea into port.

Now a `closed` trip (known departure port, confirmed return) also counts the leg from its last position to the return fix. Nothing else moves:

- `positions`, `departed_at`, `returned_at`, statuses, ports and `max_offshore_nm` are unchanged. The return fix lies inside a geofence, so it would add nothing to the offshore distance anyway.
- Open trips, trips truncated by a long silence, trips truncated by age, and trips whose positions begin at sea (truncated with an unknown start, even when the return is held) keep the sum of their recorded legs. The card corrects only the closed-trip distance (A4).
- A dip into port shorter than the debounce, or data that ends inside before the debounce, is still not a return: those fixes stay trip positions, and their legs count exactly as before.
- Harbor travel before the departure fix and after the return fix is not counted.
- `classify` reads `positions` and `returned_at`, not `distance_nm`, so segmentation and the classifier version stay the same. `process` publishes `round(trip.distance_nm, 3)`, so closed trips in that output gain their return leg.

## Evidence

The `tests/unit/test_sp1704_trip_return_distance.py` tests use synthetic tracks from `tests/fixtures/sp1704_trip_return_distance/tracks.json`, with the committed `regions/CA/fleet.json` thresholds and the real `split_trips` and `classify_trip`. `expected.json` pins what the unchanged base produced for every field the repair must not move.

`scripts/accept_sp1704_trip_return_distance.py --phase baseline|focused|regression|repository --output DIR` writes a new receipt directory below `DIR` each time it runs:

- `baseline` stages the sources with the base `segment.py` and requires the frozen primary regression to fail on its `SP1704_RETURN_LEG_OMITTED` assertion while the healthy control passes.
- `focused` runs A1-A4.
- `regression` runs the unchanged `tests.unit.test_fleet_classify`.
- `repository` runs the unchanged `scripts/check_repository.py` with the staged scanner interpreter.

A pass from any phase still needs review. It is not full-repository CI, and it is not semantic acceptance.
