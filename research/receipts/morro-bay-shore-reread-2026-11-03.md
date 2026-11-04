# Morro Bay shore re-read dossier (SC1952-07, M1a)

**Acquisition evidence only.** This is not the M1b owner re-read. It renews no review window, confirms no register row and approves no fishing legality or access. `REVIEWS`, the register, the catalog and `dist/` are untouched.

- Receipt: `research/receipts/morro-bay-shore-reread-2026-11-03.json` (check with `python3 scripts/check_shore_reread_dossier.py <receipt>`).
- File name date is the handover path fixed by the spec; the sources were actually fetched 2026-11-04T08:26:37.775Z to 2026-11-04T08:26:57.563Z UTC.
- Inspected Git SHA: `fdde26c7d36c55ac6f0d6567020909f7389231be`.
- Baselines: committed package `catalog/shore-habitat/morro-bay.geojson` (acquisitions 2026-10-08) and archived review `docs/archive/fish/repo/research/shore-source-review-2026-10-03.json` (acquisitions 2026-10-03). They are different baselines; their terms hashes differ and are not merged.

## Sources

| Source | Host | Fetched (UTC) | HTTP | Bytes | SHA-256 (raw) | Raw vs baselines |
| --- | --- | --- | --- | --- | --- | --- |
| noaa | services2.arcgis.com | 2026-11-04T08:26:37.775Z | 200 | 1080079 | `79b803306dc128f304948f8751e964ccc6ac605da13830d8e88a538d13348298` | bytes-differ |
| access | services9.arcgis.com | 2026-11-04T08:26:38.645Z | 200 | 325083 | `4925eff242f1c841d8035ccbefe851b0251e75063e39826f02cd1031d17cacc3` | bytes-identical |
| terms | www.arcgis.com | 2026-11-04T08:26:38.814Z | 200 | 4576 | `e7fafa620aac73d8a21ba894605e37f68399b2d1f40cff763c6bba7586d3b62d` | bytes-differ |
| cdfwRules | wildlife.ca.gov | 2026-11-04T08:26:57.011Z | 200 | 87866 | `7bd3c3506c862e5c9fba756014c3dd4aa1372d001724a517adaa19871392d597` | bytes-differ |
| noaaLayerMetadata | services2.arcgis.com | 2026-11-04T08:26:57.563Z | 200 | 28308 | `f7a2c9d4587e9cef1a7b1b3ccd4f21d9837135a97359a7b909f9a4bf19b6631d` | no-baseline |

- **noaa**: Full-response bytes differ from both committed baselines while the byte count is equal (1080079). The raw bytes of the baselines were not retained, so the cause cannot be established; a changed full response does not by itself change any selected run.
- **access**: Full-response bytes equal the committed and archived raw hash, so every inventory field in the response is unchanged since both baselines.
- **terms**: Item JSON bytes differ from both baselines with an equal byte count (4576); the item carries time-varying fields (modified, numViews, lastViewed). Baseline bytes were not retained, so the changed field is not identified. The licenseInfo text is compared separately.
- **cdfwRules**: Page bytes differ (87812 -> 87866); no historical HTML was retained, so this is a byte change only and no line diff is claimed. Facts are compared in the rules section.
- **noaaLayerMetadata**: No committed baseline for the layer definition; used only to name ESI codes.

Raw hashes are response-byte hashes, not normalized hashes. The archived normalized subset hashes (`3bc3362c...`, `c6ba562b...`) could not be reproduced with common serializations, so they are not compared. A changed full response does not establish a changed selected run: for all five runs the selected object classes and retained vertices are unchanged below.

## Runs (5)

| Run | Objects | Object class | Full-feature geometry | Retained vertices | Access | Legal |
| --- | --- | --- | --- | --- | --- | --- |
| hearst-memorial-beach | 2094, 2100 | unchanged | unchanged | unchanged (91 vertices, 2 paths) | unchanged | changed |
| morro-strand | 2294 | unchanged | unchanged | unchanged (137 vertices, 1 paths) | unchanged | changed |
| cayucos-beach | 2283, 2287, 2289 | unchanged | unchanged | unchanged (115 vertices, 3 paths) | unchanged | changed |
| pismo-beach | 2632, 2636, 2637 | unchanged | unchanged | unchanged (150 vertices, 3 paths) | unchanged | changed |
| oceano-beach | 2638 | unchanged | unchanged | unchanged (107 vertices, 1 paths) | unchanged | changed |

