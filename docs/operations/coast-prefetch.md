# Coast campaign raw prefetch (operator runbook)

Status: downloader implementation; **the generated seed is incomplete**. Do not
start a statewide service until the inventory gaps are resolved and independently
reviewed. Tracking: Grahammmm/skippercast#803, kanban `t_ee628c67`; metadata inventory
prerequisite `t_1a76ef56`; reviewed-host prerequisite `t_591ffff6`.

This tool downloads original files and records provenance. It never extracts
archives, opens a raster, qualifies a source, maps terrain, changes the canonical
survey ledger, or publishes anything. A verified download is **review-required**,
not accepted science or permission to redistribute CSUMB material. VR BAGs may be
mirrored even while a mapping reader holds them. BlueTopo remains planning context.

## Inventory and dry-run

Use a reviewed checkout and the shared Python environment. Commands below are run
from a task/operator worktree, not `main`. `PYTHONPATH=src` makes the shared venv
import this checkout rather than the primary checkout's editable installation.

```sh
PYTHONPATH=src "$HOME/repos/skippercast/.venv/bin/python" \
  research/scripts/build_coast_prefetch_plan.py --output var/coast-prefetch-seed.json
PYTHONPATH=src "$HOME/repos/skippercast/.venv/bin/python" \
  -m skippercast.coastal.prefetch --plan var/coast-prefetch-seed.json --dry-run \
  > var/coast-prefetch-dry-run.json
```

The seed builder is offline inventory preparation, not a new discovery lane. It
reads committed CSMP 2 m/5 m product lists, CSUMB BSS/SCC archives (one archive can
contain both native grids), additional SFML archives, NOS regular and VR BAG
candidates and their existing bbox/window evidence, and the Cal DIG I release.
It emits explicit gaps for unlocated products, unassigned files and conflicting
archive/member pins. It does not guess URLs, promote a directory listing into a
file, or label catalog samples as exhaustive.

The supplementary inventory must reconcile all named campaign products, including
current CA BlueTopo tiles, CRM SoCal v2 1 arc-sec and applicable other volumes,
Cascadia, Borderland, NCCOS Channel Islands, DDS-55, GEBCO 2026 and GMRT **CA subsets**,
and paginated NCEI footprint metadata. GEBCO/GMRT/CEDA/GIS requests must wait for
the reviewed COAST-HOSTS change to be merged. No whole-world dump or ungridded
multibeam archive is implicitly authorized. The seed's `unresolved` list is not
removed automatically by adding a file: a reviewer must reconcile each gap.

### Reconcile the approved supplement and current NOAA metadata

The metadata-only prerequisite `t_1a76ef56` was independently accepted by Sol.
Its exact supplement SHA-256 is
`cb2bd023b9ba3e42930ffd7c83f1f888ea44fd4e8d87db33fb1d4c2aa22b3619`.
It adds seven candidate files, not seven scientifically accepted sources; the
GEBCO reviewed-host subset, Borderland and Gridimage TIFF holds remain explicit.
The enumerator rejects any different supplement hash. A new supplement needs a
new independent review and a deliberate code change, not a CLI override.

From this checkout, using the existing survey-stack venv (for scheme geometry):

```sh
PYTHONPATH=src:. "$HOME/repos/skippercast/.venv/bin/python" \
  -m research.scripts.enumerate_coast_prefetch \
  --supplement /path/to/accepted/campaign-prefetch-supplement.json \
  --receipts var/prefetch-enumeration-YYYYMMDD \
  --output var/coast-prefetch-reconciled.json
PYTHONPATH=src:. "$HOME/repos/skippercast/.venv/bin/python" \
  -m research.scripts.enumerate_coast_prefetch \
  --supplement /path/to/accepted/campaign-prefetch-supplement.json \
  --receipts var/prefetch-enumeration-YYYYMMDD --offline \
  --output var/coast-prefetch-replayed.json
```

Exit 2 with a written plan means unresolved holds, not a completed inventory.
`--only nos`, `--only bluetopo` or `--only supplement` provides bounded partial
preparation; unexamined source gaps stay unresolved. The downloader still refuses
an incomplete plan unless the operator explicitly chooses `--allow-incomplete`.

The live enumerator fetches only bounded ArcGIS JSON, BAG directory HTML, S3 XML
listings and the small BlueTopo geometry/link GeoPackage. It never fetches BAG,
GeoTIFF, RAT, archive or generated-subset bodies. It verifies the NOS count and
unique object-ID set, batches those IDs with geometry, records all survey-envelope
associations (including exclusions outside the segment boxes), and includes every
regular/VR BAG link returned by each intersecting survey directory. The filename
VR hint is not a format validation. Add `--probe-nos-sizes` to obtain each BAG's
Content-Length/ETag/Last-Modified with HEAD only (also pass it on offline replay
to reuse those header receipts). Missing sizes and conflicting committed pins
remain explicit holds; without this flag NOS file sizes need later preflight.

