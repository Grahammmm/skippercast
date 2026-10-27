# Coast campaign shared contracts (rev4 / B1a)

This directory is a script-local contract library, NOT an installed Hermes skill.
There is intentionally no SKILL.md and no product import. No helper downloads,
changes Store state, publishes, selects a model route, or deletes campaign data.

## Specification and scope

Admitted source: coast-skills-design-rev4.md, SHA256
c8fabf7e2e1451af762ee9c9e52c32cab5831877e34cae3f7a5a98b00bb6d433.
references/contracts.md reproduces sections 3–6 verbatim. The layout reference
reproduces sections 1–2 with one portability substitution: the host-specific
interpreter home prefix is $HOME. The historical design's routing prose is not an
operational route grant; the operator's current authorization always controls.

Schemas describe workflow receipts, not scientific acceptance. The validator
checks schema, reference bytes, supported graph edges and structural consistency.
It cannot authenticate a board handoff, qualify a model, decide scientific quality,
or authorize archive closure/release. Workflow owners must perform their own
semantic acceptance checks. In particular an empty sample, a held run or a valid
corrective verdict is not a clean map. The synthetic graph intentionally has no
successful map, authorized reviewer pair, actual model call or release candidate.
Its opaque evidence leaves are explicitly synthetic; no native scientific output
is claimed. More complete producer/consumer smoke tests belong to B1b–B2.

## Helpers

Run scripts with the card-bound existing interpreter, from the pinned worktree.
jsonschema (the repo test extra) is required. All commands are offline.

    "$SC_PY" skills/coast-campaign-shared/scripts/validate_coast_receipt.py \
      "$RECEIPT" --roots "$ROOTS" --root-id "$RECEIPT_ROOT_ID" \
      --allowed-root-id "$QUEUE_ROOT_ID" --allowed-root-id "$REPO_ROOT_ID" \
      --allowed-root-id "$ARCHIVE_ROOT_ID" --allowed-root-id raw:campaign
    "$SC_PY" skills/coast-campaign-shared/scripts/validate_coast_receipt.py --hash-dir "$DIRECTORY"
    "$SC_PY" skills/coast-campaign-shared/scripts/coast_ledger.py verify "$LEDGER"

Only include admitted roots actually needed by this invocation; repeat
--allowed-root-id for each. These IDs must come from the card, not from the roots
file being validated. The CLI returns 3 for invalid/unresolved evidence. A return
of 0 is structural validation only; the JSON result explicitly says
scientific_acceptance=false. Schema-only checks are an internal API, not a CLI
escape hatch for full-graph validation.

Script-local public APIs:

- coast_refs: canonical(value), object_digest(value), sha256(bytes), loads(bytes),
  Resolver(bindings, allowed_root_ids=...), read(Ref), native_ref(value, queue_id),
  write_once(path, value). New file JSON includes a newline; object digests do not.
  Root bindings are absolute and disjoint; every root/path component is no-follow.
  A symlink, nonregular leaf, bad hash/size, unknown root or traversal refuses.
- validate_coast_receipt: validate(value, resolver, root_id=...). No opt-down flag.
  Only typed integrity-error unions select identity_snapshot context edges;
  expected/observed packet objects are observations, not recursive file refs.
  Normal graphs cannot use the exception. Unsupported native JSON schemas/slots
  fail closed as unresolved-reference, never silently lose provenance. The native
  adapter registry is explicit and byte-preserving; add support only with tests
  against the real producer shape. Archive remapping is owned by B1d; there is no
  automatic fallback to the live hot tree in this helper.
- coast_ledger: append(path, payload, writer=..., resolver=..., root_id=...),
  append_index(segment_path, campaign_path, payload, ...), verify(path).
  Payload omits seq/prev_row_sha256. Only write_verdict.py/verdict and
  archive_segment.py/archived pairings are accepted. The writer argument records
  ownership; it is not an OS capability. Use existing permissions and exclusive
  controllers. Same key/same immutable payload returns the exact existing row;
  changed payload refuses. append_index is recoverably idempotent, NOT a two-file
  transaction: a failure after the first append must be reconciled with identical
  inputs by the same writer before any acceptance announcement. Each file has its
  own sequence/hash chain, and the campaign index pins the segment line hash.
- coast_sample: window_key(source_id, grid_sha256, idx), window_dir(window_key),
  sample(map_done, eligible, plan_sha256=..., bridge_sha256=...). Caller proves
  eligibility against verified T1/T2; the helper clamps, ranks and returns sorted
  keys. The CLI reads an explicit JSON of those inputs.
- coast_tiles: neighbours(idx, cols, rows, total). Match source SHA and grid SHA
  before calling; no adjacency between independent one-window grids.

## Config and generated fixtures

config/tier2-thresholds.json has immutable versioned defaults and history. Consumers
pin full bytes and never tune per run. config/tier2-thresholds.schema.json checks
its shape. config/review-routing.json is an operator-required template with NO
qualified reviewers or permitted pairs; it cannot grant a stale profile alias or
silently substitute a held route. Supply a reviewed runtime-provenance-pinned
actual-model policy before semantic sign-off.

The reproducible schema/fixture source is tests/coast_contract_factory.py:

    "$SC_PY" tests/coast_contract_factory.py
    "$SC_PY" -m pytest -q tests/unit/test_coast_contracts.py tests/contract/test_research_boundary.py

Optional --design ABS copies the reference excerpts only after verifying the
admitted SHA. All eleven original rev3 families plus rev4 context/open-report
families have committed synthetic valid/invalid instances (13 pairs). Every Ref
has a real full-byte hash. A separate diagnostic fixture deliberately records a
bad downstream run EXPECTATION, demonstrating corrective validation without
trusting the failed scientific chain. Do not use fixture routing as real policy.
Fixtures are deterministic and contain no private host paths.
