## 1. Identity, filesystem and environment

### 1.1 Identity mapping

campaign_segment_id is a package label such as C1-morro-bay. It is NEVER supplied as Store.segment_id. campaign.json freezes campaign extent, lane, source inventory and the intended source-grid window population. A coordinator record is emitted by coordinator.segments.from_bbox(campaign bbox, region=campaign_segment_id); its id is seg:3310:<x>:<y>:5000, bbox is the exact EPSG:3310 5-km lattice rectangle, bbox_crs84 is the inverse densified transform supplied by that function. Preserve the full record, not a hand-typed bbox. Validate schema/crs/id/projected bbox and recomputed bbox_crs84 before enqueue; Store still enforces its existing gate.

The admission helper reads bounded, cached raster metadata (not downloading) and a reviewed tiling selection. Each source grid has a grid_sha256 = canonical object digest of {source_sha256, raster_crs, affine_transform, width, height, tile_width, tile_height, tiling_version}. idx is global row-major index in that fixed source grid, not reset per plan, campaign or lattice record. For the pre-PC-6 single selected window, use a one-window grid whose digest includes that exact pixel window; idx=0. Never infer adjacency between independent one-window grids.

Assign each selected window to ONE coordinator record using its pixel-window centre transformed to EPSG:3310; owner origin is floor(x/5000)*5000, floor(y/5000)*5000 (half-open lattice, including negative coordinates). Its actual footprint must positively overlap the admitted campaign extent and the owner record; record the bounded footprint and all overlapping lattice IDs for coverage accounting. If the owner is not in the frozen campaign record set, admission holds for an explicit corrected campaign inventory; do not substitute a record. Windows crossing lattice edges remain intact native pixel windows: owner is scheduling identity, NOT a claim that mapped support is clipped to that record. Measured footprint/support is what coverage reports. No raster resampling, silent duplication or coverage extrapolation. Each window appears once in the intended inventory and once in exactly one owner group; leftovers/holds remain listed. This separates scheduling geography from native-grid coverage without weakening a gate.

Partition proposed windows by owner record BEFORE making bridge plans. A plan uses exactly one record and a subset of that owner's windows within installed bridge caps. Current baseline: <=4 distinct source selections, one window each, total <=2 GiB, <=262144 cells/window, <=3600 seconds/job, requests=0. Repeated tiles from one source and N=16/64 plans are HELD on reviewed PC-6 support; never simulate them by raising MAX_JOBS or splitting invisibly. Every split is a distinct admitted plan with recorded remaining inventory. PC-6 adapter must retain global grid identity and index; incompatible merged shape is a design reconciliation, not permission to guess.

Within a plan window_key = source_id + '#' + grid_sha256 + '#' + decimal idx. Global coverage key = (campaign_segment_id, source_id, grid_sha256, idx); ledger identities additionally include plan_id and plan_sha256. Source IDs are data, never path components. Per-window directory window_dir = SHA256(UTF8(window_key)); record its reverse mapping in admission. This avoids slash/colon/traversal and exFAT filename problems.

plan_id is a safe human directory label, not authoritative content identity. plan_sha256 means the existing bridge's digest(plan object): canonical compact sorted JSON WITHOUT newline (handoff.common.digest). plan_file.sha256 means full bytes on disk, including any newline. They need not equal. Exact execution binding = campaign_segment_id + coordinator_segment_id + plan_sha256 + bridge_receipt file SHA256 + enqueue_receipt file SHA256. All tiers inherit these from a verified admission/round context. A plan-content/source/grid/record change requires a new plan_id and admission; a review-only correction increments round/attempt for the same plan. Record replacement_plan_of for changed plans so readiness counts the original inventory once, never both attempts as extra successes.

### 1.2 Layout

COAST_ROOT is the existing campaign root outside git. C = COAST_ROOT/<campaign_segment_id> is the queue root shared by that campaign's plans. Region-level budgets and pressure remain shared within its Store; do NOT create per-plan Stores to reset budgets. Do not import or migrate old queues silently.