BlueTopo selection reads the current listed scheme, transforms its CRS, intersects
all 22 segment boxes, and reconciles BOTH raster and RAT links against current
per-tile listings. Every scheme/tile S3 listing follows continuation tokens to
completion and rejects missing/repeated tokens. Scheme SHA-256 pins are used for
rasters/RATs; S3 ETags are never substituted. Undelivered tiles are recorded, not
invented. The scheme and NCEI metadata snapshots also enter the mirror plan.

Responses and SHA-256 receipts remain under `--receipts`, never in a canonical
store. Reusing that directory resumes/replays its snapshot; a fresh snapshot uses
a new directory, **not a new host retry registry**. Metadata GETs, BAG HEADs,
size preflight and downloads all use the same local
`~/skippercast-data/campaign-raw-manifest/retry-state.json`. Each network request
reloads it under a shared lock held through response/error persistence. Concurrent
processes cannot overwrite other hosts' holds or race a new hold; even separate
snapshots are serialized. Interrupted runs retain successful responses. Each invocation
is bounded to 2,000 requests/30 minutes, with serial one-second spacing, rejected
redirects and durable host parking. Review a changed snapshot before using it.
No CI test contacts these endpoints. Neither enumeration nor a dry-run authorizes
the bulk service or mapping.

#### Migrate legacy host holds before any new live invocation

Older builds kept retry state under each snapshot's `state/` directory. Reusing
an old snapshot imports its holds automatically before a network request, but a
fresh snapshot cannot discover unrelated old directories. Before switching builds,
stop old prefetch/enumerator processes and explicitly import **all** retained
retry registries, including one-off subset/WCS/HEAD probes. This operation is
network-free, takes the same shared lock, retains the latest deadline and maximum
failure count per host, preserves unrelated hosts, and never changes its inputs.
Do not delete the old evidence. There is no CLI override for the shared location.

For the retained 2026-10-20 run in this task worktree:

```sh
PYTHONPATH=src "$HOME/repos/skippercast/.venv/bin/python" \
  -m skippercast.coastal.prefetch \
  --import-retry-state var/prefetch-enumeration-20261020/state/retry-state.json \
  --import-retry-state var/prefetch-wcs-heads-20261020/state/retry-state.json \
  --import-retry-state var/prefetch-static-heads-20261020/state/retry-state.json
```

Verify the printed/read-back shared registry retains the `www.ngdc.noaa.gov`
deadline **at least 1792638183.7253046** (the retained WCS HTTP 500 hold), as well
as GMRT and any other existing holds. Do not contact that NOAA host before its
deadline. Migration is not permission to start the campaign or clear source holds.
Offline replay and dry-run never acquire/write the retry registry or make requests.

### Generated-subset access remains a separate hold

Metadata approval is not proof that a payload endpoint supports safe transfer.
The downloader deliberately refuses unknown remote lengths rather than invent a
byte total or launch an unbounded generated response. On 2026-10-20 a HEAD-only
probe of the accepted subset URLs returned HTTP 403 for SoCal v2 and Vol7, HTTP
200 **without Content-Length** for Vol6, and a GMRT timeout (host parked). No
payload GET was attempted. These candidates need a reviewed downloadable bounded
representation or independently established exact size before the full campaign
can run; do not substitute a whole-volume/global file or expand hosts. A dry-run
with unknown totals is honest planning output, not a promise of runnable subsets.

Plan format (JSON): `schema_version: 1`, `files: [...]`, `unresolved: [...]`.
Each file has:

- `source`: lower-case safe slug, e.g. `usgs-caldig-i`, `noaa-nos`, `csumb-sfml`;
- `url`: exact approved HTTPS downloadable URL, including any reviewed subset query;
- `segments`: one or more of C1, C2, C3, C4, C5, C6, C7a, C7b, S1–S6,
  N1–N6, N6b, N7, scheduled in that order;
- `bytes`: positive exact byte size, or null while awaiting metadata;
- `sha256`: producer/previously reviewed original-file SHA-256, or null;
- `licence`: original licence and restrictions, not a blanket assumption;
- `evidence`: official metadata URL or committed evidence pointer (retained in plan).

URLs are deduplicated; conflicting duplicate metadata is refused. Shared sources
are scheduled and counted once, at their earliest segment. Case-safe filenames
use a URL-hash prefix plus a sanitized original name. No source file is renamed
based on an untrusted Content-Disposition header.

