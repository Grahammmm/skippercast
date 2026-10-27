# SP79: preserve unknown backup identity

Scope: `sourceStation` only. A valid `fallback_for` declares that the reading
was served through failover; it does not identify the station that served it.
If neither explicit `station` nor `data.station` passes the existing identifier
grammar, return `null`, even if the caller offers the configured primary or
another ID. No UI caller, producer, official-link construction or fetching
policy is changed. `null` means unknown identity, not an invented station name.

## Claim-to-test map

All new assertions import the complete actual `web/station-label.ts` module.
Synthetic source shapes follow `StationSource` and the original
`tests/test_station_label.mjs` `src` / `liveFeed` examples. They contain no live
observations. Portable input is `tests/fixtures/sp79_backup_identity/cases.json`.

| Contract / branch | Named assertions in the focused suite |
| --- | --- |
| A1: declared backup has no eligible station; refuse caller fallback | `A4 primary declared backup without identity`; `A1 no identity matrix never fabricates either caller fallback` covers absent, empty, invalid and wrong-type explicit/data IDs against both primary and other caller IDs, malformed data shapes and no caller fallback |
| A2: eligible explicit station wins | `A4 healthy explicit backup control`; `A2 explicit station wins data disagreement`; `A2 trim all identities` |
| A2: eligible data station supplies missing/invalid explicit identity | `A2 absent station uses data identity`; `A2 invalid station uses data identity`; `A2 trim data identity`; `A2 empty and every invalid explicit identity use valid data identity` |
| A2: source explicitly names the primary, so backupFor remains null | `A2 explicit primary retains primary result`; `A2 data primary retains primary result` |
| A3: no valid backup declaration retains caller fallback and ignores data-only identity | `A3 null missing and invalid backup declarations retain legacy fallback` |
| A3: identifier grammar and trimming are unchanged | `A3 identifier grammar and trimming remain unchanged in every identity position` checks minimum/maximum length, alphanumeric/underscore/hyphen, whitespace trimming, and malformed/wrong-type negatives |
| A3: labels, official URL strings and shared physical station behavior unchanged | `A3 station labels official URL strings and sharing of identified readings unchanged` checks primary/backup labels, all three URL helpers and encoding, sharing both directions, nonshared and missing readings |
| A4: tests detect the original product defect, healthy behavior remains accepted | Baseline selects only the two A4 tests; focused executes the identical tests, without fixture or test edits |

The sole behavior change is exclusion of the caller fallback for a valid backup
declaration lacking actual identity. Valid explicit backups, data-identified
backups, explicit primary readings, legacy caller fallback, ID grammar, text,
URLs and sharing retain their baseline results. The unchanged original seven
station-label tests additionally exercise live-condition, landing and regional
brief surfaces for identified readings; this is a scoped compatibility subset,
not full-repository qualification.

## Offline acceptance and evidence

Run from the complete staged repository with the existing installed Node
(type stripping), existing pnpm dependencies, and the operator-owned
`../SOURCE-MANIFEST.json`. No installation or runtime substitution is permitted.
The launcher derives both repository and write root from its own location,
checks manifest base and ancestry against
`a1f648632e64561d82dcbeb20d9bda19f812560a`, and verifies original selector,
scanner and dependency declaration bytes against that base.

Run each command separately:

    python3 scripts/accept_sp79_backup_identity.py --suite baseline --output ../out/author-baseline
    python3 scripts/accept_sp79_backup_identity.py --suite focused --output ../out/author-focused
    python3 scripts/accept_sp79_backup_identity.py --suite regression --output ../out/author-regression
    python3 scripts/accept_sp79_backup_identity.py --suite repository --output ../out/author-repository
    pnpm typecheck
    pnpm build
    git diff --check a1f648632e64561d82dcbeb20d9bda19f812560a HEAD
    git status --porcelain

Baseline is run BEFORE repair only, with unchanged product SHA256
`bf99e06bd3408cab15046214e930b16155465fb94add3e125f9a6a8954e8c12a`.
The retained historical run `baseline-ldizdv_i` observed
`{"returned":{"id":"46053","backupFor":null}}`; the null assertion failed,
and the explicit-backup control passed. Child exit 1, one pass, one failure,
zero errors/skips; wrapper exit 0 means `BASELINE_DEFECT_REPRODUCED`, NOT GREEN.
The new test and fixture hashes frozen there remain unchanged after repair.
Changing either requires fresh honest before-repair evidence, never rewriting
old receipts. Final green runs occur at the signed-off candidate HEAD and do
not relabel that historical result.

Every launcher call allocates a fresh child directory under its requested
output parent. Its receipt records schema version 1, literal wrapper and child
argv/cwd, runtime version/resolved path, manifest/base/actual-head identity,
source/test/fixture/helper and closure hashes, counts, exits, raw stdout/stderr
paths and hashes. Missing prerequisites, missing assertions, wrong baseline
failure, cancellations, skips and TODOs fail closed. A regression-audit
preflight failure from an initial root-hoisting assumption is retained as
`regression-zdumqw25`; the corrected audit follows Node ancestor resolution for
pnpm dependencies. That failed preflight executed no test child and is not a
product failure or passing evidence.

The audit follows literal imports, conservatively including type-only edges,
through the original local selector and its already-installed dependency
exports. The original selector is literally `tests/test_station_label.mjs`.
It is unmodified. The original closure contains pure render/assessment helpers,
region-default data and signal setup; it does not call region initialization,
feed acquisition, browser startup or storage persistence. No relevant
network-bearing constants or bound defaults are invoked by these assertions.
The new test is preloaded before regression imports, using Node's non-isolated
test mode so the offline child-process sentinel does not interfere with test
runner worker creation. Fetch/socket/HTTP/DNS/WebSocket and child-process
sentinels precede target imports. `localStorage` is an in-memory Map double,
not profile storage. Required completion reports zero prohibited attempts;
these sentinels and static inspection are not a hostile-code sandbox.
All child temporary paths live in that invocation's unique output directory.

Repository mode invokes the unchanged `scripts/check_repository.py` under
`runtime.credential_scan_python3` from the staging manifest, logging the literal
interpreter and version; it does not use the launcher interpreter as a silent
fallback. The audited scanner is a local stdlib file/link scan and invokes no
network or child commands. It reports its actual checked-file count.

## Authorship and handoff boundary

Product repair, new fixture, tests, launcher and this note are authored by
actual `gpt-6.1-sol` / `openai-codex`, profile `sol-reviewer`, on card
`t_c81c9e05` under its explicit Sol builder admission. No Astra diagnostic code
was copied into these deliverables. Existing source/tests remain upstream
material. The sole independent same-card reviewer is actual Claude Opus 5.5
on `opus-coder-bopus`. Signed-off commit identity and exact-head receipts are
supplied in the review request and durable candidate output packet, outside
the repository to avoid a self-referential commit hash.

All machine-green results are REVIEW REQUIRED, not semantic or release
approval. The operator still owns the PR, full-suite/exact-head CI and shipping.
No push, network acquisition, model call, merge, deployment, publication,
outbound email, source permission, operational cap or hold change is included.