C/campaign.json
C/cache/<safe source dir>/<file>                         regular hot input copies
C/discovery/<disc-id>/{plan.json,dry/,run/}
C/plans/<plan-id>/{plan.json,segment.json,admission.json,dry/,bridge/}
C/plans/<plan-id>/bridge/{bridge-receipt.json,native-job-NN.json,enqueue-receipt.json}
C/plans/<plan-id>/runs/run-NN.json                       immutable continuation snapshots
C/plans/<plan-id>/review/rNN/aNN/context.json            immutable round/attempt root
C/plans/<plan-id>/review/rNN/aNN/tier1/{stats.json,text.json,vision.json,flagged-windows.json,windows/<window_dir>/hillshade.png}
C/plans/<plan-id>/review/rNN/aNN/tier2/{rehash.json,budgets.json,neighbours.json,review-packet.json,review-packet.md}
C/plans/<plan-id>/review/rNN/aNN/tier3/{open-report.json,decisions.json,verdict.json}
C/var/coastal/coordinator.sqlite                        existing Store, fixed DB path
C/var/coastal/jobs/<job_id ':' -> '-'>/<lease>/...         existing producer layout, unchanged
C/ledger.jsonl                                          new campaign workflow ledger, NOT pipeline retention ledger
C/close/<close-id>/{release-list.json,release-receipt.json}
COAST_ROOT/campaign-ledger.jsonl                         independently chained index
ARCHIVE_ROOT/<campaign_segment_id>/<close-id>/            archive instance
ARCHIVE_ROOT/raw/                                       existing raw mirror; read-only here

Queue policies/Store paths are fixed, not arbitrary CLI options. Application artifact path components are [A-Za-z0-9_-]+ except fixed filenames and scientific producer paths; require relative POSIX paths without empty, '.', '..', backslash or NUL components. Actual filesystem roots are operator-selected absolute paths, not addresses read from untrusted receipt data. Every output is O_EXCL/write-once; crashes leave partial evidence, never permission to overwrite. New attempt directories replace failed attempts.

### 1.3 Environment for every skill

The card supplies SC_REPO (a pinned task worktree on AgentOrange), SC_PY (the existing repo shared venv), COAST_ROOT, ARCHIVE_ROOT, RAW_MANIFESTS and the exact expected code commit. Confirm git rev-parse HEAD and SC_PY before use. Do not hard-code a worktree-local .venv or install one. This design's executed baseline uses $HOME/repos/skippercast/.venv/bin/python. No cloud/Mac clone substitution. Execute from SC_REPO with PYTHONPATH=src. All CLI file arguments are ABSOLUTE; --root does not resolve catalog_bridge --plan/--catalog/--out. Helpers use script files, never python -c/heredocs. Shell variables below are card-bound absolute paths:

C campaign queue root; P=C/plans/<plan-id>; D=C/discovery/<disc-id>; R=P/review/rNN/aNN;
RUN=P/runs/run-NN.json; CTX=R/context.json; CFG=SC_REPO/skills/coast-campaign-shared/config;
ROOTS=absolute operator root-bindings JSON; A=ARCHIVE_ROOT/<campaign_segment_id>/<close-id>.

ROOTS contains root_id -> absolute root bindings for queue:<campaign_segment_id>, repo:<code_commit>, archive:<campaign_segment_id>:<close-id>, raw:campaign. It is deployment metadata, not authority to read arbitrary paths. Helpers accept only the card-admitted roots and reject unexpected or overlapping bindings. Do not publish absolute private host paths in repo fixtures.

## 2. PC-9 execution and safety contract

Use the real catalog_bridge APIs, Store APIs and Coordinator.tick with reconcile=True. Never copy Store gate logic to bypass it, use Coordinator.run(max_jobs=N), call recover automatically, or tick render.

Enqueue takes --root C --bridge-receipt ABS --segment ABS --admission ABS --out ABS. Validate all pins and identities before Store changes. Full segment record must equal plan.segment ID/bbox binding and existing record if present. Hold controller_lock at C/var/coastal/coordinator.lock (same path as Store.path.with_suffix('.lock')). All PC-9 writes/ticks use this lock. Operator precondition: no other writer/controller for this campaign queue except this driver and its own tick heartbeat; a lock does not exclude arbitrary actors that ignore it. If ownership cannot be established, refuse execution, do not start an alternative Store. Status is read-only and does not create a Store.

