# COAST-PROD identifiers and saved-area window crosswalk

Repository evidence snapshot: `0991fc70d212c9405f7b174950cb3fa4d7c6846d`
(2026-11-15). This is a compatibility/history reconciliation, **not new
scientific acceptance, an amended grant, installation or live adoption**.
All retained real-data evidence remains PRIVATE / `publication_prohibited`.

## Namespace plus identifier is the key

Never join on the number alone. The plan/report and skill namespaces describe
different criteria; plan PASS cannot overwrite the skill criterion's verdict.
The six unique keys in each namespace are:

| Plan/report key | Meaning | Related skill key (not equal acceptance) |
| --- | --- | --- |
| plan:COAST-PROD-01 | Package/import inspection | skill:COAST-PROD-01 inspection interface |
| plan:COAST-PROD-02 | Receipt recovery | skill:COAST-PROD-03 retained real inputs |
| plan:COAST-PROD-03 | Private handoff | skill:COAST-PROD-04 private handoff |
| plan:COAST-PROD-04 | Terrain preview | skill:COAST-PROD-05 real preview |
| plan:COAST-PROD-05 | Operations tests | Partial evidence for skill:COAST-PROD-06 only |
| plan:COAST-PROD-06 | Archived legacy software-browser view | No integrated-operations equivalence |

Skill-only criterion `skill:COAST-PROD-02` means installed closure: actual
wheel/dependencies/resources/launcher identity and positive/negative consumers.
Thus plan:04 is terrain, skill:04 is private handoff; plan:06 is browser,
skill:06 is integrated operations. Neither pair is interchangeable.

Sources: [coastal-pipeline.md](../../../skills/skippercast-discover-coastal-sources/references/coastal-pipeline.md)
sections “Evidence snapshot” and COAST-PROD table (repository-relative path is
`skills/skippercast-discover-coastal-sources/references/coastal-pipeline.md`,
lines 226–338 at the snapshot). The historical T15c-b v1 report was NOT_PASS
(plan 03 FAIL); T15c-c v2 was bounded PASS after citing separate closure
receipts. Original pending-science and INDEPENDENT_PASS receipts were not
rewritten. The current skill table records an installed-closure receipt from
`bde9c6df`; older “not demonstrated” statements remain dated snapshots, not
contradictory current instructions or renewed scientific acceptance.

## Window identities: strict is not partial support

All window tuples are `[column,row,width,height]` in the full H11952 native
grid, EPSG:26910; rows increase downward. The full-grid affine is
`[2,0,721091,0,-2,3826155]`, full shape `[10495,10034]`.

| Identity | Exact window | Window affine origin |
| --- | --- | --- |
| historical original A (unchanged default) | `[3890,3488,128,128]` | `[728871,3819179]` |
| strict final A | `[3762,3488,128,128]` | `[728615,3819179]` |
| strict final B | `[3890,3488,128,128]` | `[728871,3819179]` |
| strict final C | `[3762,3360,128,128]` | `[728615,3819435]` |
| strict final D | `[3890,3360,128,128]` | `[728871,3819435]` |

The final whole-block upper-left is `[3762,3360]`, **not A's row 3488**.
FIX3 moved the old block `[3890,3360]` one 128-cell lattice column west
(256 m), not one 2 m raster cell. Final bounds are
`[728615,3818923,729127,3819435]`. Old A/C diagnostics become new B/D evidence;
that does not relabel failed attempts as successful adoptions.

The separately pinned partial-support A-D set is
`[[4402,3872,128,128],[3762,3744,128,128],[3634,3616,128,128],[4018,3488,128,128]]`,
bounds `[728359,3818155,730151,3819179]`, under
`coastal-contained-partial-support-v1`. It cannot select the strict final-A pin.
Unsupported cells remain nodata; mask-invalid counts alone do not prove holes.

Sources: `src/skippercast/coastal/coordinator/ordered_trial.py:23–43`
(`LARGER_WINDOWS`, `LARGER_AFFINE`, `LARGER_BOUNDS`, `scope_windows`),
`src/skippercast/coastal/authenticated_v1/profiles.py:6–28`
(`PARTIAL_WINDOWS`), and `tests/gis/test_coastal_saved_area_native_grid.py`.

## Attempts, reads and reruns are append-only history

These are recorded source-code/ledger statements, not newly opened private
receipts or source observations. “Unknown” must not be turned into zero.
The ledger's older `failed_trial` is the 2026-10-11 failed trial, **not** fresh
2026-10-19 attempt 1. The later numbered failures have separate charge fields.

