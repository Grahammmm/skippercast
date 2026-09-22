# Export to a chartplotter or iNavX

The regional Export screen prepares a **GPX 1.1 file and offline notes** for a fishing plan. Waypoints are selected by default. Outlines, fixed structure alignments and protected-area references are optional tracks. The regional exporter creates **no GPX routes**.

An export is a dated snapshot of the selected regional data. Downloading or sharing a file does not confirm that another app or a chartplotter imported it. The user's chartplotter model and software version are not yet known, and no successful hardware import is claimed here. Manufacturer documentation was reviewed on **September 22, 2026**; the device checks below remain necessary.

This guide covers the regional Export screen. The older, dated atlas packages described in [the atlas archive](../atlas/avila-point-estero-2026-09-20/README.md) can contain route-based drift files. Do not infer their file contents from this newer export contract or import both editions without reviewing duplicates.

## Choose a regional set

| Selection | Meaning |
| --- | --- |
| Day plan | Spots added to the local plan for this region. Local browser storage is not a backup or cross-device sync. Review the region and planned local date before exporting. |
| Current map | Eligible spots within the current map view, with the active filters applied. This is a feature selection, not a screenshot of every visible map layer. |
| Filtered selection | Eligible regional spots matching the active filters, including spots outside the current viewport. |
| All region | Every eligible published fishing target in the selected region. This does not turn regional context, survey coverage or unqualified habitat into fishing targets. |

Review the spot list and counts before download. Shared outlines and alignments should occur once even when several selected spots reference them. Changing regions must not mix selections, coordinates, source receipts or protected-area data from the previous region.

The day plan's local date and the file's generation time are different facts. Use the region's timezone for the planning date, retain the generation timestamp, and identify the region in the filename and notes. A planning date does not make the underlying survey, regulation review or forecast current for that date.

## Choose the contents

| Option | GPX representation | How to read it |
| --- | --- | --- |
| Waypoints — default on | `wpt` positions with stable names/IDs and available notes | Starting positions for investigating published habitat candidates, not confirmed fish or safe approaches. |
| Outlines — optional | `trk` / `trkseg` / `trkpt` | Selected habitat footprints drawn as lines. GPX does not carry a filled polygon or legal polygon semantics. |
| Fixed alignment tracks — optional | `trk` lines | Survey-based structure axes. They are not a forecast of boat drift, a setup position, or a passage route. |
| AVOID protected-area outlines — optional | Clearly named `AVOID …` tracks | Dated references for areas to avoid. They are not destinations, plotter boundary alarms or a complete closure service. |

Keep separate polygon rings, interior holes and disconnected components in separate track segments. A receiving device may render segments, symbols, descriptions and names differently, so inspect the result. A gap must not acquire an invented connecting line. An `AVOID` label should appear at the start of its name so that truncation is less likely to hide its purpose; retain the full area name and official source in the offline notes.

The offline notes should preserve the selected spot IDs, coordinates, source identities and dates, depth datum where known, evidence limits, chosen components, counts and omitted items. They provide the readable reference when a plotter omits or truncates GPX descriptions. Save the notes locally and confirm they open without a network connection; linked source pages still require connectivity.

### What the file cannot carry

GPX carries positions and line geometry. It does not install bathymetric grids, nautical charts, satellite imagery, terrain imagery, weather-map images or SkipperCast's interactive map layers. It does not install a forecast timeline or refresh protected-area boundaries. Any weather or rule information included in offline notes remains explicitly dated text.

The export excludes live/current-derived drift projections and does not create a harbor-to-spot navigation connection. Existing charts and other licensed content on the receiving device remain separate products. Do not treat successful line display as confirmation of sounder depth, legal access or a navigable route.

## Screen the selection before generating files

Use the selected region's established export eligibility check. Each selected waypoint and the complete linked fishing geometry included in the file must pass that region's protected-area screen; checking only a centroid, endpoints or the visible part of a shape is insufficient. Missing regional data, broken geometry links or an unavailable required screen must produce a visible reason rather than a partial-looking success.

