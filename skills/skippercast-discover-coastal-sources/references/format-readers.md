# Format preflight and bounded retained samples

For an explicitly owner-assigned 60-minute acquisition/quality iteration, select
`discover.py CHECKPOINT init --profile acquisition60` with the usual region,
plan, source/policy revision and actual UTC start. This fixes 50 productive
minutes plus ten cleanup minutes; total transfer allowance remains 250,000,000
bytes. The default `discovery30` profile remains 25+5 minutes. Neither profile
can renew an initialized checkpoint. Keep the external cgroup supervisor, run
one authorized live trial only, and stop early when the selected path is held.

Before starting the live clock or acquiring a format, test its reader with
synthetic fixtures. Native decoding of a retained real survey belongs inside
the live allowance. File identity/hash checks and reader preflight do not imply
native quality. Do not download bytes behind a known missing reader.

```bash
python <skill>/scripts/quality.py preflight --reader-receipt /private/reader-runtime.json
```

The optional GSF reader is a thin `gsf_probe.c` adapter to the original upstream
MB-System-bundled GSF 3.11 LGPL-2.1 library. Pin the official source revision,
license/source receipt, compiler command, adapter source and binary hashes.
Do not vendor the full application or write a binary parser. Build against
`gsf.c gsf_compress.c gsf_dec.c gsf_enc.c gsf_indx.c gsf_info.c`, using existing
compiler availability with `-DUSE_DEFAULT_FILE_FUNCTIONS -lm`. The upstream
human-readable dump utility is unsuitable: no prompts, rounded output, indexed
side effects or error-loop continuation enter this workflow.

Runtime receipt fields: `schema:gsf-reader-v1`, `gsf_version:3.11`, exact
`source_revision`, absolute `executable`, binary `sha256`, and `adapter_sha256`.
Keep source-receipt hash and license alongside them. Preflight verifies pins and
returns readiness or the exact reader hold; it never executes a survey read.

Use the official API's synthetic writer mode for offline checks only:

```bash
gsf_probe --fixture /private/synthetic.gsf
gsf_probe /private/synthetic.gsf 100 10 100 WEST SOUTH EAST NORTH
```

The adapter uses sequential `GSF_READONLY`, never indexes. It stops on EOF,
decode error or hard record/ping/beam limits: 10,000 / 2,000 / 1,000,000 maximum.
Only finite depths with explicitly clear ping and beam flags count as valid.
Ignore flags exclude data; application-specific nonzero flags or missing flags
remain unknown rather than good. A zero depth is not automatically invalid.
Processing parameters retain at most 16 strings of 256 bytes with explicit
truncation status. Depth metres and navigation degrees come from the pinned
GSF API contract. Never infer horizontal CRS, vertical datum, tide/depth
corrections, grid resolution or actual sounding support from library defaults.
Raw processing parameters are evidence to review, not automatic acceptance.

Native selection uses vessel navigation within the assigned bbox. That is not
a sounding footprint: beams may extend beyond their vessel positions. Empty
navigation-selected results are a bounded-scan hold, not proof of source
nonoverlap. Limited scans preserve unexamined records and cannot certify a file
or survey. No beam position reconstruction, gridding, mapping or rendering is
performed. The existing source/quality and v2 handoff distinctions remain.

Gzip is the only supported compressed wrapper. Expansion stays inside owned
scratch with a 128,000,000-byte and 200x compressed-size cap, the same inspection
deadline, and no extra-byte probe at a cap. Corruption, CRC failures and ceilings
stop cleanly; no archive member extraction or generic zip/tar reader exists.
The upstream reader has a one-MB output-file ceiling, inherited memory/file
descriptor bounds, parent timeout and external cgroup. Parent cleanup kills the
owned worker/reader process group and removes scratch even when the worker dies.
The original compressed sample remains unchanged and its hash stays primary;
expanded hash/size are additional evidence, not a replacement source identity.

Reuse retained bytes without reacquisition only after scoped source import:

```bash
python <skill>/scripts/quality.py NEW_CHECKPOINT import-sample \
  --source SOURCE_ID --manifest OLD_MANIFEST --request OLD_REQUEST_ID \
  --binding ORIGINAL_VERIFIED_LINEAGE_BINDING
python <skill>/scripts/quality.py NEW_CHECKPOINT inspect \
  --source SOURCE_ID --imported-sample 1 --reader-receipt /private/reader-runtime.json
```

`sample_imports` validates the exact old manifest, source digest, original
request, bytes/hash and lineage, retaining all references. It does not add an
HTTP request, inherit old budgets or charge reused bytes as a new transfer.
At most four imports; duplicates keep their identity. Changed bytes, expired
source evidence or mismatched lineage stop reuse. Fresh acquisitions continue
to use `--sample-request` and the same verified binding rules.

Quality method `format-native-observation-v4` pins this reader-aware method and
the explicit bounded-scan hold classification.
Older native/metadata receipts remain historical evidence; source leads and
verified retained bytes can be imported, but stale quality does not become a
new assessment. The reader receipt participates in attempt identity, and current
attachment validation checks its binary/adapter pins. Do not reset unchanged
sample/method/source attempts or create another live cycle to resolve a hold.

GSF `scan_hold` distinguishes a limit before the first ping, EOF without pings,
no navigation-selected pings at EOF versus a partial scan, and selected pings
without flag-valid finite depths. Each hold records a specific next action using
existing evidence. A navigation-selection hold never establishes sounding
nonoverlap or whole-source quality. With zero scanned beams, scan yield is null,
not a measured zero. Historical v3 quality receipts remain immutable and fail
current-method attachment validation; source facts and sample bytes remain
eligible for their existing scoped reuse checks. There is no automatic migration
or reinterpretation of old quality. This revision does not authorize another
inspection or live cycle.
