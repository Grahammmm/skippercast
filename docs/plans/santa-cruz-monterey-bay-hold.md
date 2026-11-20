# Santa Cruz-Monterey Bay: held habitat, per-reach hold report

Checked 2026-11-16 (PST) against main `d1eb2eb`. Report only: this file changes no manifest, ledger, `region.json` or status, and releases no reach. Replying to a question built from it does nothing by itself; releasing a held reach is a human security-zone review and a separate change.

## Count

The screening manifest lives in the feed, not the repo. Held reaches are counted from its ledger:

```text
curl -s -o ledger.json https://skippercast.com/feeds/tiles/seafloor/regions/santa-cruz-monterey-bay/ledger.json
jq '[.reaches[] | select(.status=="habitat-held-for-screen")] | length' ledger.json
```

Result at check time: **3** (r11, r12, r13). The published manifest
(`/feeds/tiles/seafloor/manifest-santa-cruz-monterey-bay.json`) reads `status: "held"` and lists the same three in `reach_inputs`. The other ten reaches are `unassessed`, not held, and are not listed here. The ledger changes on each publish; re-run the command before asking.

## Why all three are held

Each reach carries `held_by_reason: {"screen-scope-unreviewed": N}`. The whole-polygon screen only passes reaches named in its reviewed scope, and these three are not: `src/skippercast/seafloor/screen.py:78` (`if reach_id not in data['reviewed_reaches']:`) appends the reason at `screen.py:79`. A held manifest makes the app withhold the layer: `dist/seafloor-data.js:28` (`if (manifest.status === 'held') ...`). Region-level effect: SC-D1=B (`node scripts/check_region_promotion.mjs santa-cruz-monterey-bay` prints the habitat GAP).

## What a reviewer must look at (every reach)

- The screen scope in the ledger: polygon latitude 34.4 to 36.62, longitude -122.1 to -120.45, `whole-polygon-screen-v1`, snapshot `c8600024b5766f6e...` (2026-11-17 UTC).
- Whether the reach's candidate polygons are covered by all three screen layers, each `status: ok`: `cdfw-mpa` (155 features), `noaa-federal` (29), `security` (3, eCFR 33 CFR 165.1155 and related sections; 334.1150 is classified outside-reviewed-scope).
- That no candidate polygon overlaps an MPA, federal closure area or security zone, and that the reach's input hash below is the one reviewed.

## Held reaches

### santa-cruz-monterey-bay-r11
- Hold reason: `screen-scope-unreviewed` (10 candidate polygons held, 0 published habitat)
- Source: `src/skippercast/seafloor/screen.py:78`
- Reviewer looks at: the 10 candidates against the three layers above
- Reach input hash: `4790b6b7224078a3ee8db36eeabcf353774c4bb9c108fca95c83ba1e67314a9a`
- Replies: `APPROVE REACH` / `KEEP HELD`

### santa-cruz-monterey-bay-r12
- Hold reason: `screen-scope-unreviewed` (67 candidate polygons held, 0 published habitat)
- Source: `src/skippercast/seafloor/screen.py:78`
- Reviewer looks at: the 67 candidates against the three layers above
- Reach input hash: `63cff02afeb99ba57c2501436bf02ece5eb1c1f4db2588db1f9717330871b569` (manifest `reach_inputs`)
- Replies: `APPROVE REACH` / `KEEP HELD`

### santa-cruz-monterey-bay-r13
- Hold reason: `screen-scope-unreviewed` (313 candidate polygons held, 0 published habitat)
- Source: `src/skippercast/seafloor/screen.py:78`
- Reviewer looks at: the 313 candidates against the three layers above
- Reach input hash: `612b6db944851316afc1ac289dcbb0822de649abe6860e99f81753514a707bb7`
- Replies: `APPROVE REACH` / `KEEP HELD`

## Replies

`APPROVE REACH` means the human review found the reach clear and asks for a separate change adding it to the reviewed scope. `KEEP HELD` (also the default if there is no reply) leaves it held. Nothing is sent, published, deployed or approved by this report.