Archived `priorGeometrySha256`: hearst-memorial-beach unverifiable; morro-strand unchanged; cayucos-beach unchanged; pismo-beach unchanged; oceano-beach unchanged. Hearst has no archived entry, so its prior-hash finding is unverifiable. The Legal column is "changed" only because the rules page publisher date moved (2026-10-01 to 2026-11-02); the species facts compared are unchanged (see CDFW section).

## Access points (8)

| Point | Run | Name | Public | Type | Archived | Closure | Coordinates | Published point |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| ccc-770 | hearst-memorial-beach | unchanged | unchanged | unchanged | unchanged | date unchanged, comment unchanged | unchanged | unchanged |
| ccc-804 | morro-strand | unchanged | unchanged | unchanged | unchanged | date unchanged, comment unchanged | unchanged | unchanged |
| ccc-805 | morro-strand | unchanged | unchanged | unchanged | unchanged | date unchanged, comment unchanged | unchanged | unchanged |
| ccc-797 | cayucos-beach | unchanged | unchanged | unchanged | unchanged | date unchanged, comment unchanged | unchanged | unchanged |
| ccc-798 | cayucos-beach | unchanged | unchanged | unchanged | unchanged | date unchanged, comment unchanged | unchanged | unchanged |
| ccc-868 | pismo-beach | unchanged | unchanged | unchanged | unchanged | date unchanged, comment unchanged | unchanged | unchanged |
| ccc-870 | pismo-beach | unchanged | unchanged | unchanged | unchanged | date unchanged, comment unchanged | unchanged | unchanged |
| ccc-875 | oceano-beach | unchanged | unchanged | unchanged | unchanged | date unchanged, comment unchanged | unchanged | unchanged |

Closure fields are inventory evidence only, not opening certification. The raw access response is byte-identical to both baselines. Old, new and published values for each field are in the JSON receipt (`accessPoints[].fields`).

## Terms (CCC item e45f130ce101423ea1de943a69445ece)

- Item owner `cdenney_coastalcomm`, org `wwVnNW92ZHUIr0V0`: a portal pointer, not a rights confirmation.
- Raw item bytes: changed. Observed time-varying fields: modified 2026-07-29T21:27:58Z, lastViewed 2026-11-04T07:00:00Z, numViews 91210.
- `licenseInfo` text: **unchanged** (committed accessTerms and archive vs current, markup stripped).

## CDFW Central rules

- **publisherDate**: changed. Page text "updated on <date>" vs archived legalFacts.publisherUpdatedDate.
- **surfperch**: unchanged. Section "Surfperch": season, combined and per-species bag, shiner perch limit, redtail minimum size.
- **californiaHalibut**: unchanged. Section "California Halibut": season, bag south of Point Sur, minimum length.
- **licenseScope**: unverifiable. The archived licenseScope and licenseNote came from https://wildlife.ca.gov/Licensing/Fishing, which this card does not fetch; the Central page has no licence-requirement text to compare.
- **rawPage**: changed. Page bytes differ from the archived receipt (87812 -> 87866 bytes). No historical HTML was retained, so this is a byte change only; no line diff is claimed.

## M2 candidates: CCC 792 to 795

| Point | Name | Coordinates | Public | Type | Archived | Closure |
| --- | --- | --- | --- | --- | --- | --- |
| ccc-792 | Estero Bluffs State Park (West) | [-120.951406748599, 35.4537928380511] | Yes | Beach Access | blank | blank / blank |
| ccc-793 | Estero Bluffs State Park | [-120.942191745917, 35.4503498387185] | Yes | Beach Access | blank | blank / blank |
| ccc-794 | Estero Bluffs State Park (San Geronimo Rd.) | [-120.932671744641, 35.4498258386032] | Yes | Beach Access | blank | blank / blank |
| ccc-795 | Estero Bluffs State Park (East) | [-120.925836743272, 35.4491088396811] | Yes | Beach Access | blank | blank / blank |

Estero Bluffs selection: **unresolved**. The fetched NOAA layer lists original objects around the four access points (below), mostly 1A/2A rocky and 5 mixed sand and gravel classes with composite codes; this card does not choose a run, bounds or substrate rule. Choosing among them needs the M2 schema decision and owner review, and an automatic nearest-shore join is not allowed.