| Historical event | Retained outcome / limitation | Charged source bytes |
| --- | --- | --- |
| Pre-failure baseline | Carried prior, not new allowance | 821491388 |
| 2026-10-11 failed trial | Two conservative source reservations; scratch reservation retained | 73515136 |
| Fresh attempt 1 | Failed/held; resources narrative explicitly says no source charge | 0 |
| Fresh attempt 2 | A-acquire bootstrap absent; one uncertain reservation remains charged | 36757568 |
| Fresh attempt 3 | Failed/held in skill's attempts 1–5 summary; detailed outcome/individual charge UNKNOWN in these committed references | UNKNOWN, no separate ledger key |
| Fresh attempt 4 | B-acquire held: 18 mask-invalid cells; old block B/D invalid; three reservations retained | 110272704 |
| Window pre-scans | Two read-only cached-BAG opens, charged in advance, never refunded | 73515136 |
| Fresh attempt 5 | D-acquire deadline; six settled A/B/C reservations plus one uncertain D reservation | 257302976 |
| Fresh attempt 6 | Acquire/qualify/map completed at `ed28dc69`; eight settled admissions, originally pending-science | 294060544 |
| Attempt-6 validation hash reads | Two separately charged read-only passes; not downloads | 73515136 |
| Clean rerun 1 | `20261020r1`, `292cb0aa`, eight settled admissions; stops at map | 294060544 |
| Clean rerun 2 | `20261020r2`, `16418f92`, eight settled admissions; stops at map | 294060544 |
| SC-5 geometry pre-scan | One advance charge, distinct partial-support scope; not a ninth runtime admission or proof of scan success | 36757568 |

Charge authority is the unchanged
`research/catalog/coastal-four128-charge-ledger.json` revision 7 projection:
`prior_effective_bytes=2365309244`, `cumulative_limit_bytes=2659369788`,
`fresh_allowance_bytes=294060544`, `refunds=false`, `downloads=0`.
Recorded scratch prior is `1616905649`, cumulative maximum `2153776561`,
trial reservation `536870912`, also no refunds. These historical amounts are
not reusable allowances. No attempt, reservation, expiry or ledger is reset.

Detailed narrative: `research/scripts/coastal_four128_resources.py:31–74`;
accounting projection: `research/catalog/coastal-four128-charge-ledger.json`;
replay/admission boundary: `research/four128-admission.md`.
Attempt-6 receipt locator: `outputs/t08-four128-20261019/receipt.json`
(`5df6526c28c5`); original validation `2796e40d8b30`. Rerun locators:
`outputs/t15-four128-rerun1-20261020/receipt.json` (`fad41b67c39a`),
`outputs/t15-four128-rerun2-20261020/receipt.json` (`ddc6845b8158`).
These private-store locators/prefixes are retained citations, not fetched bytes.
Independent rerun validation `f3510f03f431` (1,154 recorded checks) does not
supply rerun science acceptance or a missing render-handoff manifest. Separate
T13 science/artifact acceptance covered attempt-6 cores only; no integrated
clean-state discover-to-render twice, live hole preservation or publication
acceptance is inferred.

## Offline opt-in and future adoption HOLD

`require_saved_area_a_native_grid(facts, window)` preserves ORIGINAL A,
including the existing legacy comparisons and rejection order. Its optional
`grid_contract` must have exactly these software-reviewed fields:

- `schema`: `coastal-saved-area-strict-final-a-grid-v1`;
- `scope`: `coastal-ordered-four128-v2`;
- `support_policy`: `strict`;
- `window_set`: the complete exact shared strict `LARGER_WINDOWS` set above;
- `full_grid_transform`: exact shared `LARGER_AFFINE` above.

Only that recognized contract and final A's exact window select read-only
`STRICT_FINAL_A`. Its affine is checked by composing the shared full-grid
affine with final A's column/row, never trusted from caller observations.
Unknown/partial/extra/incomplete contracts refuse before inspecting facts;
the compatibility function does no metadata, SQLite or native access.
A contract is a software scope discriminator, not an issued review or grant.
Duplicate calls are pure and confer no accounting registration.

`validate_adoption` still calls the legacy default with no opt-in. The new
contract is deliberately **not** a grant field or live-adoption parameter.
Final bytes without opt-in, old bytes under final opt-in, wrong windows,
cell/subcell shifts, flipped Y, wrong CRS/shape/resolution/support all refuse.
Current source/grant/review/horizon/accounting requirements remain unchanged.
Future final-A live adoption is **HOLD** for the existing admission/scientific
owners; this PR cannot supply their conclusions or reopen an exhausted run.
Unknown attempt-3 detail belongs to the existing retained-receipt custodian,
not a reconstructed ledger. No installed skill, ordered trial, metadata,
ledger, grant, source or service was changed.