Before enqueue and BEFORE EACH tick, read-only preflight under the controller lock:
  - Imported code/deps identity must still equal the enqueue binding. All job records in the WHOLE Store must carry that same current code/deps pair (conservative even for foreign terminal rows).
  - No row may be stale, claimed, running or failed_uncertain; no leases may exist, expired OR unexpired. This is checked for all segments/stages, including foreign acquire/render. No unknown state/contract is allowed. Refuse a sourcefree/authenticated mission policy or foreign execution contract in this generic bridge queue.
  - For run, prove lineage and input hashes first. Every plan root must exist with the recorded ID/manifest/segment/code/deps; no unregistered acquire root for that exact receipt. Check stage-frontier classification below.
  - Failure writes ONLY a new external run summary with stop_reason=preflight_refused and reasons; ticks_used=0 when refusal occurs before the first tick. Do not call invalidate, expire, claim, add_segment, recover, event or any write API on refusal. Existing Store SQL rows/events/leases/charges remain byte-for-byte equivalent logically. Opening for preflight must use read-only SQLite, not a constructor that creates/migrates the DB. After clean preflight use the ordinary Store with unchanged packaged policy.

Why safe: with every record at the current identity there are no invalidation seeds; with no leases there is nothing to expire. Normal tick gates remain enabled. The driver is the exclusive controller during the tick; it waits for the tick/heartbeat to finish before the next preflight. Existing foreign current queued/render jobs are not claimed by the ID filter. A foreign old implementation or lease is a REFUSAL, not a tolerated background mutation. Recheck after every tick that foreign rows/events/leases are unchanged; an unexpected difference is failed_uncertain, not success. This detects violated exclusivity but does not pretend to roll back an already-run stage. Operator recovery of contaminated/old queues is separate work; do not weaken safety to keep running.

Enqueue's durable intent is a write-once sidecar keyed by bridge_receipt SHA256 BEFORE first Store insertion. Validate all native manifests before that point. Detect second invocation from intent as well as final receipt; refuse it. A crash between intent and receipt leaves partial roots and requires explicit reconciliation, never automatic enqueue retry. Root IDs are taken from actual Store.enqueue returns; new_row is derived by comparing the root-ID set before/after, NOT SELECT changes() after Store.event (which changes that connection count). No fabricated plan_id field is read from the bridge receipt.

Lineage: from root IDs, follow only next_job.input_manifest in the HASH-VERIFIED committed result of a predecessor with state done, matching exact manifest path/sha/bytes, next stage and same segment/code/deps. Path must be inside that predecessor's recorded job directory/lease output; whole path components, never a raw string prefix. Cross-check Store child record and idempotency identity. Reject ambiguous/multiple successors, wrong stage, foreign-owned input, missing or changed result; do not adopt a row simply because its input has a similar prefix. Render successors can be recorded but never run. Lost or unclassifiable lineage produces integrity failure, not frontier_empty.

Select queued permitted lineage jobs deterministically by (window_key, stage order, job_id); tick one by ID. A returned idle triggers re-read: Store may have held the target before dispatch. Classify all windows using their deepest known state, with this exhaustive partition:
  map_done; held; failed_terminal; failed_uncertain; stale; cancelled; unfinished.
Stages missing because predecessor has not completed are not successful. queued/not_before in future, claimed/running, retryable waiting, or no claim under pressure are unfinished with reason. failed_retryable is retryable ONLY as the Store makes it claimable and within original max_attempts; no driver-created retry. Unknown/missing successor after successful acquire/qualify is integrity_error/unfinished. stale/cancelled never become complete merely because queued frontier is empty.

stop_reason = terminal (all windows map_done/held/failed_terminal/cancelled), deadline, max_ticks, not_claimable, preflight_refused, integrity_error, failed_uncertain. A stale frontier causes preflight_refused. Successful RUN card means truthful bounded execution evidence, not semantic map acceptance. Only deadline/max_ticks/not_claimable with verified unchanged identities and no leases allow ordinary continuation. Failed_uncertain needs operator recovery; changed identities need reviewed replacement admission, not another run.

Each run emits runs/run-NN.json with sequence, continuation_of Ref or null, binding, per-window stages/results/products, the partition above, missing stage reasons, ticks_used, max_ticks, until_epoch, started/finished UTC, wall_s, usage and Store status snapshot. Counts partition ALL admission windows. Holds are copied from stage results, not inferred as quality acceptance. Sources counted once by source SHA for reporting; bridge byte-accounting gates are copied unchanged, never reduced by that report.

Continuation calls run ONLY, with the previous summary Ref pinned and sequence+1. Assert roots/manifest bindings unchanged and no new acquire roots/no repeated enqueue. Total jobs may increase by legitimate qualify/map/render successors. Acceptance test expects the actual lineage increments, not unchanged total rows. Reaching N windows normally requires acquire+qualify+map stage ticks, not N ticks. Use explicit max_ticks from the card (baseline suggested budget 5*N, still subordinate to wall/budget/attempt caps); never reinterpret that as authorization to rerun failed jobs.
