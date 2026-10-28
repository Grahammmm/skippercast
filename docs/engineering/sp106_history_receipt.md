# SP106: bind annual NDBC checkpoints to their requested producer

Specification: SP-10-v1. Base: `2979d59bfbb7d724eb83b34a48102b914ee8eaa3`.
Material author: actual `gpt-6.1-sol`, provider `openai-codex`, profile
`sol-reviewer`, author run 1712. No diagnostic implementation was copied, no
material was delegated, and the previous Luna attempt made no material commits.
Sole independent reviewer: actual Claude Opus 5.5 on `opus-coder-bopus`.
This note is a contract and evidence guide, not a release approval.

## Contract delta

Previously `annual_receipt` could reuse a hash-valid object referenced under the
requested checkpoint mapping key even if the receipt belonged to another station
or year. Body integrity did not establish producer identity.

Reuse now requires a receipt object with all of the following:

- `outcome == "ok"`, `role == "annual"`;
- a genuine integer `year` equal to the requested year (not bool, float or string);
- the exact canonical `annual_url` for the requested station and year;
- a lowercase 64-hex SHA256;
- the exact canonical `ndbc/stdmet/{station}/{year}/{sha256}.bin` object key,
  retaining the existing accepted key grammar;
- the existing matching-body hash and successful decoding.

Missing, malformed or mismatched metadata is a cache miss, not a metadata type
exception and not an observation for the requested producer. Only the metadata
reuse gate changes. The existing fetch path, immutable content-addressed names,
HTTP options, decoding budgets, explicit revalidation and error recording remain.
No migration, archive deletion or live acquisition is performed by this change.
As before, a hash-valid but undecodable cached gzip raises its decoding error;
this patch does not silently refetch it or change scientific parsing.

## Case-to-claim mapping

All new tests are `RegressionTests` in `tests/unit/test_sp106_history_receipt.py`.

| Row | Named assertions |
| --- | --- |
| A1 | `test_primary_regression` seeds a fully hash-valid other-station receipt under `46215:annual:2025`, then requires exactly the requested literal URL, existing HTTP options, a correctly bound replacement and unchanged old bytes. `test_healthy_control` returns the exact original receipt object without requests. |
| A2 | `test_metadata_*` individually varies each committed mutation in `metadata.json`, removes every required field, and supplies non-object receipt values. Well-shaped alternate keys contain hash-valid body bytes. Other fields remain valid; malformed values must not produce incidental TypeError or KeyError. Each named case asserts the exact refill identity and retained original object bytes. Invalid hash metadata necessarily cannot attest body integrity; all surrounding producer fields and original body bytes remain valid. |
| A3 | `test_missing_body_refills`, `test_corrupt_body_refills`, and `test_revalidate_fetches` check miss/revalidation behavior. Separate missing/corrupt/revalidate failure cases check canonical request/error recording and retained bytes. `test_failure_never_returns_mismatched_bytes` proves a failed replacement cannot expose the mismatched body. `test_refill_checkpoint_restart_is_zero_request` saves and reloads a successful checkpoint. Gzip fetch/cache and fetched/cached decoding-failure cases preserve decoding behavior. |
| A4 | Baseline runs only `test_primary_regression` and `test_healthy_control`, unchanged from the final tests. The corrected-behavior assertion must fail semantically on the original pinned product while the healthy control passes; no error or skip is accepted. The child exits 1; the wrapper exits 0 only for this precisely recognized historical defect. |

Compatibility mode loads these original selectors literally, without changing
source tests or their transitive fixtures:

- `tests.unit.test_ndbc_history.NdbcHistoryTests.test_unchanged_archives_download_nothing`
- `tests.unit.test_ndbc_history.NdbcHistoryTests.test_corrupt_gzip_fails_only_its_year`
- `tests.unit.test_ndbc_history.NdbcHistoryTests.test_recent_mode_keeps_published_baseline_and_fetches_only_recent`

## Portable execution and safety

Invoke `python3 scripts/accept_sp106_history_receipt.py --suite MODE --output OUTPUT`
from the staged repository. MODE is `baseline`, `focused`, `regression` or
`repository`. OUTPUT must be beneath this candidate's `out` directory, which is
outside the repository. Every invocation creates a new unique child and preserves
raw stdout/stderr, named results, actual argv/cwd/interpreter/version, source and
fixture hashes, HEAD and operator source-manifest hash. The manifest is read from
the candidate root, the repository's parent, not from inside the repository.
It is never fabricated or modified by the helper.

Tests run under the staged `.venv/bin/python3`; the manifest-qualified shared
venv link is the sole allowed runtime-link exception. Repository scanning runs
under `runtime.credential_scan_python3`, without fallback. Its actual process argv
is the helper's isolated `--child repository` invocation; that child executes the
unchanged `scripts/check_repository.py` entrypoint with `runpy` and records its
entrypoint argv separately. The scanner's real exit and checked-file count must
pass. Neither invocation is represented as a direct scanner-process argv.

Before product/test imports the isolated child disables bytecode writes, creates
a synthetic temporary root beneath its unique output child, redirects package
root and HTTP-cache settings, and installs audit tripwires for sockets, DNS,
process execution and therefore common network/model-client paths. Real HTTP
Session requests are additionally refused after import and before tests. Target
and HTTP module locations and package/fixture roots are checked against the
staged checkout. `annual_receipt` and `collect` require explicitly passed cache
roots; neither has a bound operational path default. Original selected tests were
inspected: each creates its own TemporaryDirectory, passes its cache explicitly,
and uses FakeSession; no database sink is constructed in this selected closure.
The fixtures and output ancestry reject symlinks. Tripwires are mistake detectors,
not a hostile-code sandbox. No real HTTP, loopback server or operational CLI runs.

Ordinary test discovery does not install audit hooks or patch global networking.
Per-test environment changes are scoped and restored, and each test's temporary
cache is cleaned only within that test's owned lifetime. Acceptance redirects the
stdlib temporary root before importing any test. It never cleans retained evidence.
Producer endpoint literals are inert fake-client assertions, not destinations;
all bodies and metadata cases are synthetic. Invented URLs use example.invalid.

## Evidence finalization and limits

Keep the historical baseline receipt; never rerun baseline against the repair or
rename its red child result as product acceptance. After a signed-off commit,
rerun focused, regression and repository modes on the clean exact HEAD.
`--freeze --output OUTPUT --receipt BASELINE_RECEIPT --receipt FOCUSED_RECEIPT
--receipt REGRESSION_RECEIPT --receipt REPOSITORY_RECEIPT` checks those receipts,
raw-output hashes, unchanged test/fixture bytes since baseline, final clean HEAD
and diff-check, then creates a fresh evidence manifest and scoped diff/commit log.
It does not rewrite or reseal any receipt. Reviewer reruns use separate output
roots; `--actor` labels the declared invocation actor, not independently attested
model provenance. The material-author field stays fixed to the actual builder.

Scoped green is REVIEW REQUIRED. Full-repository tests, PR publication, exact-head
required CI and eventual release remain OWED to the operator. No push, merge,
live run, deployment, scientific/legal acceptance, source/live hold release or
service/profile change is supplied by this local work.