`--dry-run` makes **no network requests and no writes**, and does not need the
SanDisk mounted. It lists every admitted URL/path, all unresolved inventory gaps,
and per-segment known bytes plus unknown-size counts. `total_bytes: null` means
unknown, never zero. Totals are unique original bytes, not current incremental
network demand; dry-run deliberately does not hash the potentially large mirror.

To obtain exact sizes, the **operator** can explicitly request HEAD-only preflight:

```sh
PYTHONPATH=src "$HOME/repos/skippercast/.venv/bin/python" \
  -m skippercast.coastal.prefetch --plan var/coast-prefetch-seed.json \
  --probe-sizes --output var/coast-prefetch-sized.json
```

Preflight obeys the same allowlist, spacing and persisted host parking. It never
fetches response bodies or silently updates an existing byte/hash pin. Unsupported
HEAD, absent sizes, changed pins and unavailable hosts become explicit holds.
Review that output and the metadata supplement; freeze the complete plan at
`~/agent-work/reports/coast-pilot/prefetch-plan-reviewed.json`. Keep a SHA-256 of the
plan with the review. A request URL absent from the effective reviewed HTTP
allowlist is refused before any DNS or network activity. Bare `allowed_hosts`
strings in a catalog do not widen that policy.

## Storage, resume and integrity

Fixed production locations (no CLI reserve or host-policy override):

- SanDisk originals:
  `/mnt/agentorange-backup/skippercast-campaign/raw/<source>/<url-hash>-<file>`
- Primary source manifests: `raw/<source>/manifest.jsonl` on the same disk.
- Byte-identical manifest mirrors:
  `~/skippercast-data/campaign-raw-manifest/<source>.jsonl`. A mirror holding
  receipts the primary lacks (primary lost or truncated) stops the run; both are
  preserved for the operator instead of the mirror being overwritten.
- Host retry state: `~/skippercast-data/campaign-raw-manifest/retry-state.json`.
  Its adjacent `.lock` file synchronizes all prefetch modes on the local filesystem.
- Dashboard: `~/agent-work/reports/coast-pilot/prefetch-status.json`.

Every manifest record has URL, final URL, original bytes, local SHA-256, ETag,
Last-Modified, fetched-at time, licence, segments, absolute cached path and
verification method. If a publisher hash was available, it must match. Otherwise
`http-size-and-local-sha256` explicitly describes the weaker verification; a local
hash is not misrepresented as an independent publisher checksum.

Before requests and each data write, the tool checks that the disk is mounted and
that the write cannot reduce free space below **200,000,000,000 bytes (200 GB)**.
Missing mount or reserve exhaustion stops the whole pass. It does not create the
raw directory on an unmounted root filesystem. Originals, checkpoints and atomic
replacement files are ordinary files; no symlinks, Unix permission bits, hardlinks
or cross-filesystem renames are needed on exFAT. Manifest writes also preserve the
reserve. Local process exclusion uses a Linux lock under
`~/.cache/skippercast/coast-prefetch/`, keyed by the raw root.

A HEAD identifies size and a strong ETag validator. Download GETs
use 64 MiB ranges with If-Range, exact Content-Range and length validation, and
checkpoint `.part.json` receipts. A disconnected range is retried from its prior
checkpoint after the host cooldown; at most one in-flight range is discarded.
On restart the committed partial prefix is SHA-256 verified. A crash during append
may leave an uncommitted suffix; only that suffix is truncated and re-fetched.
A crash before the very first checkpoint may leave an empty `.part` with no
receipt; restart safely initializes it because there are no bytes to authenticate.
Nonempty unreceipted partials and existing invalid/identity-changed receipts are
still preserved and held; an empty file is not permission to ignore a receipt.
A changed validator, redirect target or corrupted prefix is held for investigation;
any ETag change (weak or strong) or Last-Modified change on a response is a hold.
A server ignoring Range can return one complete file, but that response replaces
the partial—it is never appended. Without a strong ETag (a weak ETag or
Last-Modified alone is not byte identity), only one whole-file response is accepted (no unsafe multi-request concatenation).

The verified final file is skipped on subsequent passes only after its size and
SHA-256 are checked against its manifest and any plan pins. No source request is
made for a verified cached file. A missing/stale secondary manifest is repaired
from the primary. Existing unmatched or corrupt final files are preserved and
held, not silently overwritten. Do not delete checkpoints to "fix" a hold without
reviewing the identity change; preserve suspect bytes under a separately reviewed
operator quarantine procedure.

## Politeness and status

The implementation is deliberately serial: at most **one** request is active,
including redirected requests (below the requested maximum two per host). It
uses the common `skippercast.http.Session` TLS, public-address pinning and reviewed
redirect allowlist, a descriptive SkipperCast User-Agent and one-second per-host
minimum spacing. It does not introduce another network stack or relax TLS.

