# SP1812: measurement-based conditions availability

Acceptance specification: SP-18-v1 / SP1812-CONDITIONS-DATA.
Staged base: 67ff9bcf34257698a41585bc2ad163171dc68259.
Material author: gpt-6.1-sol high, provider openai-codex, profile sol-reviewer,
kanban t_175c2260 run 2160. Independent reviewer: Claude Opus 5.5 on
opus-coder-bopus, not the author.

## Contract and implementation

A cached timestamp does not establish forecast availability. After readHour has
applied model-error, finite-number, unit and positive primary sea-period checks,
windowConditions now requires at least one usable measurement in the sampled
window. The gate enumerates all fifteen primary/secondary measurement fields,
not Hour.time. Otherwise the existing empty-result helper returns unavailable,
unknown comfort, null summary fields and the reason
`no usable forecast measurements for this window`.

Partial availability includes zero-valued wind/direction/height samples and
secondary-model-only data when an existing primary timestamp selects the hour.
No completeness, freshness or skew threshold was added. No failed payload is
resampled outside readHour. Existing aggregation and limited-score behavior are
unchanged, including null primary summaries for secondary-only wind.

Shared-file hotspot: SP1403-TRIP-CALENDAR owns explicit date parsing in
server/advisor/answers/conditions.ts. This delta is confined to the post-readHour
measurement-availability gate; calendar parsing is unchanged. Operator ownership
reconciliation and any later merge conflict resolution remain required.

## Test-first evidence and behavior mapping

The new tests, fixtures and acceptance launcher were authored before the product
change. On the unchanged pinned source, the exact A1 semantic assertion
SP1812_A1_NO_USABLE_FORECAST failed (actual true, expected false), while the
identical-window A3 healthy control passed with wind [5,5] and seas [2,2].
Baseline child exit 1: tests 2, pass 1, fail 1, skipped/cancelled/todo 0.
Launcher exit 0 means BASELINE_GAP_REPRODUCED, not repair success.

Retained outside the repository, under candidate out/author-baseline:
20261025T140150Z-b980d0b932d54d20860918208b0331c9/receipt.json
SHA256: 59302c3e627796adaa51d992b965dd7e686e1e450193fbcd8576668c2005e680.
Baseline raw TAP SHA256:
119d262442b79a234550fa6f761584f7d83f0325eeac67d7287cbf06f3fc99e0.
Frozen test SHA256:
2d69995e51d6a306038a33ade177269b210f4986f7a3ecb7091ad9fc580c5d86.
Receipts retain source, launcher, fixture and unchanged compatibility hashes.

- A1: all model error flags with cached time arrays; exact availability assertion,
  explicit reason, unknown comfort and every summary null; wrong-region control.
- A2: nulls, invalid measurement/time units, absent/empty arrays, nonfinite
  measurements, and measurements existing only outside the requested window.
- A3: healthy identical-window control and real limited comfort rating.
- A4: one usable wind sample, missing sea and unknown comfort remain available.
- A5: secondary-only wind/gust/sea; no fabricated primary summary; secondary
  error flags still suppress these measurements.
- A6: no timestamps, wrong region, missing forecast point, date/window exclusion.
- A7: valid English/Spanish/ISO date parsing, exact Pacific window epochs and
  unchanged NWS advisory inclusion.
- Additional matrix: each of the fifteen measurement fields independently
  establishes availability; invalid units suppress it; invalid primary wave
  periods still suppress wave height. No copies or slices of product algorithms.

## Portable offline acceptance

From the staged repository cwd, run the launcher as a script file:

    python3 scripts/accept_sp1812_conditions_data.py --phase focused --output ../out/reviewer-focused

Other phases are baseline (only unchanged product source), regression,
repository, typecheck and build. Each invocation creates a unique child below
its output argument and records actual child argv/cwd/runtime, exits/counts,
raw stdout/stderr and SHA256 hashes, source HEAD/tree/status and file hashes.
The focused phase reruns the exact A1/A3 pair green, then all focused cases;
regression separately runs the unchanged advisor_tools and advisor_daily files
with positive executed counts and zero skips. Repository runs the unchanged
check_repository.py under the manifest's credential_scan_python3 via a
process-local offline bootstrap. Typecheck uses three separate pnpm exec tsc
invocations; build runs existing pnpm build locally. Explicit child exit checks
are used, not Python assert-only production acceptance gates.

SOURCE-MANIFEST.json is the standard operator staging input at the candidate
root, validated for schema/repo/base identity. No plan or sibling artifact is a
runtime dependency. Installed Node type stripping imports the full staged
modules and real scoring dependencies. The synthetic feed follows the existing
forecast.models.<model>.data[point].hourly/hourly_units producer shape; it is not
a live record. Compatibility tests use their existing migration-backed in-memory
SQLite adapter and committed static catalog/feed examples.

A process-local Node preload blocks fetch, HTTP(S), TCP/TLS, UDP, basic DNS and
WebSocket before imports or bound defaults; accidental caught network attempts
also make the process fail. New tests load it during normal isolated Node test
discovery too. Launcher children have a minimal credential-free environment;
Node child processes inherit the preload. The Python scanner bootstrap installs
an audit sentinel before executing the unchanged scanner. These are accidental
side-effect guards, not a hostile-code sandbox. No live stores or services are
required or opened. Shared runtime links remain read-only. Generated local build
outputs are excluded from source identity; retained receipts are never deleted.

## Scope and remaining gates

Scoped success is REVIEW REQUIRED, not full-repository CI or semantic acceptance.
Final actual acceptance receipts and signed-off full HEAD are supplied with the
review request, after all writers finish. Reviewer runs use different out roots.
No prior review returns exist for this initial candidate.

Operator PR publication, full-repository Python/Node discovery and qualified skip
accounting, regional/search parity, credential/privacy/link/client/copy/token
gates, audit and browser/e2e tests, exact-head CI and release remain OWED. No
scientific/legal/navigation/fish-presence conclusion is supplied. No network,
source acquisition, publication, live execution, source/live/bulk-download or
other existing hold release, service/profile change, push, merge, force-push or
extra deployment is authorized by these results.