- Site selection limits: unverifiable. Owner URL: unverifiable (none in the fetched sources). SC1952-08 selection held.
- 45 NOAA objects listed (listing rule: Every layer object with any vertex inside the access points bounding box padded by 0.02 degrees; a listing, not a selection.). Legend names are from the layer definition.

| Object | ESI | Legend | Vertices | Lon range | Lat range |
| --- | --- | --- | --- | --- | --- |
| 2234 | 2A | 2A: 2A-Exposed wave-cut platforms in bedrock | 15 | -120.9712 to -120.9705 | 35.4596 to 35.4598 |
| 2236 | 6A/2A | 6A: 6A-Gravel beaches; 2A: 2A-Exposed wave-cut platforms in bedrock | 27 | -120.9720 to -120.9712 | 35.4595 to 35.4598 |
| 2241 | 4 | 4: 4-Coarse-grained sand | 66 | -120.9705 to -120.9659 | 35.4584 to 35.4602 |
| 2242 | 2A | 2A: 2A-Exposed wave-cut platforms in bedrock | 28 | -120.9660 to -120.9651 | 35.4577 to 35.4584 |
| 2243 | 4 | 4: 4-Coarse-grained sand | 26 | -120.9651 to -120.9645 | 35.4572 to 35.4578 |
| 2244 | 2A | 2A: 2A-Exposed wave-cut platforms in bedrock | 12 | -120.9645 to -120.9641 | 35.4567 to 35.4572 |
| 2245 | 5/2A | 5: 5-Mixed sand & gravel; 2A: 2A-Exposed wave-cut platforms in bedrock | 17 | -120.9641 to -120.9633 | 35.4561 to 35.4567 |
| 2246 | 2A | 2A: 2A-Exposed wave-cut platforms in bedrock | 12 | -120.9633 to -120.9627 | 35.4560 to 35.4562 |
| 2247 | 4 | 4: 4-Coarse-grained sand | 22 | -120.9627 to -120.9611 | 35.4560 to 35.4564 |
| 2248 | 5/2A | 5: 5-Mixed sand & gravel; 2A: 2A-Exposed wave-cut platforms in bedrock | 16 | -120.9611 to -120.9605 | 35.4551 to 35.4560 |
| 2249 | 5/2A | 5: 5-Mixed sand & gravel; 2A: 2A-Exposed wave-cut platforms in bedrock | 16 | -120.9599 to -120.9589 | 35.4548 to 35.4549 |
| 2250 | 2A | 2A: 2A-Exposed wave-cut platforms in bedrock | 13 | -120.9605 to -120.9599 | 35.4548 to 35.4551 |
| 2251 | 2A | 2A: 2A-Exposed wave-cut platforms in bedrock | 17 | -120.9589 to -120.9586 | 35.4547 to 35.4549 |
| 2252 | 5/2A | 5: 5-Mixed sand & gravel; 2A: 2A-Exposed wave-cut platforms in bedrock | 35 | -120.9586 to -120.9565 | 35.4538 to 35.4550 |
| 2253 | 2A | 2A: 2A-Exposed wave-cut platforms in bedrock | 90 | -120.9565 to -120.9526 | 35.4525 to 35.4538 |
| 2254 | 4 | 4: 4-Coarse-grained sand | 40 | -120.9526 to -120.9513 | 35.4514 to 35.4525 |
| 2255 | 1A | 1A: 1A-Exposed rocky shores | 20 | -120.9516 to -120.9512 | 35.4509 to 35.4514 |
| 2256 | 5 | 5: 5-Mixed sand & gravel | 22 | -120.9514 to -120.9511 | 35.4496 to 35.4509 |
| 2257 | 6B/2A | 6B: 6B-Riprap; 2A: 2A-Exposed wave-cut platforms in bedrock | 7 | -120.9154 to -120.9152 | 35.4494 to 35.4495 |
| 2258 | 6A/2A | 6A: 6A-Gravel beaches; 2A: 2A-Exposed wave-cut platforms in bedrock | 29 | -120.9152 to -120.9140 | 35.4491 to 35.4496 |
| 2259 | 2A | 2A: 2A-Exposed wave-cut platforms in bedrock | 45 | -120.9520 to -120.9512 | 35.4490 to 35.4496 |
| 2260 | 2A | 2A: 2A-Exposed wave-cut platforms in bedrock | 25 | -120.9140 to -120.9136 | 35.4488 to 35.4491 |
| 2261 | 6B/3A | 6B: 6B-Riprap; 3A: 3A-Fine- to medium-grained sand beaches | 31 | -120.9094 to -120.9082 | 35.4488 to 35.4492 |
| 2262 | 3A | 3A: 3A-Fine- to medium-grained sand beaches | 20 | -120.9082 to -120.9066 | 35.4487 to 35.4491 |
| 2263 | 1B | 1B: 1B-Exposed, solid man-made structures | 23 | -120.9136 to -120.9132 | 35.4487 to 35.4492 |
| 2264 | 3A | 3A: 3A-Fine- to medium-grained sand beaches | 2 | -120.9066 to -120.9064 | 35.4486 to 35.4487 |
| 2265 | 3A | 3A: 3A-Fine- to medium-grained sand beaches | 2 | -120.9064 to -120.9063 | 35.4486 to 35.4486 |
| 2266 | 1A | 1A: 1A-Exposed rocky shores | 9 | -120.9133 to -120.9126 | 35.4484 to 35.4487 |
| 2267 | 5/2A | 5: 5-Mixed sand & gravel; 2A: 2A-Exposed wave-cut platforms in bedrock | 15 | -120.9512 to -120.9510 | 35.4484 to 35.4490 |
| 2268 | 6B/2A | 6B: 6B-Riprap; 2A: 2A-Exposed wave-cut platforms in bedrock | 24 | -120.9102 to -120.9094 | 35.4483 to 35.4488 |
| 2269 | 2A | 2A: 2A-Exposed wave-cut platforms in bedrock | 49 | -120.9126 to -120.9101 | 35.4480 to 35.4484 |
| 2270 | 5 | 5: 5-Mixed sand & gravel | 19 | -120.9306 to -120.9293 | 35.4479 to 35.4481 |
| 2271 | 5/2A | 5: 5-Mixed sand & gravel; 2A: 2A-Exposed wave-cut platforms in bedrock | 70 | -120.9250 to -120.9218 | 35.4475 to 35.4479 |
| 2272 | 5/2A | 5: 5-Mixed sand & gravel; 2A: 2A-Exposed wave-cut platforms in bedrock | 64 | -120.9339 to -120.9306 | 35.4475 to 35.4479 |
| 2273 | 5 | 5: 5-Mixed sand & gravel | 31 | -120.9347 to -120.9339 | 35.4475 to 35.4479 |
| 2274 | 2A | 2A: 2A-Exposed wave-cut platforms in bedrock | 49 | -120.9511 to -120.9486 | 35.4475 to 35.4484 |
| 2275 | 5/2A | 5: 5-Mixed sand & gravel; 2A: 2A-Exposed wave-cut platforms in bedrock | 56 | -120.9293 to -120.9254 | 35.4474 to 35.4479 |
| 2276 | 2A | 2A: 2A-Exposed wave-cut platforms in bedrock | 15 | -120.9254 to -120.9250 | 35.4473 to 35.4476 |
| 2277 | 2A | 2A: 2A-Exposed wave-cut platforms in bedrock | 162 | -120.9218 to -120.9154 | 35.4471 to 35.4494 |
| 2278 | 5/2A | 5: 5-Mixed sand & gravel; 2A: 2A-Exposed wave-cut platforms in bedrock | 80 | -120.9486 to -120.9419 | 35.4467 to 35.4477 |
| 2279 | 1B | 1B: 1B-Exposed, solid man-made structures | 2 | -120.9077 to -120.9063 | 35.4466 to 35.4486 |
| 2280 | 4/2A | 4: 4-Coarse-grained sand; 2A: 2A-Exposed wave-cut platforms in bedrock | 43 | -120.9420 to -120.9411 | 35.4466 to 35.4474 |
| 2281 | 5/2A | 5: 5-Mixed sand & gravel; 2A: 2A-Exposed wave-cut platforms in bedrock | 118 | -120.9400 to -120.9347 | 35.4462 to 35.4478 |
| 2282 | 5/2A | 5: 5-Mixed sand & gravel; 2A: 2A-Exposed wave-cut platforms in bedrock | 31 | -120.9411 to -120.9400 | 35.4461 to 35.4466 |
| 2283 | 3A | 3A: 3A-Fine- to medium-grained sand beaches | 42 | -120.9063 to -120.9019 | 35.4459 to 35.4486 |

