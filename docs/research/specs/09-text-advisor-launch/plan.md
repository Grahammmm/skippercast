# Implementation plan · 09 Text Advisor launch

## Evidence (observed 2026-11-19, commit fa9c358)

- `docs/plans/text-advisor/README.md`: status "Built; pending owner launch steps (2026-10-04)". Gated by `TEXT_ADVISOR_ENABLED` and `ENABLE_ADVISOR`.
- `docs/plans/text-advisor/11-testing-rollout.md`: § Owner to-do (A merge, mostly done; B decisions; C accounts and hardware; D secrets; E variables) and § Flip order (four steps: bindings, dark, replies, social), each followed by `gh workflow run deploy-cloudflare.yml` and `scripts/advisor/preflight.mjs`.
- `server/advisor/gate.ts`: 404 unless enabled. `inBetaScope` limits the pilot to regions and languages.
- Runbooks: `docs/operations/runbooks/advisor-relay-setup.md`, `advisor-relay-down.md`, `advisor-queue-stuck.md`, `advisor-meta-app-review.md`, `advisor-port-to-twilio.md`, `secrets-rotation.md`.
- `AGENTS.md` → Agent merge authority: agents can merge and deploy within the task's scope, but not change credentials, add paid services or weaken gates.

## Plan

1. Pre-check (read-only): `gh variable list`, `gh secret list` (names only), `git log` for the TA PRs, then run the advisor test suites locally. Output a status table.
2. Open a tracking issue (draft text in the PR description if issue creation isn't authorised) listing the owner items with checkboxes and links to the exact runbook sections.
3. Flip steps happen only after the owner writes "go step N" in the tracking issue or chat, following § Flip order exactly.
4. Post-launch monitoring per `11-testing-rollout.md` metrics and kill switches.

## Files to create or modify

| File | Change |
| --- | --- |
| `docs/plans/text-advisor/README.md` | status log lines per step (dated) |
| `docs/plans/text-advisor/11-testing-rollout.md` | tick the owner items as the owner completes them (only with evidence) |
| none in `server/` | no code changes expected |

## Edge cases

- A preflight fails at the dark stage: stop, set `TEXT_ADVISOR_ENABLED=false` (rollback), and report.
- Repo variables are not readable by the agent token: report "unknown", never guess.

## Dependencies

Owner decisions and accounts. Independent of specs 01–08.
