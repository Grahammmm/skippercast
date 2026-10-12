# Working on SkipperCast (AI agents and people)

Codex and Claude both work in this repository. These rules keep `main`
deployable while two agents push changes in parallel. `CLAUDE.md` points
here, so both agents follow the same file. Read [CONTRIBUTING.md](CONTRIBUTING.md)
for data, licensing and privacy rules; they apply to agents too.

## Branches and pull requests

- **Never push to `main`.** Every change reaches `main` through a pull request
  that passes CI. Branch protection enforces this.
- **One task, one branch, one PR.** Name branches by agent and task:
  `codex/<short-task>` or `claude/<short-task>` (for example
  `codex/audit-estero-bag`, `claude/tomorrow-screen`).
- **Do not commit to another agent's open branch.** Comment on its PR instead.
- **Start from a fresh `main`** and rebase onto it before asking for review
  (`git fetch origin main && git rebase origin/main`). `main` requires branches
  to be up to date, so two PRs that pass alone cannot break it together.
- **Keep PRs small.** One audit, one feature or one fix. Split anything that
  touches both source data and app code.
- Fill in the PR template: what changed, why, how it was checked, and anything
  the reviewer must decide.

## Generated files: change the source, then rebuild

Much of `dist/` and `atlas/` is generated. Editing it by hand is the most common
way this repository has broken: CI now fails when rebuilt output differs from
the commit.

| To change | Edit | Then run |
| --- | --- | --- |
| Region coverage, notes, contracts (`dist/regions/*/coverage.json`, `region.json`, `manifest.json`, `region-default.js`) | `regions/<id>/region.json`, `catalog/`, `src/skippercast/platform/` | `PYTHONPATH=src python -m skippercast.platform.build` |
| Species search plans (`dist/regions/*/search-plans.json`) | `regions/`, `catalog/search-methods.json`, `scripts/build_search_plans.py` | `python scripts/build_search_plans.py` (needs `requirements-survey.txt`) |
| Worker and client bundle (`dist/client`, `dist/server`) | `dist/*.js`, `dist/*.html`, `web/` (client TypeScript and Preact), `server/` (TypeScript, entry `server/index.ts`; plain names; Vite (`vite.config.mjs`) bundles and hashes them, so never add `-v200` copies, `?v=` tags or hand-written `modulepreload` links) | `pnpm typecheck && pnpm build && node scripts/check_client.mjs` |

Commit the regenerated files in the same PR as the source change.

## Research tooling

`research/` holds dated audit, screening and discovery tooling (see
[research/README.md](research/README.md)). Product code (`src/`, `server/`,
`dist/`, `scripts/`) never imports or runs it; `tests/contract/test_research_boundary.py`
fails if it does. New audit scripts go in `research/scripts/`, not `scripts/`.

## Before opening a PR

Run what CI runs (Python 3.13 with the survey stack for the full suite; see
[docs/engineering/testing.md](docs/engineering/testing.md) for the layers):

```bash
python -m pip install -e ".[test]"                         # once; add [survey,ocean,publish] for the full suite
python -m pytest -m "not gis"                              # without GIS packages (CI check job)
SKIPPERCAST_REQUIRE_GIS=1 python -m pytest                 # full suite (CI survey-science job)
PYTHONPATH=src python -m skippercast.platform.build && git diff --exit-code
python scripts/check_repository.py
python scripts/check_web.py
node --test tests/test_*.mjs
node scripts/check_copy.mjs                                # copy lint; its baseline only shrinks
pnpm typecheck
pnpm build
```

- Tests stay offline. A test that needs a gitignored local file (`var/`) or the
  network must skip cleanly when it is absent, and should also check the
  committed output so CI still covers it. The full run fails on any skip whose
  reason is not allow-listed in `scripts/pytest_report.py`.
- Never mark a failing check as expected or delete a test to get green.
- On a small machine (2 CPUs), run the tests that cover your change, not the
  whole suite at once; CI runs the full suites.

## Reviewing the other agent's PR

Each agent reviews the other's PRs before merging. Check that:

- the change does what the description says, and nothing else;
- generated files were rebuilt, not hand-edited;
- no claim got stronger than its evidence (depth qualification, catch or
  hotspot language, datum, "ready" statuses);
- tests cover the new behavior;
- nothing private or third-party-restricted was committed.

Approve, or request changes with specific lines.

## Agent merge authority

The owner authorizes Codex and Claude to implement updates, reconcile branches,
obtain independent review, merge reviewed PRs and verify deployment within the
scope of an assigned task without asking for approval at each step. Either agent
may delegate one independent reviewer without further owner confirmation.
The agent completing the task owns the merge and deployment verification;
keep the owner informed of meaningful progress,
failures and any genuinely new decision requiring authorization.

Before merging:

- Obtain an independent review from the other agent or a delegated reviewer;
  resolve every blocking finding. Do not approve your own work as its only review.
  A reviewer is a separate agent that did not build the change.
- Confirm required CI checks pass on the exact current PR head, the branch is
  up to date with `main`, and no conflicts or unresolved change requests remain.
  After updating a branch, wait for its new checks before merging.
- Recheck the final diff for task scope, regenerated output, evidence, privacy
  and data rights. Merge only PRs needed for the authorized task.