There are no inline network retries. A 429, any 5xx or transport error durably
parks the actual affected host. Default delays grow 15 minutes, 30 minutes, etc.,
up to one day; longer Retry-After is respected. **NOAA 500/503 waits at least one
day.** Other URLs and redirects to that host are not contacted during the hold,
even after process restart or a fresh metadata snapshot. Unaffected hosts may continue.
Imported or concurrently updated deadlines are never shortened. Permanent HTTP errors,
identity mismatches and contract failures are holds, not rapid retry loops.

Status contains each source's files done/total, verified bytes and structured
errors; active URL, pass transfer bytes and parked-host retry times are also
reported. Progress refreshes during streaming (at most once per ten seconds), as
well as at each checkpoint/file. Unknown inventory cannot report `complete`.

Exit statuses: 0 = all plan files verified, no unresolved inventory; 75 = transient
host parking; 2 = permanent hold, incomplete inventory or capacity stop.
`--allow-incomplete` is an explicit operator-only partial pass over known files.
It retains unresolved gaps, returns 2, and **never** claims statewide completion.
It is not used by the full-campaign unit below.

## Claude operator service handoff (do not run inside a card)

No service has been installed or started by this implementation. After code and
inventory review and normal protected merge, the Claude operator prepares a
retained worktree at the reviewed commit and installs a user unit. Replace the
example worktree below with that retained path (do not depend on a card's disposable
worktree). Use the existing shared venv; no new dependencies are required.

Example `~/.config/systemd/user/coast-prefetch.service`:

```ini
[Unit]
Description=SkipperCast reviewed coastal raw-source prefetch
ConditionPathIsMountPoint=/mnt/agentorange-backup

[Service]
Type=simple
WorkingDirectory=%h/repos/skippercast/.worktrees/coast-prefetch-service
Environment=PYTHONPATH=src
ExecStart=%h/repos/skippercast/.venv/bin/python -m skippercast.coastal.prefetch --plan %h/agent-work/reports/coast-pilot/prefetch-plan-reviewed.json --run
Restart=on-failure
RestartPreventExitStatus=2
RestartSec=1h
TimeoutStopSec=180

[Install]
WantedBy=default.target
```

Operator commands after prerequisites (not run by agents on this card):

```sh
systemctl --user daemon-reload
systemctl --user start coast-prefetch.service
systemctl --user status coast-prefetch.service
journalctl --user -u coast-prefetch.service
```

A parked pass exits 75; the service retries after an hour but persisted host
cooldowns still enforce next-day NOAA retries. A permanent hold/capacity stop exits
2 and stays stopped for operator attention. Success exits 0 and does not restart.
No timer swap, service enablement, new privileges, spending or live-site publishing
is part of this handoff.

## Later mapping handoff

The original cache reference is `(path, bytes, sha256, url, licence)`. A shared URL
has one physical original and one manifest entry even if many segments/windows
use it. A later governed mapping admission must count that cached source once
against its unchanged `MAX_TOTAL_BYTES`, not once per window. This tool does not
change the coordinator's caps or ledger. Archives still need governed extraction;
raw VR BAGs still need their reviewed native-refinement path. The existing bridge
requires native files beneath its queue root, so this raw mirror is **not** an
automatic authorization to point a bridge plan outside that root. A subsequent
cache-admission step must validate/stage the native file using the existing rules;
never symlink around them. No mapping run is launched here.

## Offline acceptance

```sh
PYTHONPATH=src "$HOME/repos/skippercast/.venv/bin/python" -m pytest \
  tests/unit/test_coast_prefetch.py tests/unit/test_http.py \
  tests/contract/test_research_boundary.py tests/contract/test_test_layout.py \
  research/tests/test_coast_prefetch_seed.py research/tests/test_coast_prefetch_enumeration.py
# With the survey stack also exercise the synthetic GeoPackage CRS cases:
PYTHONPATH=src:. "$HOME/repos/skippercast/.venv/bin/python" -m pytest \
  tests/gis/test_coast_prefetch_scheme.py
```

Tests exercise the real HTTP policy client against synthetic offline responses:
resume and crash checkpoints, If-Range/range length, ignored Range, full-transfer
fallback, hash/size rejection, no-network verified skip, mirrored manifests,
mount/reserve failure during streaming, host parking across restarts, forbidden
and parked redirect targets, lock exclusion, symlink refusal, scheduling/dedup,
metadata preflight and incomplete-inventory reporting. The common HTTP suite
also exercises real local TLS, hostname verification and DNS/address pinning.
