# Government-only physical input scope

This capability builds a separately reviewed commercial-use release from
eligible original government inputs. It does not grant rights to CSUMB data,
filter mixed habitat after extraction, or make a release available by itself.
The full pinned `catalog/surveys.json` remains unchanged.

## Input contract

- Default processing remains `all`, preserving the existing noncommercial
  pipeline. An optional deployment `source_scope` or
  `SKIPPERCAST_SOURCE_SCOPE=government-only` selects the restricted input scope.
- Government-only requires the existing explicit `for-profit` source-use
  profile. A paid deployment still cannot select noncommercial permission.
- In a new owned isolated root, create ignored `var/seafloor/input-scope.json`
  with `version: 1`, `scope: "government-only"`, and `isolated_root` equal to
  that root's absolute resolved path. Government processing rejects a missing
  or mismatched marker; default processing rejects any scoped marker. Do not
  install this marker in another task's or production working tree.
- Before ingestion or native precedence, select only catalog rows licensed
  `public-domain-us-gov` whose recorded lineage also resolves to government
  originals. Preserve original ordering, status, hashes, masks, datum, scale,
  quality holds and terrain-support constraints. Excluded substrate supplies
  no classes; absence remains unknown.
- Normal coverage selection, terrain, support masks, reach-wide thresholds,
  connected components, fit rules and whole-polygon screening then operate on
  that input set. There is no alternative numerical package or scale change.

Both planning and processing apply this selection. A private-only run remains
private, even when its originals are government data. Private-physics adoption
and numeric-only migration are refused for scoped roots: changed source
selection requires the normal checked processing path.

## Auditable outputs

The `government-input-scope-v1` audit pins the full catalog SHA-256 and sorted
admitted/excluded source identities. It enters the physical input hash before
the screen identity is added. The source-scope implementation itself is hashed.
Changing the scope or catalog cannot reuse mixed physical outputs.

The runner retains original source rows/receipts, substrate bindings, rules,
reference and implementation identities, canonical candidates and all output
hashes. Scoped coverage checkpoints carry the same audit. Original native cache
objects are still content-addressed and byte-verified.

Publication independently requires the exact current scope audit, original
physical and substrate rows, coverage source identities, and a hash-verified
candidate calibration inventory. It verifies every calibration source, even
when that source produced no polygon. An empty inventory is valid for a reach
that produced no eligible grid; missing or duplicate inventory is an error.
Existing quality/support and current CDFW/federal/security screening checks
remain mandatory. A scoped receipt cannot enter default publication.

Canonical export and manifest carry `source_scope` and
`reach_calibration_source_ids`, while canonical polygon coordinates, holes and
parts are preserved. PMTiles remains quantized display geometry. Nominal datum,
unknown uncertainty/interpolation, planning fit and non-navigation limits remain
unchanged. Government eligibility is not fishing clearance or fish presence.

## Run and release gates

From the owned isolated root, with verified reference, original caches and
current reviewed screen installed:

```sh
export SKIPPERCAST_SOURCE_SCOPE=government-only
export SKIPPERCAST_SOURCE_USE=for-profit
export PYTHONPATH=src:.
python -m skippercast.seafloor plan --region morro-bay --json
python -m skippercast.seafloor run --reach morro-bay-r01 --fetch
python -m skippercast.seafloor publish --region morro-bay
```

Repeat processing for every reach in the complete requested regions, including
unmapped reaches, before regional publication. Failed or coverage-only results
must not inherit old habitat. The source namespace and raw recovery receipt
must identify the isolated input scope and exact reviewed scientific revision.

The existing uploader deliberately refuses scoped bundles. Its default aliases
belong to the mixed noncommercial product. A separate release capability must
be reviewed before upload: immutable archive/export keys, a scope-specific
current manifest with expiry/withdrawal, complete byte read-back, public strong
ETag and Range/If-Match verification, and explicit consumer binding. Preserve
the existing branch/CI/publication authority and complete-region gates. No
scoped release is live merely because local builds or tests pass.

Offline tests include a real small native raster run with a finer restricted
competitor excluded before ingestion, coverage and calibration; restricted
substrate; calibration-only dependencies; cache/source scope identity; isolated
root enforcement; canonical hole preservation; and default-upload refusal.
