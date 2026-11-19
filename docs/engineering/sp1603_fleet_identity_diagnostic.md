# Fleet identity byte diagnostic (SP-16-v1)

SP1603-FLEET-IDENTITY-DIAGNOSTIC is offline evidence. The frozen pre-SCA-369
baseline, replayable at `182f5dd921c2ff6421f838a22bcbdf25e149c45c`, has the
required result **PARITY_UNRESOLVED**. The current-source successor requires
**PARITY_RESOLVED** instead. Neither diagnostic rewrites or migrates stored
identities. Machine-valid evidence is REVIEW REQUIRED, not semantic acceptance.

## What runs

The committed synthetic [corpus](../../tests/fixtures/sp1603_fleet_identity_diagnostic/corpus.json)
uses finite `value_json` shapes from the unchanged fleet job and sink tests.
There are two exponent cases and 15 controls, including two astral-key cases.
The exponent cases share one root assertion ID. The corpus, source modules,
hash dependency and original regression selectors have frozen SHA-256 pins in
[pins.json](../../tests/fixtures/sp1603_fleet_identity_diagnostic/pins.json).
The successor overlays only the two changed module hashes on the baseline pins.
No plan directory, other candidate, extracted function or copied encoder is a
runtime input.

The Python file entrypoint imports the full staged
`skippercast.fleet.ops` and calls `canonical_json` and `value_key`. The Node
file entrypoint imports full `server/fleet/ids.ts` and its real hash dependency,
calling `canonicalJson` and `valueKey` under installed Node type stripping.
Both return the exact text, UTF-8 hex bytes, value keys, source SHA and runtime.
A separate comparator hashes the returned bytes with Node's `createHash` and
requires each actual value key to equal the independently derived first 16
hex characters. It never regenerates JSON with a copied encoder oracle.

The frozen strict diagnostic records `exponent_parity` as unresolved and exits
1. The successor requires both exponent cases to agree and exits 0 on parity.
Both require complete evidence and keep the nested cases and ordinary controls.
Missing or changed evidence, corruption, source drift, runtime failure, or a
parity outcome contrary to the selected mode fails closed.

Measured pre-fix scalar examples:

| Value | Python text / key | Worker text / key |
| --- | --- | --- |
| `0.00001` | `1e-05` / `5a9530d3c6d5faad` | `0.00001` / `661710915adfa7c4` |
| `1.5` | `1.5` / `9f29a130438b8117` | `1.5` / `9f29a130438b8117` |

The U+E000 and U+10000 object-key cases already agree at the pre-fix baseline
and remain controls, including when nested. The successor uses the Worker's
`0.00001` / `661710915adfa7c4` representation in both runtimes. This corpus
alone does not cover all JSON-number or Unicode edge cases.

## Tests

`node --test tests/test_sp1603_fleet_identity_diagnostic.mjs` requires current
parity. It uses this checkout's `.venv/bin/python3` when present, otherwise the installed `python3`
on PATH (as provided by CI setup-python). It needs neither a stage manifest nor
a virtualenv link. Producer reports retain the actual interpreter
executable/version, and child receipts retain its launch argv. Explicit producer
runtime overrides never fall back; a missing runtime still fails closed.

To replay the frozen baseline, run the same Node test command in a checkout of
`182f5dd921c2ff6421f838a22bcbdf25e149c45c`; its unchanged strict entry point is
`node tests/fixtures/sp1603_fleet_identity_diagnostic/diagnostic.mjs --output <new-output-dir>`.
If staging this revision's wrapper and pins alongside the pinned sources, use
`node tests/test_sp1603_fleet_identity_diagnostic.mjs --baseline` explicitly.
The successor never falls back to baseline mode on source drift.

The modes share the A1-A4 test cases and offline producer entry points. A1 checks
the measured parity verdict, A2 checks every ordinary control, A3 compares
fresh producer bytes and keys, and A4 rejects corrupt bytes/keys, wrong source
identities, missing cases and a self-consistent but wrong parity outcome. A
corrupt fixture or missing Python runtime still yields `UNEXPECTED_ERROR` and
strict exit 2. The unchanged SQLite and offline sentinels run in both modes.

## Isolation and limits

Producer and original-regression children install network/model and live-store
sentinels before product import. Python redirects repository/fleet/temp roots,
blocks network/process I/O, captures guarded bound `urlopen` defaults, and
restricts writes/SQLite files to its unique synthetic output root. Node denies
fetch, HTTP(S), socket and datagram calls. A process-local file-based module
hook restricts native `node:sqlite` to `:memory:` while retaining its real
implementation; original migrations still run unchanged. A fresh-process
probe checks sentinels and a healthy in-memory SQLite positive. No service,
real D1, browser, model or public endpoint is contacted. No browser/component
code changes are involved in this card.

These are trusted offline-fixture guards, not a hostile-code security sandbox.
They live only in dedicated child processes; the ordinary characterization
module does not install irreversible hooks into the discovery process or
other suites. Node child termination restores its globals by process lifetime.
Python also disables bytecode writes to the approved shared venv. Synthetic
outputs and failed-development receipts are retained, never operationally
deleted or resealed as successes. Review reruns must use separate output roots.

The original SP1603 diagnostic was authored by actual `gpt-6.1-sol` via
`openai-codex` (Sol builder admission). The sole independent reviewer is
`opus-coder-bopus`, actual Claude Opus 5.5. This note records provenance, not
self-approval. All source/live/download/legal/preview and existing release
holds remain unchanged.
