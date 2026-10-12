> **Historical archive (copied 2026-10-11, SkipperCast FE-62).** This is `docs/BATHYMETRY-OVERLAY.md` from the retired Fish (SLO Fish Report) repository at commit `68d7b44` (2026-10-06). It records how Fish worked and what was checked at the time, is not maintained, and may describe services, data and claims that no longer exist. SkipperCast's own documentation is the live truth: start at the [archive index](../../README.md) and [front-end design § 15](../../../../plans/front-end/design.md#15-retiring-fish). Links to Fish code, configuration or data that were not archived are shown as plain text, and identifiers that could not be published were redacted.

# Native USGS bottom raster overlay

Built October 1–2, 2026 from the existing, read-only SkipperCast reviewed caches. This completes the native bottom-display export described as the next step in the earlier product research. It is separate from screened fishing habitat and species opportunity layers.

## Delivered asset and map contract

`public/data/slo-bathymetry.json` is the static import manifest. It points to:

`/data/bathymetry/slo-native-v1-947997ecb672cf4f.pmtiles`

The archive is **12,044,691 bytes**, SHA-256 `f4a5910129f96da4a27f7b50f36bf215a1ab17b4959e933345b8ab5ed53447ec`. It contains **1,987 lossless PNG tiles** at zooms 11–16: 7 / 17 / 44 / 121 / 393 / 1,405 tiles respectively. Tile size is 256 pixels. Zoom 16 is approximately 1.95 m per display pixel on this coast, matching the useful spacing of the delivered 2 m source grids. Display overzoom adds no measurements.

The archive's geographic bounding box is `[-121.129741,35.127465,-120.768460,35.545443]`. That is an extent, **not a claim of measured coverage throughout the rectangle**. Only populated source pixels in the admitted depth range are visible; land, gaps, absent surveys and other depths remain transparent. The source footprint primarily covers Point Buchon/Port San Luis through Morro Bay and Point Estero; it does not provide all-county San Simeon/Pismo coverage.

With the existing PMTiles MapLibre protocol:

```ts
const source = {
 type: 'raster',
 url: 'pmtiles://' + location.origin + '/api/bathymetry/tiles',
 tileSize: 256,
 minzoom: manifest.minzoom,
 maxzoom: manifest.maxzoom,
 bounds: manifest.bounds,
 attribution: manifest.attribution,
};
map.addSource('native-bottom', source);
map.addLayer({
 id: 'native-bottom', type: 'raster', source: 'native-bottom',
 paint: {'raster-opacity': 0.85, 'raster-resampling': 'nearest'},
});
```

The MapLibre client uses the same-origin Worker endpoint **`/api/bathymetry/tiles`**, implemented by `src/bathymetry-proxy.ts`. The archive remains a static publication asset, but the local Cloudflare ASSETS binding returned full HTTP 200 bodies when sent a Range header. The endpoint supplies verified byte-range transport instead of relying on that binding behavior.

The proxy accepts only the configured SLO county. On each request it reads the fixed `/data/slo-bathymetry.json` manifest and validates ready/schema/county/raster format, public-domain commercial rights, the exact approved original source identities, immutable local archive path, SHA-256 and size. The archive budget is **16 MiB**, independent of the importer's smaller publication budget. It loads one bounded archive per release, verifies its complete SHA-256 before exposing bytes, and retains at most one archive in the isolate cache; concurrent ranges share that load. Replaced or withdrawn manifests revoke cached access. These are historical physical public-domain measurements, so the fishing habitat's expiring legal-screen gate does not apply to this separate raster.

GET requires a single closed or suffix range of at most **2 MiB**. Missing, open-ended, multiple, unsafe, oversized, unsatisfiable and full-archive ranges are rejected. A valid request receives HTTP 206 with exact `Content-Range`, `Content-Length`, a strong SHA-derived `ETag`, `Accept-Ranges: bytes` and preserved source attribution. `If-Match` uses strong comparison and a changed release returns 412. HEAD validates the manifest and returns archive metadata without loading the archive. Responses use `Cache-Control: no-store`; the isolate's verified byte cache is internal.

