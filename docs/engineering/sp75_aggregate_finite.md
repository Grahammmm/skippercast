# SP75: finite aggregation parameters

Scope: pure `AggregateParams.from_mapping` boundary hardening. No configured
threshold, source, event publication, rights ordering or grid algorithm changes.

## Claim-to-test map

The only new product helper, `_reject_nonfinite`, inspects the normalized JSON
tree immediately after the existing mapping normalization, before any numeric
comparison, integer conversion or resolution ratio rounding. Its float branch
rejects NaN and either infinity with a field/path-specific ValueError; mapping
and list branches recurse without modifying the normalized data. Existing numeric
type/minimum/integer/kind validation and canonical serialization remain unchanged.

- A1: `test_A1_nonfinite_declared_numbers` covers all three nonfinite values in
  delay_hours, resolution_m and min_distinct_vessels. No accepted object or
  OverflowError satisfies the assertions. `test_A1_types_and_integer_fraction`
  preserves boolean/string/container and invalid integer-fraction refusal.
- A2: `test_A2_nonfinite_kind_edges_with_null_or_finite_base` covers all three
  fishing kinds and each nonfinite edge with both null and finite bases, before
  ratio arithmetic. `test_A2_nested_nonfinite_extensions` covers a direct value,
  list, nested object/list and normalized tuple; no nonfinite number can survive
  anywhere in factory-produced canonical parameters.
- A2 positive/compatibility: `test_A2_null_limits_and_kind_edges` checks explicit
  null admin pass-through and a finite fractional edge without a base.
  `test_A2_kind_type_and_kind_rules` preserves existing type and kind refusals.
- A3: `test_A3_minimum_boundaries_and_valid_fractions` covers each minimum, an
  immediately lower invalid value, legitimate finite fractions and integral
  floats. `test_A3_exact_multiples` checks same-edge and coarser exact multiples
  (including fractional base), and rejects below-base/nonmultiples.
- A3: `test_A3_canonical_hash_and_input_immutability` asserts literal canonical
  bytes including a finite extension, SHA256 prefix, ordering independence,
  nested immutable mappings, threshold wrapper and unchanged original mapping.
- A4: `test_A4_primary_nan_delay` captures return/exception as data and asserts
  ValueError naming delay_hours. The pinned module instead returns parameters;
  its exact named failure is SP75_PRIMARY_NAN_ACCEPTED.
  `test_A4_healthy_control` independently checks grid/1000m/24h/two-vessel output,
  and also executes the finite A2/A3 compatibility assertions above on both
  baseline and repaired modules. These same test/fixture bytes are used red and
  green. The synthetic fixture shape derives from the factory and existing
  `test_fleet_events.params`/`ResolutionByKind` interfaces, not live fleet data.

## Reproducible offline acceptance

Run `python3 scripts/accept_sp75_aggregate_finite.py --suite PHASE --output
../out/author-PHASE` from the staged repo. PHASE is baseline, focused, regression
or repository. Every invocation uses a fresh unique child directory; output
outside the isolated candidate out tree is refused. Receipts contain literal
argv/cwd, source/test/fixture/launcher/manifest hashes, head/base, runtime version,
structured counts and complete raw-output paths/hashes. Assertions run against
complete actual modules, not copied functions.

The operator-owned SOURCE-MANIFEST.json one level above the repo must name the
pinned staging base, and git ancestry is checked. Python tests use the staged
`.venv/bin/python3`; repository runs the unchanged `scripts/check_repository.py`
via the file child entry under the manifest-approved credential-scan Python.
There is no runtime fallback or installation. System Python only orchestrates.

Before tests import targets, the launcher statically resolves and hashes local
import closure (including package initializers and nested imports), checks literal
required unittest selectors and verifies all unowned closure bytes against the
staging base. Tests cannot contain child-command sites. The transitive config
adapter closure includes a dormant forecast node sampler, never invoked by these
selectors; a fresh-process audit hook forbids all target child processes,
network/DNS operations and model-client imports. It also confines target writes
to the unique run directory. The inspected HTTP module has declaration-only
import behavior; its fetch/default-session/cache APIs are additionally disabled
before test imports. SKIPPERCAST_ROOT is the isolated repo before path constants
and bound defaults are formed; inherited other SKIPPERCAST settings are removed.
TMPDIR/tempfile output is confined to the run and bytecode is suppressed. No
selected suite calls AIS stores, provider adapters, fetch functions, model APIs,
or cache APIs. These are defense-in-depth sentinels, not a hostile-code sandbox;
normal direct test discovery does not install persistent hooks in peer suites.

Regression runs exactly the unchanged selectors:

- tests.unit.test_fleet_events.AggregateTest
- tests.unit.test_fleet_aggregate.ResolutionByKind
- tests.unit.test_fleet_aggregate.LegacyKinds

Missing imports/selectors, zero tests, unexpected skips, expected failures,
unexpected successes, boundary attempts or mismatched counts cannot be green.
The expected-red baseline requires the exact pinned product SHA256, exactly two
cases, only the named primary failure, captured returned-object outcome, one
healthy pass, child exit 1, zero errors/skips and wrapper exit 0. A setup/import
failure cannot qualify. Historical red evidence is not final acceptance.

## Evidence and authorship

The first worker's incomplete uncommitted Luna material and old receipts remain
preserved outside the repository. No Luna commit existed at continuation. Sol
reworked the launcher/tests/note and replaced the inherited product edit with the
minimal full-tree validation above. After freezing all tests, Sol restored the
pinned product bytes and ran a fresh honest baseline; no earlier receipt was
rewritten. Test and fixture hashes must match that fresh baseline and final
focused evidence. The finite compatibility assertions passed both on the pinned
factory and the repair. Actual author runtimes and exact evidence locators are
supplied in the same-card review packet; shared .venv exclusion is operator
staging, not a product edit.

Final scoped success remains REVIEW REQUIRED by the sole independent Opus
reviewer. Full-repository CI, the PR, required exact-head checks and shipping are
OWED by the operator. This is no semantic/legal acceptance, live authorization,
publication permission or release/hold change.
