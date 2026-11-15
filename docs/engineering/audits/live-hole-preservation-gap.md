# Live hole and disjoint-core preservation: retained evidence gap

**AUDINV-FIX-130 — HOLD (missing live preservation proof).**
Checked repository base: `0991fc70d212c9405f7b174950cb3fa4d7c6846d` (2026-11-15).
This report compares existing sanitized receipt descriptions with the retained
partial-support policy from [#761] and source-free admission work from [#781].
It does not authorize execution or assert visual/scientific acceptance.

## Scope and evidence classes

Only repository text, source code, synthetic test definitions and historical PR
metadata were read. No private `outputs/` receipt bytes were read back here; no
native source was opened, downloaded, hashed, scanned or rendered. Receipt hashes
below are **documented historical pins**, copied from [P1]/[P9], not recomputed live.
The bounded repository search found no committed SC-5 topology receipt matching
`coastal-four128-mask-topology-prescan-v1` or `sc5-partial` in JSON files; this is
not proof that the private custodian has no such artifact.

- **Documented historical:** retained descriptions/pins in [P1] or PR metadata;
  no fresh verification of the private bytes or validity horizon.
- **Synthetic-only:** source-free fixtures/test definitions; never observed cells
  from a live source, even when the actual renderer is exercised by that test.
- **Read-back live evidence:** none admitted/read in this assessment.
- **Missing:** exact live receipt/binding or stage proof not established by the
  admitted evidence. Its count is **UNKNOWN**, not zero; disposition is **HOLD**.

Installed-wheel closure [#746] is already merged and explicitly excluded.
Older SC-1 text in [P1] still calls installed closure unresolved; that stale text
is not a new wheel gap, prerequisite, or reason to duplicate the installed receipt.
Nothing changes production, tests, policies, grants, stores, charges or review gates.

## Retained identity register

[P1] identifies H11952, attempt-6/source-renderer lineage `ed28dc69`, and the
historical strict four128 windows (x, y, width, height):
A `[3762,3488,128,128]`, B `[3890,3488,128,128]`,
C `[3762,3360,128,128]`, D `[3890,3360,128,128]`.
Its historical selection reports **0 unsupported cells**; holes are N/A, not a
passing live hole test. The exact historical grant/policy digest and source-file
SHA binding are UNKNOWN in this report's receipt descriptions; no cross-policy
binding is inferred from the common source label.

| ID | Private-store receipt locator | Documented SHA256 | Classification / scope |
| --- | --- | --- | --- |
| R1 | `outputs/t08-four128-20261019/receipt.json` | `5df6526c28c57074a56136c10ef9e179928a0ee8af50ab5816855934f35a4d74` | Documented historical; attempt 6 acquire/qualify/map, t_41de4cd3; attempts 1–5 failed/held, retained without refunds. |
| R2 | `outputs/t08-four128-20261019/validation/receipt.json` | `2796e40d8b3057f1adb1d3039e9e5dbac406f9405f5010883ba01c6327f37b2b` | Documented historical; t_b40d52c8, original `PASS_PRIVATE_MAP_HANDOFF_PENDING_SCIENCE`. |
| R3 | `outputs/t08-four128-20261019/validation/science-closure-receipt.json` | `ff1ebe1de9f486640eb758e0b1a2b2923c8b42b416a255014fd0f0c0fa978923` | Documented historical; closure limited to attempt-6 terrain-only A–D, not partial windows. |
| R4 | `outputs/t13-four128-terrain-acceptance-20261020/t13-receipt.json` | `d80ecebab98004e79c6bb4d5b7c6015fed21f442c64ef0283dee714b22b80e94` | Documented historical; t_189fbd03, 4 cores, 0 held; holes N/A. |
| R5 | `outputs/t15-four128-rerun1-20261020/receipt.json` | `fad41b67c39abc145b6f64d9ad5f8450cd90093d4c95bbf257d7c14b5716851b` | Documented historical; t_187849bc, `292cb0aa`; map only, pending science. |
| R6 | `outputs/t15-four128-rerun2-20261020/receipt.json` | `ddc6845b8158b1fb314116875f6c37d368ad8dda0216b0c5577222eac07d0c9b` | Documented historical; t_2e07206c, `16418f92`; map only, pending science. |
| R7 | `outputs/t15-clean-reruns-20261020/validation/receipt.json` | `f3510f03f431ad4a9119fa20f5aef2f81d2b4b88f3b040ac2efdfc1851b7a306` | Documented historical; t_c49a9aa8, `INDEPENDENT_PASS`; not partial-policy preservation. |
| R8 | `outputs/t15-clean-reruns-20261020/COAST-PROD-report-v2.json` | `d602cebb6d0af2bc6ed6391ae86295f77633ca89078e7847791293feb68e721c` | Documented historical; bounded driver PASS, not full phase-exit acceptance. |

The T15 reruns stop at map: no rerun render-handoff manifest is documented.
T13 rendered separately prepared attempt-6 cores; it did not render the rerun
outputs. Historical T13 reviews, t_d433a9bc, ran at `292cb0aa` and expired around
`2026-10-22T07:09:43Z` [P1]. This report neither renews nor extends them.

## Partial-support comparison identity (not an executed receipt)

[P2]/[P3] retain execution profile `coastal-contained-windows-v3`, opt-in
`support_policy=coastal-contained-partial-support-v1`, and distinct policy schema
`coastal-fixed-patch-policy-partial-v1` with its own computed policy SHA.
Absent opt-in remains strict; a schema name is not an exact receipt policy hash.
The partial policy/grant hash in a live preservation chain is **UNKNOWN** here.

| Candidate | Pinned window | Historical mask-invalid cells | Actual enclosed / border components |
| --- | --- | --- | --- |
| P-A | `[4402,3872,128,128]` | 14 | UNKNOWN / UNKNOWN |
| P-B | `[3762,3744,128,128]` | 4 | UNKNOWN / UNKNOWN |
| P-C | `[3634,3616,128,128]` | 299 | UNKNOWN / UNKNOWN |
| P-D | `[4018,3488,128,128]` | 18 | UNKNOWN / UNKNOWN |

These are count-only FIX3 observations documented in [#761]/[P3], not new
observations or expected output. Their cited locator is `hole-candidates.json`,
SHA256 **prefix only** `024d474a8832`; full digest/private locator is UNKNOWN.
[#761] reports depths 18.0–40.0 m and maximum uncertainty 0.385 m for those
candidates; this is historical metadata, not current qualification.
[P5] pins the intended source SHA256
`0cb528795f939e9238e9b11f52279940a2365b2b4b6f52d9f9db8aea82b235fa`,
36,757,568 bytes, grid `[10495,10034]`, affine `[2,0,721091,0,-2,3826155]`,
and native bounds `[728359,3818155,730151,3819179]`.
Those code constants identify the intended comparison source, not a read-back
binding of FIX3 or any completed run to those bytes. No native hash was computed.

## Evidence-to-policy gap matrix

All rows below retain **HOLD** for the named live proof. A custodian is the
existing evidence owner/role, not a newly assigned job or a completion dependency.

| Gap ID | Required policy / preservation criterion | Existing evidence class and receipt/window binding | Missing proof and precise custodian gap | Result |
| --- | --- | --- | --- | --- |
| G01 | Source, ordered window set, policy SHA, grant/packet/plan and upstream receipt must bind the same chain [P2–P4]. | Documented historical R1–R8 bind strict A–D only; P-A–P-D are separately pinned candidates. Synthetic grant/packet mismatch tests [P6]. | SC-5 admission/receipt custodian: exact full source/receipt/policy hashes and matching partial grant, windows, plan, code/dependency identity; no live chain read back. | HOLD |
| G02 | Every partial window has at least one unsupported cell and at least 8,192 supported pairs; enclosed holes require actual topology, not invalid counts [P2–P5]. | Documented historical strict A–D have 0 unsupported cells; candidates have 14/4/299/18 invalid cells only. Actual partial enclosed/component counts UNKNOWN. | SC-5 pre-scan custodian (existing t_689254ff harness lineage): retained `outputs/sc5-partial-20261020p1-prescan/mask-topology-receipt.json`, full hash/bytes, row-run and 4/8-neighbour enclosed/border summaries and review are not supplied here. Locator is planned, not proof it exists. | HOLD |
| G03 | Unsupported cells are native mask-invalid only, retained as nodata; all mask-valid raw/normalized pairs finite, source-valid and eligible [P2]. | Synthetic-only mapping/evaluation refusals [P7]; count-only candidates cannot distinguish enclosed holes or unmasked NaN. | SC-5 qualification custodian: same-return native masks and finite-pair diagnostic receipt binding, without reopening source to fill this report. | HOLD |
| G04 | Native mask → qualification → map mask/terrain/uncertainty must preserve support, nodata and exact georeference. | Synthetic-only `_prepare` mask preservation [P7]; strict R5/R6 TIFF equality in [P1] concerns fully supported windows, not holes. | SC-5 mapping/validation custodian: existing partial per-stage hashes, support equality and topology summaries for P-A–P-D; actual counts UNKNOWN. | HOLD |
| G05 | Map → mesh → preview retains enclosed holes and supported components, with no interpolation or bridging [P8]. | Synthetic-only renderer test has one 12-cell enclosed hole, two support/mesh components, zero spanning components per fixture core; corruption tests reject filling/bridging. R4 holes N/A. | SC-5 terrain/artifact validator: existing source-bound live `--require-holes` receipt plus map/mesh/preview comparison; live hole/component/spanning counts UNKNOWN, not synthetic values. | HOLD |
| G06 | Disjoint cores and within-core support regions stay separate; no bounding-box/seam support credited. | Synthetic-only disjoint-core check [P8]; partial grant nonoverlap/pinned geometry [P3]/[P6] establishes scope, not rendered separation. Historical strict A–D form a contiguous arrangement. | SC-5 artifact validator: existing live cross-core relation/overlap and mesh-region separation receipt bound to partial source/windows, UNKNOWN here. | HOLD |
| G07 | Supported depth 0–91.44 m inclusive; productUncert in metres, 0 < u ≤ 1 m, valid units/packing and all supported pairs checked [P2]. | Documented historical candidate depth/max uncertainty [#761]; synthetic-only depth/uncertainty/floor refusals [P7]. | SC-5 qualification/independent quality reviewer: exact partial facts/diagnostics, counts, min/max and units confirmation with matching policy/trial/plan hashes; current live qualification UNKNOWN. | HOLD |
| G08 | Independent pre-scan topology review is observation-only; quality and terrain/artifact review must bind their own exact scope/horizon [P2]/[P4]/[P5]. | R3/R4 reviews documented for strict attempt-6 only and expired; [#781] supplies source-free admission code, not an observation. | Existing SC-5 independent reviewers/custodian: exact receipt-byte topology review and partial quality/artifact verdicts with identity, scope and validity. No visual/scientific verdict is supplied by this report. | HOLD |
| G09 | Preserve failed/partial receipts, charges, grant limits and review-required/publication-prohibited state. | Documented historical R1 attempts 1–5 held/failed; R2 pending-science original; [P1] retains T15 v1 NOT_PASS alongside v2 PASS. | SC-5 runtime/ledger custodian: any later attempted/failed/partial run history remains UNKNOWN here; no erased history, refunded charge, new attempt or fresh allowance inferred. | HOLD |

The base partial policy's minimum one unsupported cell is **not** an enclosed-hole
criterion. [P4]/[P5] additionally require an enclosed 4-neighbour unsupported region
in at least one pinned window, plus per-window support floors. Even a reviewed
pre-scan that meets this intent proves input topology only, not end-stage preservation.

## Edge-case disposition (manual report acceptance)

| Case ID | Evidence interpretation checked | Disposition |
| --- | --- | --- |
| E01 | Fully supported R4 and strict reruns cannot prove holes. | HOLD G02/G05; documented zero applies only to those historical windows. |
| E02 | Synthetic holes/renderer PASS cannot populate live observed fields. | HOLD G04–G06; fixture values remain explicitly synthetic. |
| E03 | Strict grant/status cannot borrow partial-policy authority or vice versa. | HOLD G01/G08; distinct policy SHA, opt-in, ordered windows and status required [P2–P4]. |
| E04 | UnmaskedNaN is not native-mask unsupported-cell evidence. | HOLD G03; mask-valid nonfinite/sentinel faults remain refusals [P7]. |
| E05 | Wrong policy, window or source hash breaks the chain. | HOLD G01; no label-only/source-name substitution, truncated hash expansion or stale review reuse. |
| E06 | Filled holes or bridged disjoint components remain failures. | HOLD G05/G06; fixture corruption refusals [P8] do not prove live absence of defects. |
| E07 | Missing topology counts remain UNKNOWN; machine PASS is not visual/science acceptance. | HOLD G02/G05/G08; no new review conclusion, run or acceptance is demanded to finish this report. |

## Conclusion and handoff

Existing policy/harness capability is present; **live hole/disjoint-core preservation
is not demonstrated by the admitted evidence**. This is a completed gap assessment,
not a claim that no private receipt exists or that the product was fixed. Missing
facts belong to the existing SC-5 receipt/admission, mapping and independent-review
custodians named above; no new run, duplicate card or response is required here.
Retain PRIVATE / `publication_prohibited`, expired horizons, original receipts,
failed/open charges, no-refund terms and finite attempt/runtime allowances.
No installed-wheel, browser, imagery, habitat, publication or scientific closure.

## Frozen source citations

All repository links below resolve at the checked base; PR bodies are historical
metadata, not independent read-back of their referenced private files.

[P1]: https://github.com/Grahammmm/skippercast/blob/0991fc70d212c9405f7b174950cb3fa4d7c6846d/skills/skippercast-discover-coastal-sources/references/coastal-pipeline.md#L227-L339
[P2]: https://github.com/Grahammmm/skippercast/blob/0991fc70d212c9405f7b174950cb3fa4d7c6846d/src/skippercast/coastal/authenticated_v1/policy.py#L3-L77
[P3]: https://github.com/Grahammmm/skippercast/blob/0991fc70d212c9405f7b174950cb3fa4d7c6846d/src/skippercast/coastal/authenticated_v1/profiles.py#L6-L104
[P4]: https://github.com/Grahammmm/skippercast/blob/0991fc70d212c9405f7b174950cb3fa4d7c6846d/research/four128-admission.md#L154-L201
[P5]: https://github.com/Grahammmm/skippercast/blob/0991fc70d212c9405f7b174950cb3fa4d7c6846d/research/scripts/coastal_four128_mask_topology.py#L43-L260
[P6]: https://github.com/Grahammmm/skippercast/blob/0991fc70d212c9405f7b174950cb3fa4d7c6846d/tests/unit/test_coastal_partial_support.py#L70-L294
[P7]: https://github.com/Grahammmm/skippercast/blob/0991fc70d212c9405f7b174950cb3fa4d7c6846d/tests/gis/test_coastal_partial_support_mapping.py#L36-L193
[P8]: https://github.com/Grahammmm/skippercast/blob/0991fc70d212c9405f7b174950cb3fa4d7c6846d/research/tests/gis/test_check_terrain_acceptance_render.py#L25-L195
[P9]: https://github.com/Grahammmm/skippercast/blob/0991fc70d212c9405f7b174950cb3fa4d7c6846d/skills/skippercast-discover-coastal-sources/references/coastal-pipeline.md#L410-L447
[#746]: https://github.com/Grahammmm/skippercast/pull/746
[#761]: https://github.com/Grahammmm/skippercast/pull/761
[#781]: https://github.com/Grahammmm/skippercast/pull/781