## Private files and handover

Raw responses hold the full inventory and stay under `var/shore-review/SC1952-07/` (ignored, never committed). To verify copies in another clone, compare each file below by `sha256sum`:

- `var/shore-review/SC1952-07/candidate.geojson` 36464 bytes `d7b40d7fe319a738e931ac6e8eaebf0b3d09de3693fe144525baa4f076c1f80a`
- `var/shore-review/SC1952-07/collector.stderr` 0 bytes `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`
- `var/shore-review/SC1952-07/collector.stdout` 68 bytes `8bc7ff41f4e56da686740c6798ec0643e647b1a4c076e6222b1341ba1859261d`
- `var/shore-review/SC1952-07/fetch_pages.py` 2006 bytes `f7a66f6f32692edce436d77145fdc390a80c2b0f71f684f694946cc6b528b05e`
- `var/shore-review/SC1952-07/pages/cdfw-central-rules.html` 87866 bytes `7bd3c3506c862e5c9fba756014c3dd4aa1372d001724a517adaa19871392d597`
- `var/shore-review/SC1952-07/pages/noaa-layer3-metadata.json` 28308 bytes `f7a2c9d4587e9cef1a7b1b3ccd4f21d9837135a97359a7b909f9a4bf19b6631d`
- `var/shore-review/SC1952-07/pages/pages-receipts.json` 909 bytes `9cdf92dac903f74f821bf249ada45cd0975c5c0158a80ae90b95bb38683ad6ef`
- `var/shore-review/SC1952-07/sources/ccc-access-item.json` 4576 bytes `e7fafa620aac73d8a21ba894605e37f68399b2d1f40cff763c6bba7586d3b62d`
- `var/shore-review/SC1952-07/sources/ccc-access-points.json` 325083 bytes `4925eff242f1c841d8035ccbefe851b0251e75063e39826f02cd1031d17cacc3`
- `var/shore-review/SC1952-07/sources/noaa-esi-shoreline.json` 1080079 bytes `79b803306dc128f304948f8751e964ccc6ac605da13830d8e88a538d13348298`
- `var/shore-review/SC1952-07/sources/receipts.json` 1115 bytes `f39898c181847e929c5aa18817685b77c34455dc5ad835817c86647455c30d05`