Actual local Worker verification completed: `Range: bytes=0-16383` returned **206**, exactly **16,384 bytes**, `Content-Range: bytes 0-16383/12044691`, and `ETag: "sha256-f4a5910129f96da4a27f7b50f36bf215a1ab17b4959e933345b8ab5ed53447ec"`. The installed production `pmtiles` JavaScript reader then fetched the header and native Point Buchon tile `16/10762/25914` through this HTTP endpoint: **8,068-byte PNG**, zoom range 11–16. This establishes local Worker/library transport and decoding, not browser rendering or deployed performance. The initial default-sandbox loopback failure was an access restriction, not evidence that the server was down.

No external CSP origin or account/key is needed for these assets. The file is below Cloudflare's current [25 MiB per-static-asset limit](https://developers.cloudflare.com/workers/platform/limits/).

Display the legend using `colorStops` and the range **0–300 ft · nominal depth**. The colors encode the original producer's depth grid, not species fit. Surface temperature and current layers use their own scales. Maintain visible attribution:

**USGS; CSUMB Seafloor Mapping Lab; University of California Center for Integrated Spatial Research**

Do not call this a navigational chart, probability map, live seabed survey, permitted fishing footprint, or exact fishing-depth rule screen.

## Reviewed original sources

The importer accepts only the three already-reviewed public-domain USGS bathymetry bindings in Fish's approved SkipperCast manifest. Both the original ZIP and the normalized native COG are hashed before reuse. Source URLs, rights, acquisition year, resolution profile, notes and cache receipt COG hash are retained in the new public manifest.