- Use GitHub's normal protected-branch merge flow. Never bypass required checks,
  disable branch protection, force-push `main`, or commit directly to `main`.

After merging, confirm the deployed revision and relevant live behavior. For
data changes, confirm publication state and source freshness before reporting
that the data is available. Report failed or incomplete deployment honestly.

This authority does not authorize unrelated changes, new paid services, changes
to credentials or access controls, or weakening security and data-quality gates.
Ask only when a genuinely new decision needs the owner's authorization.

## Commits

- Imperative subject under 72 characters, then a body saying why.
- Agents add their attribution trailer (`Co-Authored-By: ...`).
- Material user-facing changes get a line in [CHANGELOG.md](CHANGELOG.md).

## Releases

Deploy only from `main`: the Cloudflare deploy runs only after Offline checks
pass on a `main` commit, smoke-tests the site and rolls back automatically on
failure. Tag releases (`v0.3.1`, `v0.4.0`) after merging a user-facing change.
Manual rollback: [roll back a release](docs/operations/runbooks/rollback-release.md). The scheduled
data jobs publish to the `conditions` and `data` branches and do not go
through PRs.

## Division of work (current)

- **Codex:** data discovery, source audits, ingestion and regional pipelines.
  Budget: about one day a week of audits unless a user-facing feature needs one.
- **Claude:** product features, app code, CI and reviews of Codex PRs.

Either agent can take any task the owner assigns; the split exists so the two
rarely edit the same files at once.

## Autonomous sessions

Agents keep working without waiting on the owner. The owner often cannot see a
pending approval, so a wait becomes a silent stall.

**Do not stall.**

- Do not wait on an approval or confirmation that the task already authorises.
  Work from the task as written.
- Start sub-agents with plain `Agent` calls. Do not depend on `SendMessage` to
  hand out work, and do not interrupt and restart agents that are running.
- If a tool call is denied or hangs, try another route once. If none exists,
  park that thread: post one comment on the task's tracking issue with the
  exact link or action needed, then continue with every other thread. End the
  session only when every remaining thread is parked.
- Ask the owner only for a genuinely new decision, a change to an owner-area
  file (see `.github/CODEOWNERS`), or anything involving credentials, spending
  or access controls.
- Never push to `main`, bypass a required check, or weaken a security or
  data-quality gate to get unblocked. A denied action is parked, not worked
  around.

**Track work on GitHub.** Keep the to-do list and outstanding tasks as issues
in this repository, not only in chat, so any agent or the owner can pick them
up. Link each PR to its issue.

**Delegate by weight.** The orchestrating agent plans, gates results and
decides. Larger models build and review. Mid-size models do mechanical work
such as rebases and merge stewarding. Small models do grunt work such as
polling CI, summarising issues, extracting fields and running test commands.
Output from a smaller model is never trusted without a gate: a test, a
deterministic check, or review by a larger model. If a unit of work fails
twice, escalate it to the next model tier instead of retrying the same one.
A builder never reviews its own work.

**Fresh containers.** A cloud session starts with no dependencies installed.
Before building, run `pnpm install --frozen-lockfile` and
`python -m pip install -e ".[test]"` and wait for both to finish. Do the work
in a branch or worktree, never on `main`.

## Progress reports

Once a task has been running for 60 minutes, post a short report every 30
minutes until it finishes, in chat and as a comment on the task's tracking
issue. Use exactly three headings:

- **Progress**: what was done since the last report, as features and results
  (PRs opened or merged, checks passed), not a list of steps.
- **Problems**: what broke or is parked, in plain words.
- **Plans**: what happens next. End with **Needed from you**: every action the
  owner must take, each as one direct link or button (the PR to merge, the
  issue to answer), or "nothing needed".

**Options.** When the owner must choose, list every option in order with the
recommended one first and marked "(Recommended)". State each option's
downsides plainly. Use this only for real owner decisions, not for steps the
task already settles.

**Merging.** When a PR is ready for the owner to merge, give the direct PR link
and say what to click (Squash and merge once the checks are green).

## Default SkipperCast workspace on AgentOrange

This section applies when the session has the Tailscale/SSH connection to
AgentOrange. A cloud session without it uses the checkout the session provides
(see "Autonomous sessions") and says so in its first report.

- For future SkipperCast development, documents, datasets and generated outputs, work on AgentOrange through the existing Tailscale/SSH connection (`ssh agentorange`). Confirm remote access before making changes.
- The authoritative repository checkout is `$HOME/skippercast-data/2026-10-07-pge-south/repo`. The seafloor data cache is `$HOME/skippercast-data/2026-10-07-pge-south/repo/var/seafloor/cache`. Keep cache and other private or bulky working data under ignored `var/`; do not commit them. Put reviewed documents, source code and intended generated release outputs in their established repository directories.
- Preserve work from other sessions: check `git status` before edits and use a separate task branch or worktree. Do not reset, clean, overwrite or commit another session's uncommitted work. Follow the branch, review and test rules above.
- Leave the Mac originals in place. Remote access does not authorize deleting or overwriting them. If AgentOrange is unreachable, record the connection problem and do not silently switch future SkipperCast work to a Mac clone.
- These paths describe the current working copy and cache, not evidence that a dataset is fit for publication. Continue the normal provenance, rights, scientific and legal checks for each source.
