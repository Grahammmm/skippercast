# Held coastal discovery intake

The cached inventory CLI accepts `coastal-held-discovery-plan-v1` for retained
metadata leads that cannot honestly satisfy the existing strict
`coastal-cached-inventory-plan-v2` 2 m BAG contract. This is a private proposal
for the owner's existing tracker. It does not initialize a queue, select a
native reader, or admit execution.

## Input and output

The plan has exactly `schema`, `region`, `output_root`, `candidates`,
`metadata_bytes` (16777216), `output_bytes` (524288), `network_bytes` (0),
`source_read_bytes` (0), and `proposed_limits`. The latter explicitly names
`pending_candidates` (1–40) and `native_active` (1); neither is an allocation.
Each of 1–40 candidates is `{"lead": {"path": "lead.json", "sha256": "…",
"bytes": 123, "contract": "coastal-discovery-lead-v1"}}`.

The canonical and packaged `coastal-discovery-lead-v1.schema.json` define:

- regular or variable-resolution BAG metadata, with unknown raw identity
  represented by null SHA/bytes;
- an archive containing an unresolved GeoTIFF member, with archive identity
  kept separate from the missing native-member identity;
- unresolved scope, a proposed fixed centre, or explicit native indices;
- pending leads and closed controls with an exact retained receipt reference.

Metadata references inside a lead are retained assertions, not authenticated
scientific evidence. They are not followed. Source paths are not opened or
statted. Archive members are not enumerated. NAVD88 remains NAVD88; unknown
datum realization, uncertainty and interpolation masks remain explicit.
The fixed centre is not an accepted native window or measured support.

The existing CLI's hash/size-bound JSON reads, 128 KiB per-file cap, durable
nonrefundable admission, immutable output identity, one catalogue pass and
reuse/recovery rules also apply to the new plan. Supply its exact descriptor
and a horizon of at most 3600 seconds:

```sh
python -m skippercast.coastal.cached_inventory --root METADATA_ROOT \
  --plan PLAN.json --plan-sha256 PLAN_SHA256 --plan-bytes PLAN_BYTES \
  --out EXACT_PLAN_OUTPUT_ROOT --now START_EPOCH --horizon END_EPOCH
```

Running this command still requires the owner's applicable metadata scope.
An interrupted refused pass stays charged; a new output path cannot reset it.
The output is `coastal-held-discovery-inputs-v1`, always
`HELD_METADATA_ONLY` and `execution_authorized=false`. It is not a mapping
handoff or a list of executable jobs. The existing v2 manifest and strict
BAG checks remain unchanged.

## Candidate deduplication and proposed backpressure

Candidate identity hashes the identity namespace (native raw SHA, archive SHA,
or unresolved publisher lead ID), private-terrain purpose and exact proposed
scope. Transport URL, cache spelling, budget and code version do not create a
second metadata candidate. Different scopes remain separate candidates.
Unknown raw sources with different lead IDs are not guessed to be identical.

Every distinct descriptor and its retained evidence survives grouping. Exact
repeated descriptors are counted separately. Conflicting source facts, datum,
metadata or lifecycle add a hold instead of choosing a winning record. A group
containing any pending record counts as pending, including lifecycle conflicts.
Closed controls alone consume no pending capacity and grant no replay rights.

The output counts unique pending groups and reports whether the explicitly
proposed limit is exceeded. It preserves all leads on overflow; it never drops
the fourth candidate or silently admits the first three. Actual native-active
count is unknown, and `enforced_by_dispatch=false`. Binding a live artifact,
writer, consumer and original charge authority is a prerequisite to operational
backpressure. This metadata proposal must not become a second live tracker.

## Existing coordinator contract and execution boundary

SQLite `coordinator/store.py` remains at `user_version=3`. Existing jobs,
leases, artifact references, events, charges, authenticated missions and window
phase uniqueness are unchanged. Constructing `Store` creates/migrates state;
use the source-free inspection CLI for status so an absent queue stays absent.
No authoritative runtime queue path or writer/consumer is established by this
document or by the parameterized `var/coastal/coordinator.sqlite` example.

Execution job idempotency includes stage, segment, owned input path/hash/bytes,
code and dependencies, parameters and budget; authenticated jobs also bind
their execution contract/context. It is intentionally distinct from metadata
candidate identity. Never use a new candidate key, path or budget to reset
existing attempts, charges, mission/window uniqueness or uncertain work.

Existing dispatch pressure pauses discovery/acquisition at three
qualified-unmapped segments or five held segments, resuming at at most one
qualified-unmapped and fewer than five held. This is not a three-lead backlog
cap. `Coordinator.run` serializes its own controller, but policy slots alone
do not prove global single-native concurrency for arbitrary direct callers.

Generic native dispatch remains unqualified for a new bounded trial:
`Store._enqueue` hashes its input reference before admission, `Store.claim`
can verify native evidence before budget reservation, and generic acquire
resolves/hashes its source before its byte check. Moving one budget check is
insufficient. A future execution repair must separate metadata preflight from
charged guarded native verification at every entry, retain scientific gates,
and prove that refusal performs no native open. This change grants no generic
execution or production adoption. Existing closed private trial evidence and
the dedicated authenticated contracts retain only their original scope.