| Source | Original archive SHA-256 | Reused native COG SHA-256 |
| --- | --- | --- |
| [Offshore Morro Bay](https://doi.org/10.5066/P9HEZNRO) | `1f215612bbd0bac0eed8b7738cfc608a8403ebdcb8d1705123e864fd81f24aed` | `c57549d62416903fc2e24bf04cc9aaeb185d29aa43ce96723edcab07529c2eee` |
| [Offshore Point Buchon](https://doi.org/10.5066/P9KBGELE) | `c825293fc999ad757b32ee2acefcae590690d451d12fd367b2f8b3e9e6d731d4` | `216b8bdb5bf8683ffbef6e940cd5289decf777b7112f42dab41fc836a69389ea` |
| [Offshore Point Estero](https://doi.org/10.5066/P9ZSTUK1) | `43244d9ca2e61f6c4154bd50c9ec05286b1d01772e1354fc247f905176e8d37a` | `4faf6272e251771bc46a0c3404e9209a99351b4a242d8df4254ae660fa0d7d7a` |

Each normalized COG is EPSG:32610 with 2×2 m cells and no averaged overviews. These are USGS-produced reviewed releases whose explicit source decision is `public-domain-us-gov` / `allowed-public-domain`. The attribution includes collaborating institutions; that does not convert these USGS releases into the excluded standalone CSUMB commercial-restricted data. No Big Sur–San Simeon restricted grid or unreviewed regional raster is imported.

The original archives and COG cache live under the selected SkipperCast checkout's `var/seafloor/cache/{originalArchiveSha}/`. The importer reads that checkout without editing it. If several receipt variants exist, it deterministically selects the verified variant with the largest valid requested-window pixel count, then validates its exact COG bytes. No source archive or large raw depth file is copied into Fish.

## Rendering method and limits

1. Read positive-down nominal depth and the native source mask.
2. Reproject using **nearest source sampling** to Web Mercator display pixels. No new bilinear interpolation, smoothing, wet-cell extrapolation or averaging of different surveys is added.
3. Admit only finite source depth greater than zero and at most 91.44 m (300 ft). A zero depth is withheld. All other values map to palette index zero, explicitly transparent.
4. Where producer footprints overlap, preserve a deterministic first-source precedence (Morro, Buchon, Estero), without averaging unknown-datum depths. The method does not compute slope across a source seam.
5. Encode a fixed depth-color scale into 85 visual bins (about 3.6 ft each). Three light levels provide subtle relief from native same-source finite differences. These are display encodings, not an exact pixel-depth-query API.
6. Withhold terrain lighting at source gaps, survey seams, raster edges, and the Point Buchon/Estero ≥80 m zones where the producer supplied 5 m data resampled into the delivered 2 m grid. Those deeper values still display nominal depth color; they are not advertised as 2 m detail.
7. Write lossless PNG tiles into a PMTiles v3 archive with small gzip-compressed leaf directories and an immutable configuration-derived filename.

**Unknown vertical datum and quantitative uncertainty stay unknown.** Native cell spacing does not establish positioning accuracy or rock dimensions. The original producer's separate interpolation mask is unavailable; a valid raster cell is original producer-gridded support, not necessarily an independent measured sounding. The importer adds no interpolation but cannot remove the producer's undocumented interpolation. Historical survey evidence is not a recent bottom-change measurement.

The visual depth gate is **nominal**, so it cannot establish exact 300 ft legal clearance. Protected-water bathymetry can be useful physical context; this layer is not spatially screened fishing habitat. Keep MPAs/restrictions visible and require the separate reviewed species, date, method and whole-habitat screens before recommending a fishing target. It supplies no fish occurrence or catch probability.

## Repeatable import and tests

From Fish, use the existing SkipperCast GIS Python (rasterio, numpy and Pillow), for example:

```sh
../skippercast-seafloor-rollout/.venv/bin/python scripts/import-bathymetry.py \
  --skipper-root ../skippercast-seafloor-rollout
../skippercast-seafloor-rollout/.venv/bin/python tests/bathymetry.test.py
node --test tests/bathymetry.test.mjs
node --import tsx --test tests/bathymetry-proxy.test.ts
```

The importer does not download data. It validates approved producer rights, archive identity, COG identity/native resolution, nodata provenance and the bounded county footprint. The configured maximum archive size defaults to 15 MB. A budget failure does not publish a new manifest. The `--limit-tiles N` diagnostic option never publishes a manifest.

Intermediate PNGs and zero-coverage receipts are saved under ignored `artifacts/bathymetry-display/{configHash}/`. The hash includes the importer itself, approved source records, COG hashes, zooms and color scale. A resumed run verifies every cached populated tile's checksum before use. Source/method changes therefore create a separate cache generation; tile files and final manifest use atomic replacement. The previous immutable archive remains available until an explicitly authorized cleanup. A new county requires approved regional source bindings and output naming; it does not silently reuse SLO's coverage or hashes.

Verification completed:

- Five scientific tests cover exact nominal range/nodata transparency, missing-neighbor and cross-survey relief rejection, withholding fine relief in the producer's coarser zone, rights failure before cache access, and lossless palette transparency.
- The installed production JavaScript PMTiles reader parses the actual generated archive/header/metadata and retrieves native PNG tiles from all three survey areas.
- The archive's byte length and SHA-256 match the manifest, native tile size/type/transparency are checked, and an absent tile returns undefined.
- Eight proxy tests cover the real publication archive, strict range and HEAD/If-Match semantics, concurrent cache loading, release withdrawal/replacement, exact source/rights/path gates, and checksum/body/status failure before any tile bytes are returned.
- The actual local Worker and production JavaScript PMTiles reader passed the HTTP range/header/PNG checks described above. TypeScript checks passed after the proxy integration.
- Actual sample images were viewed: Morro's selected deeper flat terrain is correspondingly flat, a partial Estero footprint has transparent gaps, and a Buchon sample contains real local relief. No decorative contours or rocks were added to make a flat source look more interesting.

Browser acceptance remains part of parent integration: rendered layer ordering, visible legend/attribution, mobile frame performance, and source/permission distinctions. Live browser visual QA was blocked by the available browser administration policy and has not been performed; no visual-quality assurance is implied by the transport tests.