An optional `AVOID` track is deliberately a protected-area reference, not a fishing geometry that has passed exclusion screening. Keep these two roles distinct in counts, names and notes. The presence of an exported boundary does not certify its legal currency or completeness. Display the actual source/retrieval dates and freshness state, and preserve the region's existing conservative exclusion rules. See [map protection](map-and-forecast.md) and [regional data contracts](data-contracts.md).

## Import on a device

Use a separate, compatible data card and preserve an export of the device's existing user data before an initial import. Avoid writing into a purchased chart card unless its manufacturer expressly permits it. Store the backup somewhere other than the card being used for the transfer. Reimporting a set can create duplicates; a stable ID helps identify an older set but does not guarantee automatic deduplication.

**SD or microSD is the common chartplotter workflow. USB is model-dependent.** A USB socket may serve a card reader or another purpose rather than accept an ordinary flash drive. Check the exact display's card type, capacity, filesystem and supported reader. Copy the actual `.gpx` file, not a ZIP archive, downloaded HTML page or offline-notes file. Inserting storage alone is not an import instruction.

### Garmin GPSMAP and ECHOMAP

Garmin states that marine chartplotters using micro/SD cards for user data can read `.gpx` and `.adm`, including waypoint, route and track data. Its manuals describe GPX for third-party interchange. They do not establish that every GPSMAP/ECHOMAP generation accepts every GPX 1.1 element or extension. [Garmin transfer support](https://support.garmin.com/en-US/?faq=zFDPlv7AnK2eNWRp2AgMkA).

For the current GPSMAP x3 manual, insert the card, open **Where To → menu → Manage User Data → Data Transfer**, select the card if requested, choose **Merge from Card**, then select the file. **Replace from Card overwrites existing user data** and should not be the routine instruction for adding a SkipperCast set. Third-party transfer instructions also include **File Type → GPX**; ECHOMAP menu entry points differ. [GPSMAP card import](https://www8.garmin.com/manuals/webhelp/GUID-3E67C80C-0812-4EEC-BC60-699751B9CF6F/EN-US/GUID-72BBFEE8-763D-4C57-9FFF-792F40B377C5.html), [ECHOMAP UHD2 GPX selection](https://www8.garmin.com/manuals/webhelp/GUID-CDD85099-F5B6-41B4-84D1-524AE6475690/EN-US/GUID-217163D9-1476-4D77-989D-380EA660C06A.html).

Representative capacities, not a family-wide promise:

- GPSMAP 15x3: 5,000 waypoints, 100 routes, 50 saved tracks and 50,000 **active** track points. Its micro-USB specification concerns a compatible Garmin card reader. The active-track figure does not establish a per-imported-track limit. [GPSMAP 15x3 specifications](https://www8.garmin.com/manuals/webhelp/GUID-3E67C80C-0812-4EEC-BC60-699751B9CF6F/EN-US/GUID-421BED65-C3F2-4DAC-8DAA-CFF72A87B654.html).
- ECHOMAP UHD2 9-inch: 5,000 waypoints, 50 saved tracks, 50,000 track points, 100 routes and one microSD slot with a 32 GB maximum. [ECHOMAP UHD2 specifications](https://www.garmin.com/en-GB/p/796274/).

Garmin documents 10-character waypoint names on several older marine families, with different route and track-name lengths. This is a reason to preserve stable IDs and readable offline notes, not evidence of a universal limit for newer models. [Garmin naming limits](https://support.garmin.com/en-SG/?faq=T7VG1gi43QA6FhTfXC3sr7).

### Lowrance

The official HDS Gen3 manuals document GPX interchange for waypoints, routes and trails and a manual file import: insert compatible storage, open **Files**, select the saved file and choose **Import**. Newer displays may call the file browser **Storage**. Follow the exact model's manual for the final menu labels. The older official PDF text was available in the search index during this review, but direct download was unavailable; this is documentation evidence, not a test of a current HDS PRO importer. [HDS Gen3 installation manual, user-data backup/import](https://softwaredownloads.navico.com/Lowrance/FTP/Lowrance_Software%20-%20Copy/manuals/HDS_GEN3_IM_EN_988-10733-001_w.pdf), [HDS Gen3 operator manual, GPX interchange](https://softwaredownloads.navico.com/Lowrance/FTP/Lowrance_Software%20-%20Copy/manuals/HDS-GEN3_OM_EN_988-10740-005_w.pdf).

Current HDS PRO specifications list **3,000 waypoints, 100 routes and 100 trails with up to 10,000 points per trail**. They list microSD slots with a 32 GB maximum; USB availability varies with display size. These capacities do not prove identical limits on other Lowrance families or specify GPX-version handling. [HDS PRO specifications](https://www.lowrance.com/hds-pro/specs/).

### Simrad

The official NSS evo3 installation manual documents GPX interchange and **Files → select file → Import** from a memory card. NSX uses separate Waypoints & Routes and Tracks app workflows; consult its matching guide for the import button and prompts. An NSS menu path should not be presented as an NSX-specific instruction. The older official PDF text was indexed during this review, but direct retrieval was unavailable. [NSS evo3 installation manual, user-data backup/import](https://softwaredownloads.navico.com/Simrad/SimradYachting_Software%20-%20Copy/Downloads/documents/NSS-evo3_IM_EN_988-11364-001_w.pdf), [official NSX guide/download entry point](https://www.simrad-yachting.com/downloads/nsx/).

The indexed NSX basic guide describes GPX user data, microSD storage and USB on supported sizes. Its direct URL redirected to a missing-file page during this review, so use the official download entry point to obtain the guide for the installed software. Do not claim universal GPX 1.1 or USB support from it. [NSX basic guide, indexed reference](https://softwaredownloads.navico.com/Simrad/SimradYachting_Software%20-%20Copy/Downloads/NSX/NSX_BOG_EN.pdf).

Published NSX specifications list **6,000 waypoints, 500 routes with at most 100 route points, and 50 tracks with up to 12,000 track points**. NSX ULTRAWIDE specifies both microSD and USB-A storage interfaces. These are model examples, not common limits for all Simrad displays. [NSX specifications](https://www.simrad-yachting.com/en-eu/nsx/specifications/), [NSX ULTRAWIDE specifications](https://www.simrad-yachting.com/nsx-ultrawide/specifications/).

### Raymarine Axiom with LightHouse 4

The LightHouse 4 file browser recognizes GPX files containing waypoints, routes and tracks; select the file and choose **Import**. The documented card workflow is **Homescreen → My data → Import/export → Import from card**, then locate the GPX. Use the storage reader supported by the particular Axiom generation and installed accessories. [LightHouse 4 Files](https://docs.raymarine.com/81406/en-US/latest/Files-5C8D71E8.html), [documented card import workflow](https://docs.raymarine.com/81406/en-US/latest/ImportingARoute-AF97A6FC.html).

The current Axiom 2 specification lists **10,000 waypoints in up to 200 groups, 250 routes with up to 500 waypoints each, and 15 tracks with up to 10,000 points per track**. Route capacity also consumes the waypoint allowance; the regional SkipperCast export itself has no routes. GPX track outlines do not automatically become Raymarine boundary alarms or filled areas. [Axiom 2 specifications](https://www.raymarine.com/en-us/our-products/chartplotters/axiom/axiom-2), [LightHouse 4 track capacity](https://docs.raymarine.com/81406/en-US/latest/Tracks-9D271B8D.html).

### iNavX

iNavX documents GPX waypoint and track import through **Open In… iNavX** from an email attachment. On a compatible iOS version, save the downloaded GPX in Files and use the system share/open action to hand it to iNavX, then follow its import prompts. Available share destinations and menu labels depend on the installed apps and OS. SD/USB transfer is not required for this workflow. [Official waypoint help](https://inavx.com/h/inavx/waypoints.htm), [official track help](https://inavx.com/h/inavx/track.htm), [current import/export FAQ](https://www.inavx.com/faq).

Show the imported waypoints and tracks separately as needed. The published track help describes drawing line segments between points less than 5 nautical miles apart, so verify long sparse alignments rather than assuming they will appear. No reliable current universal name-length or GPX import-count limit was established in this review. The help does not certify this exporter or every GPX 1.1 extension.

## Capacity and fidelity rules

Device specifications generally describe **total device capacity**, not free capacity or a per-file import allowance. Existing personal data consume it. Optional protected-area and habitat outlines can use many track slots even when few fishing waypoints are selected. Some devices may split track segments into separate saved objects.

Show waypoint count, track count and track-point count before export. Record any splitting or simplification in the offline notes. A 10,000-point track ceiling is a useful conservative design target for the documented HDS PRO and Axiom examples, but it is not a universal guarantee. Never silently discard excess features or present a partial import as complete. Do not split, simplify or round protected-area geometry in a way that claims a new legal boundary.

Use finite WGS84 decimal-degree coordinates and preserve sufficient precision. GPX attributes are `lat` and `lon`; GeoJSON positions are ordered longitude, latitude. Do not reinterpret survey depths as GPX elevation or an unsupported chartplotter sounding. Leave unknown vertical datums unknown. Custom symbols, colors, links, long descriptions, Unicode names, grouping, ordering and deduplication need device-specific verification.

## Verify the exported file and the actual import

These are separate checks. A valid XML file or passing browser test does not establish successful hardware import.

1. Record the region ID, package/version or manifest digest, local plan date, generation timestamp, selected IDs, active selection/filter scope, enabled components and expected counts. Retain the generated GPX and offline notes.
2. Check that the GPX parses as 1.1, contains the expected waypoint and track objects, contains no `rte` objects, has finite in-range coordinates and includes no features from another region. Check polygon closure, independent rings/holes and disconnected segments against the original geometries. Check that shared features are not duplicated.
3. Reapply the regional protected-area check to all selected fishing positions and every included linked geometry in full. Keep intentionally exported `AVOID` reference tracks separate. Confirm that missing data, crossing segments and intersecting polygons are handled by the same rules as the map.
4. Back up the receiving device's existing data. Record manufacturer, exact model, software/app and OS versions, medium/filesystem, chosen import command and any warning. Import a small waypoint-only set first, then a small set containing each optional track kind.
5. Compare several imported names/IDs and latitude/longitude values with the offline notes, including positions on different sides of the region. Confirm the coordinate display format and datum before comparing values; a degrees/minutes display can represent the same decimal-degree position.
6. Enable track display and inspect outlines, holes, disconnected parts, alignment endpoints and `AVOID` labels at useful chart scales. Check for shifted positions, truncation, unexpected joining lines, missing segments, altered shapes and invisible tracks. Confirm that no imported line is activated as a navigation route.
7. Compare expected and actual object counts and check retained personal data and duplicates. If the device omits details, keep the offline notes as the reference. Do not assume that a successful first waypoint means every component imported correctly.
8. Record the result as **verified on this model/version with this fixture**, **partial** with the missing/changed parts, or **unverified**. Preserve a screenshot or user-observed record where available. Recheck material exporter or firmware changes; do not expand one result into all-brand compatibility.

Before an actual trip, review the current official charts, rules, closure information and conditions independently of the saved file. Imported snapshots cannot refresh themselves.

## Repeat for another region

Use the existing [regional package process](regions.md), not a new device-specific app fork. Bind the new region's timezone, target atlas, eligible outlines/alignments, source receipts and protected-area dataset through the shared contracts. A region with context-only geology must continue to export no qualified fishing targets until its evidence gates are satisfied.

Keep a small representative export fixture per region: a waypoint, a linked outline, a fixed alignment when available, and an optional protected-area reference. Include separate geometry edge cases for holes and disconnected components where the data provide them. Run the same file checks and record any subsequent model/version-specific import result using the checklist above. Preserve source attribution and reuse restrictions in the offline notes, and report empty or unavailable components explicitly.

Suggested interface wording:

> **Download GPX** — Export selected places as waypoints, with optional reference tracks. Copy the file to compatible storage and import it using your chartplotter's menu, or open it in iNavX. Storage requirements and limits depend on the model. Save the offline notes and verify the imported positions and lines.