## Holds

- M1b owner re-read and M1c review dates remain owner work; no REVIEWS or register edit.
- Closure fields are inventory evidence, not opening certification.
- Acquisition does not approve current fishing legality.
- Raw hash changes (NOAA, terms, CDFW page) are byte changes only; baselines were not retained.
- M2 Estero Bluffs selection unresolved; SC1952-08 selection held.

## Appendix: bounded page acquisition script (private)

```python
"""Bounded official-page acquisition for SC1952-07 (private, var/ only).

Fetches exactly: the CDFW Central URL (wildlife.ca.gov) and the NOAA layer metadata
(same services2.arcgis.com host as the collector's NOAA source). Refuses off-host
redirects, caps size and time, records URL/final URL/status/UTC time/bytes/SHA256.
"""
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent
PAGES = ROOT / 'pages'
MAX = 8_000_000
JOBS = {
    'cdfw-central-rules': ('https://wildlife.ca.gov/Fishing/Ocean/Regulations/Fishing-Map/Central', 'cdfw-central-rules.html'),
    'noaa-layer3-metadata': ('https://services2.arcgis.com/C8EMgrsFcRFL6LrL/arcgis/rest/services/Central_California_ESI_2006_test/FeatureServer/3?f=json', 'noaa-layer3-metadata.json'),
}
out = {}
for key, (url, name) in JOBS.items():
    rec = {'url': url}
    try:
        req = Request(url, headers={'User-Agent': 'SkipperCast shore import'})
        with urlopen(req, timeout=60) as r:
            final = r.geturl()
            status = r.status
            body = r.read(MAX + 1)
        rec.update(finalUrl=final, status=status)
        if urlsplit(final).netloc != urlsplit(url).netloc:
            rec['failure'] = 'off-host redirect'
        elif len(body) > MAX:
            rec['failure'] = 'oversized'
        else:
            (PAGES / name).write_bytes(body)
            rec.update(file='pages/' + name, bytes=len(body), sha256=hashlib.sha256(body).hexdigest(),
                       fetchedAt=datetime.now(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z'))
    except Exception as e:  # noqa: BLE001 - recorded as an explicit per-source failure
        rec['failure'] = type(e).__name__ + ': ' + str(e)
    out[key] = rec
(PAGES / 'pages-receipts.json').write_text(json.dumps(out, indent=1) + '\n')
print(json.dumps(out, indent=1))
sys.exit(0)
```
