# T08 admission gap report (AUDINV-FIX-059)

**Disposition: HOLD** until a fresh, non-backdated, independent owner admission exists. Report only. Nothing was renewed, issued, rerun, backdated or extended, and no cap, attempt or validity was changed. Historical records are untouched. Completing this report needs no owner reply.

Provenance: G decision 2026-11-15 (decisions/G-DECISIONS.log:1931), inventory row FIX-059 (reports/audit-inventory/INVENTORY.tsv:322). Checked in a clone of `Grahammmm/skippercast` main.

## 1. Expired T08 admission (observed)

Source: `~/agent-work/NEXT-ITERATION.md` item 12 (line 38), verbatim:

> The fresh T08 admission documents 1-4 expire Tue 2026-10-20 15:38 PDT. After that, the script reruns; no backdating.

- Expiry: **Tue 2026-10-20 15:38 PDT**, zone kept as written and not converted.
- Scope: role documents 1-4. The four doc roles in `doc5g.json` `docs` are `independent-four128-rights-review`, `-scientific-preflight`, `-scope-review` and `-strict-trial-policy`.
- Today (2026-11-15) is after that expiry. Documents 1-4 are expired.
- `NEXT-ITERATION.md` item 13 (line 39) records G's 2026-10-19 "160 MiB" retained-output cap and asks for it to be folded into the owner-authorization documents.

## 2. Historical doc5g.json binding (observed)

File: `research/catalog/four128-admission/doc5g.json`. SHA-256 `724f0124048c86a82b202a5b7a9eb9d94200c7bc5d86b58c4e32b5faef7c81c1`. Last touched in commit `220e19337ed4a5797a526f88b0427fca7a392d69` (2026-10-20 08:20:19 -0700).

| Field | Line | Value |
|---|---|---|
| `mode` | 65 | `historical-replay` |
| `retained.cap` | 69 | **167772160** B (160 MiB) |
| `retained.prior` | 70 | 78101927 B |
| `retained.trial` | 71 | 33554432 B (32 MiB) |
| `run_tag` | 73 | `20261020r2` |
| `limits.source_prior_bytes` / `source_limit_bytes` | n/a | 2034491132 / 2328551676 |
| `limits.scratch_prior_bytes` / `scratch_limit_bytes` | n/a | 1616905649 / 2153776561 |

The cap, prior and trial are three distinct byte fields and none is derived from another here. Prior 78101927 = doc5f prior 68,088,433 + rerun-1 charge 10,013,494, per `texts.retained_meaning`. That text says "no refunds", and the report keeps that term. Prior charges, attempts and the source/scratch limits stay as recorded.

The same cap 167772160 is also in `doc5e.json:69` (SHA-256 `bd73234e...a079`) and `doc5f.json:69` (`b2b3ec52...2101`). Historical cap consolidation is therefore present in three historical documents.

`doc5g.json` also states its own limit: "Prelaunch runtime binding only; not scientific acceptance, not execution authority beyond coordinator gates." Its `mode` is `historical-replay`, so it records past state and does not authorize a run now.

## 3. Separate older 64 MiB scope (observed, not merged with the 160 MiB scope)

| Scope | Value | Where | Date |
|---|---|---|---|
| Earlier harness cumulative cap | **67108864** B (64 MiB) | `~/agent-work/t08a/fresh_admission.py:158` (`cap = 67108864`); the same file's text says `coastal_four128_prepare.py:58` hard-codes 67108864; `t08a/dry-staging/metadata/approved-trial-budget-arithmetic-v1.json:7` | Pre-2026-10-19 attempts |
| G-ruled retained cap | **167772160** B (160 MiB) | `NEXT-ITERATION.md:39`; `doc5e/5f/5g.json` | G 2026-10-19 |

Both are kept as historical records. The 64 MiB value was an earlier attempt's cumulative cap, with prior 33509823 and trial 33554432 in that attempt's own packet. It is not a reading of the 160 MiB value. Neither record was edited.

In `research/scripts/coastal_four128_runtime.py` the byte value 67108864 appears only as a systemd `LimitFSIZE` property (line 443). It is not a retained-output cap and is not an admission value. 33554432 appears at lines 253, 272 and 316 as the per-trial output cap.

## 4. Current authorization (NOT VERIFIED)

Searched: the repo's `research/catalog/four128-admission/` and the `~/agent-work` T08 artefacts named above. Not found in the admitted evidence:

- a current role document set (documents 1-4) with validity after 2026-10-20 15:38 PDT;
- a current owner approval naming role, scope, code identity, ledger and horizon;
- an authorization that carries the 160 MiB cap forward into a current admission.

Status: **NOT VERIFIED**. No reviewer or owner is guessed. The custodian of the missing facts is the admission owner. A tooling reference exists (`doc5_issue_v7.py` and `fresh_admission.py` under `~/agent-work/t08*`). It is a reference only, was not run, and is not a request to issue anything.

## 5. Why a present historical cap still gives HOLD

1. The cap is recorded under `historical-replay` mode, with the doc5g binding scoped to run tag `20261020r2`.
2. The role documents backing that run expired on 2026-10-20 15:38 PDT.
3. Past cap consolidation is not authority to run now, and no test or catalog row can create owner authority.

## 6. Prerequisite for any future run

A separately admitted future run needs a fresh admission that is:

- **non-backdated**: dated at issue, never moved to an earlier time or to today's date by editing history;
- **independent**: the author is not the reviewer;
- bound to role, scope, code identity, ledger and a stated horizon;
- explicit about cap, prior, trial, and source and scratch limits, with prior charges and the no-refund term carried over unchanged.

No attempt count or validity is extended by this report.

## 7. Open items for the custodian

- Admission owner: issue or decline a fresh admission (outside this card).
- Reconcile `NEXT-ITERATION.md:39` ("fold 160 MiB into owner-authorization documents") with the current owner documents. Only the historical `doc5e/5f/5g` carry it.

## 8. Manual checks of this report

- All quoted values were re-read from the files above. Each is observed unless labelled NOT VERIFIED.
- No synthetic example is present.
- The sha256 values were computed on the clone's files; the doc5g hash is the full value, and the doc5e and doc5f hashes are shortened.
