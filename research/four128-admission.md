# Config-driven four128 admission (SC-7)

`research/scripts/coastal_four128_admission.py` replaces per-rerun copies of
`doc5_issue` and `mission_assemble`. It has three deliberately separate actions:
`replay`, `issue`, and `assemble`. It never starts units, opens BAGs, downloads,
or grants scientific/publication acceptance. All results require independent
review. Implementation tracking: Grahammmm/skippercast#753.

## Historical byte reproduction

The committed `research/catalog/four128-admission/doc5{e,f,g}.json` configs are
**historical-replay only**. They cannot issue or assemble a live admission.
On the maintainer machine, with the archived metadata still present:

```sh
python -B research/scripts/coastal_four128_admission.py replay \
  --config research/catalog/four128-admission/doc5e.json \
  --output var/admission-replay/doc5e
```

Repeat with `doc5f.json` and `doc5g.json`, choosing absent output directories.
No inputs or archived outputs are overwritten. The output directory must be
outside the project data tree. `REPLAY_ONLY.json` distinguishes these historical
copies from current review/authority.

The exact-byte target is the issuer's three outputs:

- `closed-fresh-carry.json`
- `independent-runtime-review.json` (document 5)
- `live-index.json`

Inputs are the archived prospective package and its hash-verified metadata,
the signed amendment, evidence documents 1–4, selection/predecessor receipts,
the original issuer script identity, and the issuance receipt. Configs pin the
external input bytes. Control/controller/prepare hashes are checked against
Git objects at the historical head. The renderer reconstructs the three outputs
before opening any of their expected bytes, then compares both bytes and hashes.
The historical clock, reviewer identity and interpreter spelling are recorded
observations, not fresh attestations. Aggregate code/dependency identities are
cross-checked as recorded bindings, not measured in today's environment.

This does **not** rerun `prepare.py`, revalidate an old scientific conclusion,
or backdate a current approval. Prepare outputs contain their own historical
clock observations and are expressly archived inputs to this acceptance test.
Historical copies can contain `PASS`/execution flags because byte equality
requires preserving them; the replay receipt confers no execution authority.

## One future-rerun config, not another Python version

A future run needs a separately reviewed JSON config and a newly admitted task.
No runnable live config is shipped here: the existing signed v6 allowance and
old tags belong to already-run missions and must not be reused.

Use the historical config structure as the field reference, with these changes:

- `mode`: `live`; `layout`: `6`; fresh `label`, `run_tag`, `staging_root`,
  `mission_root`, `project_root`, and complete `used_run_tags`.
- `head`, `code_root`, `interpreter`: the exact independently reviewed checkout
  and interpreter. The command runs from that checkout; no dirty tracked or
  untracked files are permitted. The source supervisor's own guard runs first.
- `origin`: `{ "ref": "origin/<reviewed-branch>", "head": "<40 hex>",
  "allowed_test_files": [] }`. Normally origin equals the approved head.
  A separately reviewed descendant may differ only in the exact listed `tests/`
  files. It is recorded as not approved for execution.
- `controls`: hashes for runtime, resources, artifact-review **and**
  `research/catalog/coastal-four128-charge-ledger.json`. Also pin
  `prepare_sha256`, `controller_sha256`, and `bootstrap_sha256`.
