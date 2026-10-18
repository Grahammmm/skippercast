# Shared coastal pipeline contract

The implementation is `skippercast.coastal`. Use the reviewed package and existing approved environment under the repository dependency policy. Skill scripts are compatibility entry points, not separate scientific implementations. Package resources include schemas and the pinned whole-ping GSF adapter. Do not install services or change isolation, access, credentials or model routing as part of a run.

## Evidence and stages

The host coordinator stores geographic EPSG:3310 segments in SQLite, with fenced leases and input/code/dependency/parameter identities. Asset hashes identify bytes, not geographic segments. A bounded invocation is a command, not a persistent service:

```sh
python -m skippercast.coastal.cli --root REPO --db var/coastal/coordinator.sqlite status
python -m skippercast.coastal.cli --root REPO --db var/coastal/coordinator.sqlite enqueue --segments SEGMENTS.json --stage discover --input INPUT_REF.json --params PARAMS.json --budget BUDGET.json
python -m skippercast.coastal.cli --root REPO --db var/coastal/coordinator.sqlite run --until UTC_EPOCH_DEADLINE --max-jobs 5
```

Use a reviewed, bounded run specification and the current policy before enqueueing. Preserve the mission allowance across retries. The fixed stage dispatcher accepts authenticated job files; never introduce caller-supplied executable commands. An expired lease is not proof that its process stopped. Resolve uncertain process identity before retrying.

The initial coordinator lane is `discover -> acquire -> qualify -> map -> render`. Here discovery inspects a supplied frozen local catalog; acquisition verifies existing cached bytes. Receipts must say that no external request or transfer occurred. External finite discovery/acquisition use the existing host-side bounded discovery procedure and approved endpoints; the isolated worker remains network-restricted. Do not label cache reuse as a new public search or imply all catalogs were examined.

A mapping-input v2 producer reopens native data and binds the bounded window, geographic support, metadata, rights, implementation and dependencies. Its verifier recomputes facts. Independent review is a separate byte-bound attestation with identity and expiry; it is not cryptographic proof of independence and cannot override a scientific hold. Never author factual observations merely to make readiness pass.

Source sign, units, datum and scale/offset are explicit. BAG elevation storage is positive-up even when a depth coordinate axis is down. Normalized terrain is positive-down metres with scale/offset already applied; do not negate it again. Unknown or conflicting semantics stay held. Preserve nodata and unsupported holes. BAG node footprints do not demonstrate continuous measurements between nodes. Derivatives require supported native spacing and geometry.

Render v2.1 distinguishes private-preview readiness from website acceptance. It requires supported terrain, rights-cleared imagery, numeric alignment with source-bound independent correspondence evidence, and separate review. Coordinate transforms alone do not prove image alignment. Geometry and texture must preserve unsupported regions; interpolation between observed nodes is visualization, not newly measured terrain. Missing imagery holds this paired-imagery lane. A separately assigned data-only
terrain preview follows its reviewed terrain-only contract and keeps imagery,
habitat and website acceptance separate.

## Runtime and preflight

Use the shared bounded runner: an independent supervisor, process identity and actual cleanup enforce deadlines. An environment variable or written deadline alone is insufficient. Keep unavailable model usage unknown and accounting conservative when receipts are incomplete. Preserve immutable bounds and stop on uncertainty instead of resetting reservations.

```sh
python -m skippercast.coastal.hermes_preflight --root REPO --out var/coastal/preflight.json --context host --skill-path SKILL_PATH
```

Optional hash-bound native fixture arguments appear in `--help`. Host imports, fixture reads, cancellation and artifact roundtrips establish only host evidence. Actual protected Hermes invocation and external artifact return require evidence from that runtime and the applicable explicit approval. Keep the durable coordinator outside a temporary gateway. A caller-provided context label cannot establish worker readiness.

## Trial and audit

Finish implementation, independent correctness/science review and any
applicable explicitly requested security review before a timed trial. Do not
start an optional security workflow merely because a private terrain task exists. First run a synthetic dataset through discovery, mapping and actual rendering, retaining deliberate mask holes and known alignment offsets. Label synthetic review packets and fixtures; never reuse them for a real source. Check every prerequisite for each authorized bounded real stage. If a gate is missing, save the hold and stop that dependent stage; do not replace evidence with a manually written receipt.

Record exact head, source/dependency identities, stage attempts, effective bounds, actual/unknown usage, outputs, independent review, cleanup and next action. Keep private receipts and bulky data outside version control. Private preview does not authorize merge, public upload, website integration or deployment. Skill corrections belong in a separate reviewed implementation revision, not in a running timed mission.


## Operating modes and bounded trial lessons

Choose a mode from the owner's requested output, and retain all its real gates:

| Mode | Required evidence | Separate downstream scope |
| --- | --- | --- |
| Private data-only terrain | Exact source/window, valid paired support, resolved storage/normalization semantics, geographic checks, private-use rights and independent science/artifact review | Imagery, habitat interpretation, rankings, fishing export and publication are optional only when requested |
| Paired terrain/imagery | Reviewed terrain plus imagery rights, independent numeric correspondence and the paired contract's review | Coordinate transforms alone cannot establish alignment or website acceptance |
| Habitat or publication | Requested interpretation/ranking and the applicable source, screening, rights and release contract | Terrain alone establishes neither habitat/substrate nor public permission |

Nominal MLLW with unknown realization stays explicitly nominal; do not invent a
realization, uncertainty calibration, VDatum transform or navigation claim.
Unknown datum realization differs from unresolved sign/units/scale semantics,
which must still hold normalization. Source positive-up BAG elevation and
normalized positive-down depth are different fields; never apply the sign twice.

**Check geometry before source admission.** A historical interest/hard-bottom
polygon is a study constraint, not NOAA's exhaustive bathymetry coverage. Its
failure to cover a proposed square does not prove source nodata. Use retained
actual affine, grid dimensions, native cell outer bounds and full or independently
reviewed conservative geometry (including holes) to test every window and margin
without reopening source arrays. Compare proposed area to the study polygon's
capacity before promising a contiguous square. If a different contained or
disjoint configuration is authorized, pin it as a distinct finite profile; never
relax a geofence, substitute its bounding box or relocate windows silently.

**Admit the complete stage, then launch.** Preparation must return success and
validate exact packet count/order/window membership, producer references,
independent reviews, code/dependency pins and the stage's resource envelope.
Failed preparation means do not launch, even when a downstream count guard would
refuse it safely. The reviewed strict bounded BAG profile requires every
side-squared raw/mask/source/normalized pair and its depth/uncertainty criteria;
missing one pair remains a factual hold. Synthetic tests and metadata alone do
not establish actual support. Independent review of registered observations and
qualified arrays remains separate from worker completion.

**Keep resource scopes distinct.** Preserve the old charged ledger and all
original receipts. An explicitly new source-volume grant is not a refund or a
physical-I/O quota. Record original source bytes streamed/hashed, sealed-copy
hashes, logical pair visits and retained regular output bytes separately, with
unknown physical I/O/disk-quota measurements left unknown. A 64 MiB output cap
cannot stand in for a source-read allowance. Reserve the complete retained stage
tree before dispatch and audit it before result commitment. A 60-minute stage or
combined acquisition/qualification ceiling is not padding: use its original
immutable mission clock, stop when the finite batch ends and authorize no extra
phases merely because time or allowance remains. Report service-unit elapsed time,
worker-supervised time and review/coordination elapsed separately.

**Measure from existing artifacts.** Verify prior/current support hashes and
compute native-grid or consistently projected mask unions without new source
acquisition or a code change solely to claim growth. Deduplicate old/new windows;
prove zero overlap rather than assuming it. Report nominal native-cell area and
equal-area projected area with their method/tolerance. Disjoint measured cores
supply neither the area of their bounding box nor continuous seam/context support.
A schema fix, pretty image or successful job adds no measurement by itself.

**Preserve provenance through source-free recovery.** Validate the original full
BoundCRS source/target/operation first, then canonicalize the physical projected
CRS of derived acceptance packets when needed by the consumer. Preserve the
original CRS, hashes and unchanged rasters; do not infer a vertical transformation
from a representation fix. Archive immutable failed plan/unit/output receipts
before a distinct bounded recovery using retained qualified artifacts. Do not
edit the frozen native export, reset native charges or reopen the source to repair
a derived metadata/preparation error.

**Name the next actual milestone.** A local catalog stage proves local inspection,
not live official discovery. A private native/map/render trial proves only its
selected artifacts. The next coordinator/producer milestone needs a real bounded
registered handoff and durable recovery evidence; the next map-loader milestone
needs actual support-hole/disjoint-core preservation; the next browser milestone
needs interaction, camera and performance evidence beyond static PNG inspection.
Continue independent authorized source-free work through an unrelated optional
habitat/imagery hold, and stop the dependent stage at a genuine missing gate.
Authenticated native execution can deliberately forbid automatic successors;
separately launched mapping/render controls do not prove an integrated coordinator
pipeline. Audit legacy native adapters for their own sign/datum behavior rather
than inferring they inherit authenticated-worker normalization.

These lessons come from completed bounded real-data and source-free recovery
receipts. Keep their exact paths, hashes, dates, failed-attempt evidence and scope
in the private self-audit/run receipt; examples do not grant current execution,
installation, deployment or publication authority.
