# Fleet identity byte diagnostic (SP-16-v1)

SP1603-FLEET-IDENTITY-DIAGNOSTIC is offline evidence, not an encoder fix.
The required result is **PARITY_UNRESOLVED**. No stored identity, fact,
registry, canonical store or product module is changed. Protocol selection,
re-keying and migration remain with the operator; this diagnostic grants none
of them. Machine-valid evidence is REVIEW REQUIRED, not semantic acceptance.

## What runs

The committed synthetic [corpus](../../tests/fixtures/sp1603_fleet_identity_diagnostic/corpus.json)
uses finite `value_json` shapes from the unchanged fleet job and sink tests.
There are 13 ordinary controls, two exponent cases and two astral-key cases.
The nested cases are subcases of the two root assertion IDs, not additional
expected failures. The corpus, source modules, hash dependency and original
regression selectors have frozen SHA-256 pins in
[pins.json](../../tests/fixtures/sp1603_fleet_identity_diagnostic/pins.json).
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

The strict diagnostic makes real equality assertions with root IDs
`exponent_parity` and `astral_key_parity`. At the pinned base both fail and the
strict child exits 1. The report retains every nested mismatch and every
ordinary control. Missing or changed evidence, unexpected agreement,
corruption, source drift or runtime failure yields UNEXPECTED_ERROR and strict
exit 2, not the approved expected-red result.

Measured scalar examples:

| Value | Python text / key | Worker text / key |
| --- | --- | --- |
| `0.00001` | `1e-05` / `5a9530d3c6d5faad` | `0.00001` / `661710915adfa7c4` |
| `1.5` | `1.5` / `9f29a130438b8117` | `1.5` / `9f29a130438b8117` |

For U+E000 and U+10000 object keys, Python orders by code point and the
Worker by UTF-16 code unit. Their actual bytes and keys consequently differ,
also within nested arrays/objects. The report does not imply either encoding
is the chosen protocol or that the two known classes exhaust all JSON-number
or Unicode incompatibilities.

## Tests

`node --test tests/test_sp1603_fleet_identity_diagnostic.mjs` uses this
checkout's `.venv/bin/python3` when present, otherwise the installed `python3`
on PATH (as provided by CI setup-python). It needs neither a stage manifest nor
a virtualenv link. Producer reports retain the actual interpreter
executable/version, and child receipts retain its launch argv. Explicit producer
runtime overrides never fall back; a missing runtime still fails closed.

The file runs the full A1-A4 characterization. A1 asserts the truthful root
mismatches, A2 checks every ordinary control, A3 repeats fresh actual producers
and compares exact nested evidence, and A4 tests corrupt bytes/keys,
wrong/missing producer identities/cases, unexpected agreement, a corrupt
fixture and a missing Python runtime. The last two require the strict
diagnostic to exit 2 with the exact unexpected errors. Healthy evidence still
passes after synthetic mutations. The green characterization suite does not
hide or fix the strict red child.

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

All authored material on this card is by actual `gpt-6.1-sol` via
`openai-codex` (Sol builder admission). The sole independent reviewer is
`opus-coder-bopus`, actual Claude Opus 5.5. This note records provenance, not
self-approval. All source/live/download/legal/preview and existing release
holds remain unchanged.