- `inputs.amendment`, `inputs.selection`, `inputs.prior_carry`, and
  `inputs.historical_context`: `{path, bytes, sha256}` of admitted metadata.
  Remove historical `receipt`, `issuer`, and `package` inputs; they are not used
  by live issuance. Paths may use `~/` (expanded on the operator's machine).
- `evidence_root`, `docs`, `windows`, `bounds`, `limits`, `retained`: exact reviewed
  policy and accounting. All four document role/schema pairs are mandatory.
  Prepare's existing grant/coordinator validation is retained. Evidence must
  retain more than two hours' validity at issuance.
- `reviewer`: `{profile, model, reviewer_id}` of the actual independent issuer;
  `task`: admitted review task id. The harness author (Opus) cannot issue its own
  runtime review. A string is a role attestation, not a cryptographic signature.
- `texts`: reviewed carry rationale, scratch ruling, checks and limitations;
  do not copy an old amendment's narrative into a new admission.
- `issuance_receipt`, `assembly_receipt`: distinct, absent receipt paths outside
  the mission and staging roots; `window_scope_change`: reviewed context rationale.

The reviewer records the SHA256 of the completed config in the task. Both
commands require that exact pin; it is a binding check, not a substitute for
independent review or budget authority:

```sh
python -B research/scripts/coastal_four128_admission.py issue \
  --config var/admission/run.json --config-sha256 REVIEWED_CONFIG_SHA256
python -B research/scripts/coastal_four128_admission.py assemble \
  --config var/admission/run.json --config-sha256 REVIEWED_CONFIG_SHA256
```

Issuance invokes the existing metadata-only prepare CLI into an absent staging
root, checks accounting/geometry/identities/evidence and runs the runtime review
validator before writing the issuance files. Assembly verifies the issuance
config binding and controls, checks the pinned historical context, creates the
absent managed mission and writes staging metadata verbatim through
`ManagedOutputs`. It then runs the real runtime `preflight` CLI. It never calls
`run`. A failed assembly is retained with a failed receipt, never retried in
place. Fresh mission/scratch/tag checks and the 75-minute document-5 expiry
margin are preserved. Native execution remains a separate admitted task step.

## Charge ledger and authority boundary

`research/catalog/coastal-four128-charge-ledger.json` is a repository-reviewed
accounting projection of the existing signed delegated-authority amendment.
It records the original raw SHA256, revision, superseded digest, signer and
signing time; the archived signed bytes are not rewritten or republished.
The historical signature is a **role attestation**, not a public-key signature.
No signing key or new authority was introduced.

`resources.py` loads the ledger's charge fields dynamically, derives its floors
and allowances, and checks integer accounting/no-refund identities. Live prepare
requires the raw amendment digest to match the ledger head. Runtime likewise
requires the already hash-verified grant amendment reference to match that head.
The ledger itself is now mandatory in document 5's runtime control hashes, so a
ledger edit invalidates the old runtime binding. Dict-only `budget_limits` is an
arithmetic validator retained for tests, not the live raw-byte authority gate.

For another failed/completed run or charged metadata read:

1. The delegated authority signs an amendment carrying every previous charge,
   the new charge, the predecessor digest and exact shortfall. This tool does
   not sign it or invent authority.
2. Update the reviewed ledger projection and head identity from those signed
   bytes. Append the new named `*_charged_bytes` field; never remove/refund an
   old charge. The original signed bytes must agree with the projection.
3. Update the fresh run config and obtain independent review. Python does not
   need another failed-run constant. Existing compatibility names remain for
   historical consumers; new validation iterates the ledger keys.
4. Reissue document 5 against the new ledger/control hashes. Old doc5e/f/g
   configs remain replay-only and never acquire new authority.

## Verification and limitations

```sh
PYTHONPATH=src:. PYTHONDONTWRITEBYTECODE=1 python -B -m pytest \
  tests/unit/test_coastal_four128_admission.py \
  tests/unit/test_coastal_four128_budget.py \
  tests/unit/test_coastal_four128_home_paths.py \
  tests/contract/test_research_boundary.py tests/contract/test_test_layout.py
```

CI runs synthetic construction, accounting, path/no-overwrite, tag, hash and
review refusal tests. When archived metadata exists, the same suite additionally
checks the three real historical replays (like the existing signed-amendment
checks). The synthetic assembly test uses the real managed writer and runtime
review validator with a simulated subprocess preflight, not a live mission.
Actual historical replay is the execution evidence for the byte criterion;
a future live config still requires fresh independent review and real preflight.

## Rerun card template

Title: `Four128 rerun <tag>: issue, assemble, execute, preserve receipt`

Body: admitted scope; exact reviewed head and config SHA256; fresh tag; signed
amendment path/SHA256; doc5/staging path; absent mission/scratch paths; exact
resource/output caps; source-read allowance; actual issuer/reviewer identity;
executor; no downloads/publication; commands above followed by the separately
admitted runtime command; required receipts; independent acceptance/merge owner.
A machine PASS is review-required, not semantic acceptance. No FIX/DOC5/RUN
triples are needed merely to change a run tag or charge amount.
