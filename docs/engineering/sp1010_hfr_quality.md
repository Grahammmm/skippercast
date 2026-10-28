# SP1010 HFR quality: finite packed HDOP

## Frozen contract and bounded delta

Specification: SP-10-v1, item SP1010-HFR-QUALITY.
Base: 2979d59bfbb7d724eb83b34a48102b914ee8eaa3.
Baseline ocean.py SHA256: 1315e6eceb51bb135afe43d1df11c8e43afd459de9e49ba7472ece22030c1b43.

The DAP path in `pipeline/ocean.py` now checks `math.isfinite(hdop)` before
emitting a cell. Its existing nonnegative and scaled-HDOP <= 2 comparisons
remain unchanged (packed HDOP 0 through 200 inclusive). Previously NaN passed
both comparisons and appeared as NaN output quality. Infinities and finite
out-of-range HDOP remain rejected. No scientific threshold was changed.

The one-line product change does not alter radar-count rules, the 0.01 scale,
vector validation, coordinate selection/stride, six-frame time coverage,
last-populated sample time, latest-grid time, empty frames, gap retention,
provider/field metadata or observation caveats. It does not touch noaa_hfr.py,
WCOFS or spectral processing. Fractional-radar-count hardening is excluded.

## Test-to-claim map

All names below are methods of
`tests.unit.test_sp1010_hfr_quality.RegressionTests`.

| Row | Named assertions and coverage |
| --- | --- |
| A1, A4 | `test_primary_regression`: real hfr excludes a NaN-HDOP cell, retains an empty frame, zero valid count, null sample time and latest-grid time. Product ValueError/OverflowError becomes observed data before the semantic assertion, not an accepted harness error. |
| A1, A4 | `test_healthy_control`: packed HDOP 100, two radars, exact retained cell `[35, -121, 1.944, 90, 1, 2]`, finite quality, identical sample/latest times and strict JSON. |
| A2 | `test_each_invalid_hdop_isolated`: NaN, both infinities, negative and just above 200 each with otherwise valid axes/count/vector. |
| A2 | `test_mixed_cells_keep_exact_identities_and_counts`: eight cells, exactly three surviving coordinates and qualities, per-frame and top-level counts, strict JSON. |
| A3 | `test_finite_endpoints_and_nearby_values_keep_scale`: 0, 0.0001, 1, 100, 199.9999, 200; exact identities, scaled/rounded qualities and unchanged vectors. |
| A3 | `test_existing_radar_count_gates`: invalid finite counts and nonfinite counts rejected; 2 and 20 retained exactly; no fractional-count change. |
| A3 | `test_existing_sentinel_and_vector_validation`: u/v fill sentinels, nonfinite and oversized vectors rejected; zero and southward vectors retained. |
| A3 | `test_all_empty_frames_retain_latest_grid`: both empty frames retained, null observation time, latest grid preserved. |
| A3 | `test_latest_empty_frame_does_not_replace_last_observation`: latest empty frame remains a gap; earlier populated frame supplies sample time/count. |
| A3 | `test_grid_stride_and_regional_selection_unchanged`: 35-by-35 synthetic grid, stride 2, exact endpoint coordinates, DAP query and 324 selected cells. |
| A3 | `test_time_selection_keeps_six_frames_and_gaps`: eight supplied times select only the last six, with exact gap/count sequence. |
| A3 | `test_real_dap_arrays_and_dap_preserve_quality_tokens`: the actual parser preserves NaN and finite tokens before hfr filters quality. |

`SyntheticDAP` is a fake transport only. It supplies DDS dimensions, DAS
packing/origin metadata and DAP ASCII arrays for time/lat/lon/u/v/hdop/site
count, interpreting the actual requested slices. All parsing, selection,
vector conversion and output assembly run in the real staged modules. The
fixture definitions are committed in `tests/fixtures/sp1010_hfr_quality` and
invented rather than downloaded. The fixed public endpoint appears only as an
inert expected fake-client request. Invented fixture identity uses example.invalid.

The original compatibility selector remains unchanged and is run literally:
`tests.unit.test_pipeline_intelligence.IntelligenceTests.test_dap_parser_keeps_fill_and_zeros_and_current_direction_is_toward`.
It exercises only pure DAP/vector/bounds functions; it constructs no SQLite sink.
Optional GRIB/eccodes tests are not silently skipped or claimed as this selector.

