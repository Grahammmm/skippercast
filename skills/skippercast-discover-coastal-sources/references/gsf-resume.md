# Bounded sequential GSF resume

Use this separate path only for an explicitly assigned retained-sample scan or
new authorized quality task. It does not reopen a finished discovery checkpoint,
start a live trial, raise historical limits, download data or change source
acceptance. An owner-authorized offline saved-data regression can use a fresh
standalone checkpoint and its own short fixed allowance; that is not general
permission to inspect other samples outside an assigned task.

The upstream GSF reader retains scale factors between ping records. `gsf_scan.c`
uses `GSF_READONLY`, reopens at the beginning, and sequentially replays the exact
committed record count to reconstruct this state. It never raw-seeks, creates an
index, or treats a partially observed ping as consumed. A ping that cannot fit
the remaining beam allowance is left uncommitted for the next chunk. A ping
larger than the whole beam allowance is a terminal hold.

The historical `gsf_probe.c`, reader receipt, one-shot quality method v4 and its
CLI remain compatible. The new `gsf-sequential-replay-v1` method emits a separate
`gsf-resumable-observation-v1` receipt. It never automatically attaches to the
source manifest, mapping handoff or v2 display acceptance. Each committed chunk
retains depth statistics, processing parameters and the numeric navigation
selection; the final receipt aggregates counts only and points to these chunks.
Unknown horizontal/vertical datum, sounding support and grid resolution stay
unknown. A navigation-selection miss is not proven sounding nonoverlap.

## Runtime pin and commands

Compile a distinct binary against the six already pinned upstream GSF 3.11
sources, retaining their LGPL notices. Use `-DUSE_DEFAULT_FILE_FUNCTIONS`,
`-Wl,--wrap=fread` and `-lm`. Do not overwrite a prior reader binary. The runtime
JSON uses `schema: gsf-resume-reader-v1`, `gsf_version: 3.11`, exact
`source_revision`, absolute `executable`, executable `sha256` and
`adapter_sha256`. Preserve the source receipt, build command and license there.
A changed binary, adapter or runtime receipt invalidates resume.

Run the complete operation under the caller's finite process-group/cgroup
supervisor. The native adapter also has an independent absolute timer, and the
Python owner kills/reaps its own process group after each attempt. External
supervision remains required for owner death and initialization. Set the fixed
UTC deadline once before initialization; it may be at most an hour away.
Initialization, hashing, gzip expansion, replay and new scanning share it. UTC
rollback is rejected. No command renews the clock.

```bash
python <skill>/scripts/gsf_resume.py NEW_CHECKPOINT init \
  --sample RETAINED_LOCAL_SAMPLE --quality-receipt ORIGINAL_QUALITY_RECEIPT \
  --reader NEW_READER_RUNTIME --bbox WEST SOUTH EAST NORTH \
  --deadline FIXED_UTC_DEADLINE \
  --new-records 10000 --chunks 8 --replay-records 280000 \
  --read-bytes 64000000 --chunk-read-bytes 8000000 --chunk-seconds 30
python <skill>/scripts/gsf_resume.py NEW_CHECKPOINT step \
  --expected-sha256 HASH_RETURNED_BY_PREVIOUS_SUCCESSFUL_COMMAND
python <skill>/scripts/gsf_resume.py NEW_CHECKPOINT status \
  --expected-sha256 HASH_RETURNED_BY_PREVIOUS_SUCCESSFUL_COMMAND
python <skill>/scripts/gsf_resume.py NEW_CHECKPOINT finalize \
  --expected-sha256 HASH_RETURNED_BY_PREVIOUS_SUCCESSFUL_COMMAND
```

Keep the previous returned checkpoint hash outside the checkpoint. Do not
recompute it from a modified file to bypass the integrity check. Repeat `step`
only while its returned status is `READY`, within the same supervisor and
unchanged deadline. A configuration hash additionally pins immutable fields.
An exclusive nonblocking file lock prevents concurrent writers.

The historical quality receipt supplies the exact source ID, metadata hash,
asset URL, request ID and verified sample binding. Both its complete file hash
and the original sample hash/size are pinned. A gzip sample is expanded once
through the existing bounded gzip implementation (128 MB and 200x maximum),
then its separate native hash/size are pinned too. Original bytes and historical
receipts are never modified. Every chunk verifies these pins before and after
reading. A valid old binding does not grant current rights or source acceptance.

## Accounting and terminal behavior

Hard ceilings: eight chunks, 10,000 newly committed records per chunk, 2,000
pings and one million beams per chunk, 280,000 replayed records total, 250 MB
cumulative `fread` requested bytes, 64 MB requested bytes per chunk, and 45
seconds per chunk. Command values may only reduce them. At most 80,000 unique
records are committed. The native reader has 1 GiB address space, 48 file
descriptors and one MB output files. Metadata inputs/outputs are bounded.

The wrapper disables stdio read-ahead before the first upstream read. Its
`fread_requested_bytes` is conservative requested size-times-count, including
header, replay, short reads and EOF probes; it is not a measurement of physical
disk I/O. Cumulative `fread_charged_bytes` includes all attempts. Hash and gzip
verification reads are separate from this decoder counter, bounded by their
64 MB compressed/128 MB native input caps, finite chunks and the same deadline;
no network transfer is involved. Replay counts separately from new records and
never contributes duplicate observations.

Before launching, the checkpoint atomically reserves the entire byte allowance
and replay cursor. Only a fully validated successful chunk refunds unused bytes
and advances the cursor. Failures retain their full reservation and cannot be
retried unchanged. An interrupted `PENDING` intent also blocks further scans.
Finalization of `PENDING` fails closed because owned-process cleanup is not
verified; preserve evidence and obtain supervisor stop confirmation before any
separately reviewed recovery. Never kill an arbitrary recorded PID.

Normal finalization writes a new separate receipt and removes only its owned
gzip expansion. EOF is explicit; a chunk limit or partial scan leaves all
unscanned remainder unknown. Failed chunks contribute no observations. Numeric
zero remains a valid depth when finite and all ping/beam flags are clear;
missing or application-specific flags are not silently accepted. No terrain,
habitat or rendering acceptance follows from a successful scan.
