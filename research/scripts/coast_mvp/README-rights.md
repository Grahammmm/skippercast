# Coast MVP rights export (C5)

Offline research tooling; no downloads, catalog edits, email, deployment or publication.
The standalone HTML is an export for review, not a change to the live licences page.
Product code must not import `research/` (repository boundary). C3 may serve a reviewed
export as a static local preview asset; runtime integration is owned by C3.

## Fixture acceptance

From the repository root, using Python 3.11+:

```sh
python research/scripts/coast_mvp/coast_rights.py \
  --manifest research/tests/fixtures/coast_mvp/rights-manifest.json \
  --output var/coast-mvp-c5/rights.html
python -m pytest research/tests/test_coast_mvp_rights.py
```

Open the output locally. The fixture is synthetic: repeated-digit hashes and cell
counts are deliberately invented test values, not downloaded-file receipts. The
page labels it SYNTHETIC FIXTURE ONLY. No restricted raster bytes are committed.
The example GEBCO citation is taken from the already-committed candidate metadata;
this does not promote that candidate or claim it has been acquired.

## Manifest contract and C1 handoff

`schema_version: 1`, with a `sources` array. Each row must have:

- `source_id`: unique nonempty string (including unused rows).
- `contributed_cells`: nonnegative integer, computed from C1's FINAL contributor
  raster, after nodata exclusion and priority masking. Booleans and guessed usage
  from input presence, resolution, file bounds or the catalogue are rejected.

For each row with `contributed_cells > 0`, also require:

- `name`, `source_url` (HTTPS documentation URL), `sha256` (64 lowercase hex digits
  identifying the input raster bytes, retained from acquisition receipts).
- `rights.license`: exact recorded per-release licence / terms text, not a guess
  based on host or institution. CC0 and US public domain remain distinct strings.
- `rights.terms_url`: HTTPS evidence URL for those terms.
- `rights.attribution`: full source-specific credit/citation, including release
  name, authors, year and DOI where the source requests them. GEBCO must carry the
  citation for the actual grid version, not an automatically invented current year.
- `rights.csumb_involved`: explicit boolean, including USGS-published co-productions.

Additional C1 provenance fields may be present; only the fields above are rendered.
Do not pass private URLs or secrets. This tool does not fetch any URL, read rasters,
verify source hashes, verify citations against upstream text, or attest that the
contributor counts are correct. Those checks belong to C1/source review. The CLI pins
the exact input JSON bytes with SHA-256. The Python render function without a supplied
digest hashes canonical JSON instead. Output order is by source ID.

Zero-contribution rows are excluded from the rights inventory; missing contribution
counts are an error, never treated as zero. Positive contributors with absent licence,
credit, evidence URL or hash fail the entire build before replacing a previous page.
Empty mosaics explicitly report no contributors and retain the safety/review notices.
No upstream manifest exists on main yet: this contract is explicit for C1 to populate,
not evidence that a real C1 mosaic has passed this acceptance check.

## Review and rights boundaries

Every page is `review_required`, including CC0 and US-public-domain rows; machine-valid
metadata is not semantic or legal acceptance. Recorded terms and credits are displayed
verbatim with HTML escaping. Unsafe URL schemes and credential-bearing URLs are refused.

CSUMB contributions always get `needs_permission`, even when the release licence says
public domain or CC0. Explicit CSUMB references in names, IDs, credit or evidence keep
that flag even if `csumb_involved` is incorrectly false. The page records the SFML
non-profit/acknowledgment policy and flags the unresolved for-profit permission question;
owner/counsel must resolve it. No email is sent and no permission is assumed.

GEBCO's recorded licence and version-specific citation are preserved, with a general
no-endorsement/no-misrepresentation statement naming GEBCO, IHO and IOC. Every export
says not for navigation or any purpose involving safety at sea. None of these notices
makes a mosaic fit for navigation, commercial use or publication.

Evidence already present in the repository / admitted plan:

- `docs/legal/data-rights-register.md`, B3 and catalogue rows: unresolved CSUMB/USGS
  terms and the distinction between redistribution and commercial clearance.
- `catalog/candidates/gebco-2026-grid.json`: recorded GEBCO terms and citation DOI;
  candidate remains unapproved and unacquired by this task.
- Admitted `coast-campaign-plan.md` licence summary: CSUMB non-profit/credit,
  per-release CC0/public-domain labels, and not-for-navigation limitations.

C1-C5 cross-model batch review is still required. This tooling neither modifies the
canonical rights register nor relaxes existing commercial/publication gates.