## Honest test-first evidence

Before the product edit, the pinned HEAD and ocean.py digest were checked.
Baseline ran exactly the primary regression followed by the healthy control:
one named semantic assertion failure (`valid_cells` was 1 instead of 0), one
pass, child exit 1, no errors or skips. The baseline wrapper exited 0 solely
for `BASELINE_DEFECT_REPRODUCED`; this is historical red evidence, not a pass
for the product. Its receipt is retained beneath the candidate's
`out/author-baseline/baseline-sz_om940` directory, with SHA256
6af593657660b94c0a180fc055327187e0e87bfe9a1a4f42b00eadcc28001979.

Test and fixture bytes are unchanged between this red baseline and final
acceptance; each final receipt checks and references that baseline. After
baseline, the helper was hardened to freeze the exact twelve-test inventory
and explicitly match the primary assertion marker. Its own differing baseline
and final hashes remain honestly recorded; no baseline receipt was resealed,
and the baseline was not rerun on repaired source.

## Portable runtime and evidence

From the staged repository, invoke each mode separately:

    python3 scripts/accept_sp1010_hfr_quality.py --suite baseline --output ../out/author-baseline
    python3 scripts/accept_sp1010_hfr_quality.py --suite focused --output ../out/author-focused
    python3 scripts/accept_sp1010_hfr_quality.py --suite regression --output ../out/author-regression
    python3 scripts/accept_sp1010_hfr_quality.py --suite repository --output ../out/author-repository

Baseline is only valid before product edits on the pinned base. Do not rerun
it on repaired code expecting a green baseline. Reviewer final-mode runs use
separate output parents and may set `--actor` to their disclosed runtime.

The runner derives repo/candidate paths from itself and requires the
operator-written `SOURCE-MANIFEST.json` in the candidate parent with schema
`agentorange.source-manifest/v1`, matching paths, base and admitted runtime.
It checks ancestry, original regression-source hash, unchanged checker source,
and that the linked staged venv matches the manifest. Tests run through
`.venv/bin/python3`; repository mode runs the unchanged
`scripts/check_repository.py` under `runtime.credential_scan_python3`, with no
interpreter fallback. The scan is the repo's credential/private-path/link
release hygiene check, not an exhaustive external security audit.

Before target imports the child suppresses bytecode, prepends the staged repo
and src to sys.path, sets the package root to this repo, redirects tempfile,
HTTP cache and forecast roots to new synthetic paths, and installs network,
model-package, subprocess and out-of-root-write tripwires. Imports and bound
settings roots are verified before any target function call. All selected
hfr/DAP/vector APIs and the original selector are filesystem-free; no var,
region_dir, run_dir, default operational client or live sink is invoked. Test
collection itself has no target import, environment change or permanent audit
hook; ordinary test execution uses reversible mocks that end with each test.
These controls detect mistakes; they are not a hostile-code sandbox.

New fixture and evidence ancestry refuses symlinks. Each invocation makes a
fresh unique child under its supplied output parent. It records actual argv,
cwd, interpreter/version/prefix, HEAD/base, imported module origins, source and
test/fixture hashes, manifest hash, named outcomes/counts, exits and stdout/
stderr paths with SHA256. Explicit runtime conditions, not removable Python
assert statements, govern acceptance. Missing selectors, import/dependency
errors, unexpected failures and skips fail closed. Raw output and prior runs
are retained. No installation, network call or external fixture is needed.

## Provenance, review and remaining gates

All new code, tests, fixtures, helper and this note are authored independently
from the brief by actual gpt-6.1-sol / openai-codex on sol-reviewer (run 1705).
No Astra diagnostic source was copied. Luna's earlier staging check produced
no material commit; the candidate was still at the exact base with a clean
status when Sol started. Existing operator staging and shared-venv admission
are preserved, including the local .venv exclusion, without worker changes to
shared environments or Git ignore policy. Commits use the existing identity
and DCO sign-off; runtime provenance is disclosed separately from that identity.

The sole independent same-card reviewer is opus-coder-bopus on actual
Claude Opus 5.5. Scoped green means REVIEW REQUIRED, not semantic, scientific,
legal or shipping acceptance. Full-suite testing, PR publication, required
exact-head CI and shipping remain OWED to the operator. No source/live hold,
legal/privacy gate, publication boundary or other task's work is released.
No worker push, merge, live run, download, service or profile change occurred.
