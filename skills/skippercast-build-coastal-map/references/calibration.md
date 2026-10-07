# Improve quality per verified result

## Establish a tested floor, not a guessed minimum

Start with orchestration's candidate setting. Compare models/efforts only on the
same bounded input, artifact/revision fingerprint and acceptance checks. Keep
compiler/tests/rights gates and independent review unchanged. A model cannot make
a missing source or permission available. Distinguish product work from simulated
workflow decisions. A dry-run pass does not establish renderer or science ability.

Reuse actual task outcomes rather than buying a benchmark service. Measure when
available: model/effort, input fingerprint, outcome, rework, elapsed active/wall
time and real token usage. Leave unavailable tokens/costs blank; do not estimate
from words or claim subscription savings. Record effective model from tool output
when available; if unknown label requested settings as requested, not observed.

Use `scripts/model_trials.py` for a local append-only JSONL trial ledger and compact
summary. Select a task-owned local path; no network or global monitoring. For example:

```bash
python3 <skill>/scripts/model_trials.py record --ledger <local-trials.jsonl> \
  --task receipt-extraction --fingerprint <input-sha-or-revision> \
  --model gpt-6-luna --effort low --outcome pass --kind actual \
  --evidence <review-receipt-path>
python3 <skill>/scripts/model_trials.py report --ledger <local-trials.jsonl>
```

The report shows counts by task, fingerprint and requested pair; it does not select
or certify a minimum. Promote a lower setting only after several comparable actual
passes with no additional review defects/rework, and a representative failure case.
A practical pilot is three successful actual batches plus a failure fixture; increase
that sample for consequential work. Keep the last accepted pair for fallback. One
failure prompts cause diagnosis; two equivalent failures prompt a method/setting
change. Scope conclusions to that task, not the whole model family.

## Forward-test this skill

Use an independent bounded subagent with realistic inputs, isolated artifacts and
no production mutation. Request decisions, necessary evidence and next action; do
not reveal an answer key. Cover:

1. Pixelated harbor channel/land seam with unlike datum or NoData possibilities.
2. Beautiful smooth current field requested where masked/expired cells exist.
3. A publicly downloadable mixed-rights habitat release replacing a reviewed one.
4. A source-stage job blocked while an independent renderer fix is ready.
5. Camera-only 2D/3D toggling and regional forecast/shared-link conflicts.
6. Protected CI green but production shell/data identity or asset range differs.

Look for concrete bounded action, appropriate skill routing, evidence rather than
fabrication, honest source clocks, release/privacy gates, owned work and correct
stop/retry conditions. Failed cases require narrow skill corrections and rechecking
only affected cases. Passing workflow decisions are simulation evidence only.

## Improve after each meaningful batch

Add a short retrospective to the existing project ledger: intended visible change,
actual result, blocker/rework, setting used and one supported improvement. Keep the
skill's stable reusable decisions; current revisions, jobs and blockers stay in the
project ledger. Patch only rules supported by observed failures. Remove obsolete
workarounds after a regression case proves the contract changed. Don't accumulate
universal gates or duplicate every historical incident.

Prefer one variable per experiment: brief size, model setting, data method or
visual treatment. Evaluate the same views and checks before/after; preserve source
accuracy and existing unique features. Version canonical skill changes in the
repository and synchronize the installed copy after accepted changes.
