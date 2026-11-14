# Trinidad–Klamath basemap detail (R4-SC-12)

The current extract settings already select all active and preview regions from
`regions/*/region.json`. Trinidad–Klamath is preview, with the detail box
`[-124.6, 40.95, -124.0, 41.55]` (west, south, east, north). Keep zooms **11–14**
inside that box, alongside the other 15 selected region boxes; overview zooms
remain 0–10. Six draft subregions are contained by the broad Southern California
box, so 16 extract boxes cover all 22 region packages. The check reports the
containing box for each package without changing any draft status.
No region status, fishing bounds or publication pointer needs changing.

## Check without downloading or publishing

```sh
python3 scripts/basemap/check_detail.py
```

This lists each region and ends with `22 of 22 regions inside a detail box`.
It verifies extract **settings**, not tile contents or the currently live archive.
A stale published archive is not repaired merely by passing this check.

For an operator's saved extraction plan:

```sh
python3 scripts/basemap/check_detail.py --dir var/basemap
```

This checks `plan.json` and `detail.geojson` against current region bounds,
rejecting missing regions (including Trinidad), changed boxes, duplicates,
inconsistent geometry and incorrect zooms. The existing builder runs this check
after writing the plan and before extraction or replacing a local archive.

## Operator handoff and rollback

Use the existing dispatch-only `.github/workflows/basemap.yml` procedure on main
when the operator is ready. This PR does not dispatch it, download a source,
build an archive or upload anything. Review the saved plan and run the check
above before publishing. The workflow's existing archive verification and
HTTP Range read-back still apply; settings coverage is not a substitute for them.

Keep the current published archive and manifest until a replacement is verified.
If preparation fails, leave those unchanged. If a later operator publication
needs rollback, restore the prior manifest pointer to its retained immutable
archive using the existing publication procedure. Reverting this PR removes only
the new pre-extraction check; it does not alter any published data.
