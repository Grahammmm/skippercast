# Southern California island habitat release

The Channel Islands layer combines actual mapped footprints with explicit gaps. It does not draw a ring around an island and call it a fishing ground. The released shapes are habitat **context**, not validated catches, charter stops or navigation targets. The user's 200-foot limit is retained. Native bathymetric values support a conservative depth screen where available; an unnamed common vertical datum and missing per-cell uncertainty prevent certification of fishing targets or exports.

## Imported primary sources

| Product | What is actually imported | Date and detail | Constraints |
| --- | --- | --- | --- |
| [NOAA NCCOS/NCEI 0304093](https://doi.org/10.25921/2ees-dq97) | Northern Channel Islands and Santa Barbara Island numerical bathymetry, separate 2 m (roughly 0–40 m) and 4 m (roughly 36–80 m) grids | Surveys 1998–2022-11-05; compilation completed 2024-01-31; archive published 2025-05-30 | Merged acoustic measurements, including published IDW gap interpolation and linear vertical shifts. No per-cell uncertainty or named common vertical datum. CC0 is explicit in the archive ISO document. |
| [NOAA NCCOS California substrate](https://www.fisheries.noaa.gov/inport/item/39578) | The original hard/soft multipart shapefile; geometry intersected with reviewed island extents and measured-source depth masks | January 2006 compilation; original surveys vary; native spatial resolution not specified | Publisher says it is not field validated and fine-scale errors may occur. No mixed-substrate, boulder-size or live-habitat claims are created. NOAA/NCCOS, MLML, MMS and UCSB attribution retained. |
| [CDFW California Kelp 2016](https://filelib.wildlife.ca.gov/Public/R7_MR/BIOLOGICAL/Kelp/BIO_CA_Kelp2016.zip) | Native canopy and subsurface polygon classifications, retaining both source codes | Aerial observations September 3–25, 2016; 2 m classification derived from 0.3 m imagery; published May 2017 | Historical kelp, not live canopy. Detection depends on timing, ocean conditions, photo quality and coverage. CDFW and Sandoval & Associates attribution required and provided. |

The bathymetry is available from the [public NCEI archive](https://www.ncei.noaa.gov/data/oceans/archive/arc0237/0304093/1.1/data/0-data/). Its [ISO metadata](https://www.ncei.noaa.gov/data/oceans/archive/arc0237/0304093/1.1/data/0-data/4CLCAE-ISO-19115-2.xml) explicitly dedicates the dataset to CC0. A catalog's inconsistent access-level tag does not override the actual public archive, successful HTTP 206 file retrieval, and product-specific license. File hashes, archive members, sizes and acquisition receipts are pinned in the reviewed configuration and retained by the compiler.

The northern GeoTIFFs identify NAD83/UTM 10N. The Santa Barbara Island files embed an unnamed GRS80 horizontal datum, while the archive documentation specifies NAD83/UTM 11N. The compiler uses that documented projection, preserves the embedded WKT in each numeric view, and records the discrepancy. It never replaces the unknown vertical reference with MLLW. The vertical values remain signed metres from the published source.

## Repeatable processing

`regions/southern-california/habitat-sources.json` is the reviewed input contract. `scripts/build_socal_habitat.py` consumes it, creates `survey-habitat.geojson`, a per-island coverage summary and masked numeric bottom tiles, and writes `habitat-receipts.json`. The private raw cache stays outside public artifacts under `var/`.

```bash
# Run with the optional GIS environment containing numpy, rasterio, shapely,
# pyproj, pyogrio, requests and remotezip.
python scripts/build_socal_habitat.py --fetch
```

The first validated build used NumPy 2.5.3, rasterio 1.5.1 (GDAL 3.12.4), Shapely 2.1.2, pyproj 3.8.0 and pyogrio 0.13.0. Keep the GIS environment pinned when comparing byte-level output or feature identifiers; geometry-library upgrades deserve a fresh geometry and closure review.

On later runs the hash-pinned cache makes the import reproducible without network requests. `--refresh` rechecks the source products but refuses an unreviewed content change. A failed, empty or mismatched source cannot silently replace the prior public habitat asset. A monthly catalog watch is appropriate; these historical surveys must not be relabeled as fresh observations by a daily rebuild.

The pipeline:

1. Validates source hashes and bounded file sizes. ZIP members are read without filesystem extraction.
2. Reads native 2 m/4 m acoustic cells in bounded blocks. For every 8 m display cell, **all** original cells must be present, underwater and no deeper than 60.96 m. The 8 m aggregation is a rendering choice, not an assertion that source accuracy is 8 m.
3. Dissolves qualifying cells, erodes the footprint by 4 m, then intersects that footprint with the source's actual hard/soft geometry. Substrate classification is not inferred from slope or image color.
4. Preserves actual dated kelp detections separately. Kelp shapes outside bathymetric coverage explicitly lack a complete depth screen.
5. Removes every MPA and Groundfish Exclusion Area with a 75 m geometric clearance. It clips entire polygons, including holes and crossing segments, rather than checking only centroids. This margin does not claim to bound the older substrate map's unknown positional error.
6. Omits small display fragments below 0.01 km² for substrate or 0.0025 km² for kelp. Gaps are never joined by an invented enclosing hull. Browsing extents are only view shortcuts and labels.
7. Generates up to 24 measured views per island from representative points of the largest distinct habitat shapes, prioritizing substrate over overlapping kelp. Each 129×129 numeric window preserves original 2 m/4 m cells and missing-data masks; no new interpolation fills holes. Every view records its separate source digest, resolution, source year range, coverage and limitations. The 0.1 m storage precision is not survey accuracy.

The image's depth range describes the **image window**, which can extend beyond the habitat outline or the 200-foot band. It is not mislabeled as the depth range of the entire habitat polygon. Published coordinates retain seven decimal places, changing position by less than a centimetre in this region while reducing transfer size. This is storage precision, not survey accuracy. Each shape has `depth_qualified:false`, `fishing_target:false`, no A/B/C quality grade and no catch or AIS evidence claim.

## Island coverage and access

This release contains 410 actual habitat polygons and 84 numerical bottom windows.

| Island | Hard substrate | Soft substrate | Historical kelp | Total shapes |
| --- | ---: | ---: | ---: | ---: |
| San Miguel | 5 | 7 | 124 | 136 |
| Santa Rosa | 12 | 4 | 159 | 175 |
| Santa Cruz | 23 | 6 | 34 | 63 |
| Anacapa | 2 | 2 | 0 | 4 |
| Santa Barbara | 6 | 16 | 8 | 30 |
| Catalina | 0 | 0 | 2 | 2 |
| San Clemente | 0 | 0 | 0 | Withheld |

Zero counts are coverage gaps or exclusions, not proof that habitat is absent.

The machine-readable `summary.islands` in the GeoJSON contains actual shape counts, counts by habitat class, retained depth-screened area and gaps for San Miguel, Santa Rosa, Santa Cruz, Anacapa, Santa Barbara Island, Santa Catalina and San Clemente. The five sanctuary islands receive actual numerical bathymetry where the source has cells; Catalina currently has dated kelp context and no imported native bathymetry. The detailed shapes do not imply a complete survey of an island's shoreline.

San Clemente nearshore habitat is withheld because the active Navy range status and complete access screen were not verified. Consult the [Navy schedule](https://www.scisland.org/) and [current 33 CFR 165.1131](https://www.ecfr.gov/current/title-33/chapter-I/subchapter-P/part-165/subpart-F/section-165.1131). An empty or inaccessible schedule is not clearance. MPA exclusion also does not decide all seasonal groundfish restrictions or authorize anchoring, landing or fishing.

## Sources considered but not promoted

- [USGS OFR 03-85](https://pubs.usgs.gov/of/2003/0085/) and [OFR 2005-1170](https://pubs.usgs.gov/of/2005/1170/catalog.html) contain historical habitat polygons and 1 m sidescan for San Miguel, Anacapa and southeast Santa Cruz, supported by selected diver/ROV observations. The original San Miguel 2003 archive became accessible in September 2026 and is now SHA-256-pinned in [`catalog/usgs-ofr0385-san-miguel.json`](../catalog/usgs-ofr0385-san-miguel.json). Its 2,871 polygons include 2,238 marked hard, 621 mixed and 12 soft; three invalid original polygons require explicit repair for this research count. Metadata states roughly 10 m positional accuracy. A 1 m backscatter pixel is not a 1 m depth cell or boulder measurement.

The [original-cell San Miguel review](../dist/data/san-miguel-original-habitat-vr-review.json) compares those USGS classes to NOAA's later [H13084](https://www.ngdc.noaa.gov/nos/H12001-H14000/H13084.html) MLLW variable-resolution BAG. Inside the USGS bounding envelope, 5,574,288 native cells pass the 25–200 ft depth/product-uncertainty policy; 648,740 intersect mapped hard class and 9,739 mixed class. Fresh complete CDFW MPA and NOAA federal-area snapshots, the hash-pinned H13084 hazard report, and an 18-layer NOAA ENC Direct danger query leave 601,603 hard-class cells after conservative research buffers. Counts do not form connected search outlines, prove current bottom character, clear navigation or access, or establish a catch rate. H13084 remains a held source pending exact-area chart, park, protected-species and method review. The [W00320 regular 4 m BAG comparison](../dist/data/san-miguel-original-habitat-depth-review.json) found only 257 measured cells in the same USGS envelope, all beyond 200 ft, showing why a survey envelope alone cannot substitute for native-cell overlap.
- [NOAA West Coast Induration 2017](https://maps.fisheries.noaa.gov/server/rest/services/WestCoast/USWestCoast_SeafloorInduration_v2017/MapServer) is a reviewed discovery lead with a live service and explicit CC0 terms. It provides 25 m hard/mixed/soft raster context and a separate quality layer. The map service did not expose native downloadable values during this import; rendered tile colors were not reverse-engineered into invented scientific polygons.
- [CDFW Kelp Persistence ds3151](https://www.arcgis.com/home/item.html?id=a8ded116c6ba45f7b0cb85d24db4558b) is a useful 5 m historical multi-survey indicator based on 2002–2006, 2008–2010 and 2013–2016. It is not current canopy. The original 2016 vector survey was selected for this release because its class, footprint and observation dates are explicit.
- [NPS/Santa Barbara Channel Marine BON](https://sbc.marinebon.org/data/catalog/) offers ecological monitoring context. Its scientific observations need a separate sampling, effort, geometry and redistribution review before they can inform a fishing score. No habitat polygon currently makes a calibrated bite prediction.

Next imports should replace the old substrate compilation with available, ground-truthed native classifications; resolve common bathymetric datum/uncertainty; import recent kelp observations with quality masks; and then qualify exact target geometry and export support. The present release improves detail without hiding those evidence gaps.
