# Runbook: the fleet OSINT run

**Use when:** switching the charter fleet's OSINT step on (first run), a weekly *Fleet OSINT* run (`fleet-osint.yml`) failed or left batches failed, a run must be resumed, the subscription token expired, or the pinned Claude Code version must change.
**Severity:** SEV4. Nothing user-facing changes in real time: boats keep their earlier facts and the next Sunday run catches up. Raise it to SEV3 if the run refuses to start (token, version) two weeks in a row.
**Owner:** repository owner (the token, variables, the box). An agent can dispatch the workflow, read its summary and, given a shell on the box, the run directory; it opens fix PRs.
**Setup reference:** [design.md § 8](../../plans/charter-fleet/design.md#8-the-osint-agent-step), [runners](../runners.md#the-fleet-osint-run), [fleet registry run](fleet-registry.md) (the pipeline it fills in), [threat model § 10.4](../../legal/threat-model.md).

## What runs where

`fleet-osint.yml` runs every Sunday at 10:17 UTC and on dispatch, on `vars.DATA_RUNNER` (Hermes), only from `main`, only while `ENABLE_FLEET` is `true`. It never triggers on `pull_request`. One job, four steps:

1. **Plan.** `python -m skippercast.fleet plan-agent --region CA --sink worker --run-id <id> --mode full` reads the registry snapshot and writes batch manifests of at most 20 boats (new, stale or incomplete; removal-requested boats are never selected) to `<run dir>/manifests/batch-NNN.json`. A resumed run skips this step and keeps its manifests.
2. **Research.** `python scripts/fleet/run_osint.py --region CA --run-id <id> --claude <pinned CLI>` runs each pending batch as one headless `claude -p` session with the `charter-osint` agent (`.claude/agents/charter-osint.md`), `FLEET_OSINT_PARALLEL` (default 3) at a time, 60 minutes each. Each session writes `profiles/<vessel_id>.json` and `summaries/<batch_id>.md` in the run directory. A failed batch is retried once; each batch's status goes to `state.json` under `osint`.
3. **Ingest.** `python -m skippercast.fleet ingest --region CA --sink worker --run-id <id> --profiles <run dir>/profiles` validates every profile (schema, off-limits hosts, MMSI agreement), refuses and lists invalid ones, and writes the rest to the registry as `osint` facts through `/api/fleet/jobs/registry` with a GitHub OIDC token.
4. **Fail when a batch failed**, after ingesting the batches that finished, so the job is red and the run can be resumed.

| Dispatch input | Default (and the schedule's value) | What |
| --- | --- | --- |
| `region` | `CA` (the schedule uses `vars.FLEET_REGION`, else `CA`) | A region with `regions/<id>/fleet.json`. |
| `mode` | `full` | `full` selects new, stale and incomplete boats; `refresh` only new and stale ones. Ignored when resuming. |
| `sink` | `worker` | `worker` reads and writes the registry (D1); `staging` uses the SQLite registry on the box (`fleet-staging`). |
| `max_batches` | empty: all | Research at most this many pending batches; the rest stay pending for a resume. |
| `run_id` | empty: a new run | Resume this run (same sink): done batches are skipped, failed and pending ones run. |

The summary prints the run id first, then counts only (`plan-agent` counts, `{"batches", "done", "failed", "not_run", "skipped_done", "profiles"}`, ingest counts). Never boat names, contacts or agent output: workflow logs are readable by anyone who can read the repository.

Files on the box (`~` is the runner user's home):

| What | Where |
| --- | --- |
| The subscription token | `~/.config/skippercast/claude.env` (mode 0600; `CLAUDE_CODE_OAUTH_TOKEN=...`) |
| The pinned CLI | `~/.local/share/skippercast/claude-code/<version>/node_modules/.bin/claude` (installed by the workflow when missing) |
| Run directory | `~/.local/share/skippercast/fleet/<REGION>/runs/<run_id>/` (staging: `fleet-staging`) |
| In it | `agent-plan.json`, `manifests/batch-NNN.json`, `profiles/<vessel_id>.json`, `summaries/<batch_id>.md`, `osint/<batch_id>.json` (the session's JSON result), `osint/<batch_id>.stderr.log`, `osint/agents.json`, `state.json`, `profiles-ingest.json` |
| Agent fetch cache | `<var>/<REGION>/http-cache/agent/` (the manifest's `policy.cache_dir`) |

All of it is registry data: it stays on the box, never in git, an issue or a PR.

## First run (owner steps, once)

1. **Registry first.** The [fleet registry run](fleet-registry.md) has run at least once (`FLEET_ENABLED` and `ENABLE_FLEET` are `true`, `DATA_RUNNER` is set), so there are boats to research.
2. **Subscription token, on Hermes as the runner user.** The OSINT run uses the Claude subscription only, never an API key. Run `claude setup-token` (here through `npx` at the pinned version, before the workflow has installed it) and save the token:

   ```bash
   npx -y @anthropic-ai/claude-code@2.1.289 setup-token   # opens the browser sign-in; prints a one-year token
   mkdir -p ~/.config/skippercast && chmod 700 ~/.config/skippercast
   ( umask 077; read -rs -p 'Token: ' t; printf 'CLAUDE_CODE_OAUTH_TOKEN=%s\n' "$t" > ~/.config/skippercast/claude.env; unset t )
   ls -l ~/.config/skippercast/claude.env   # -rw------- and owned by the runner user
   ```

   The token is not a GitHub secret and must not be one. Do not put `ANTHROPIC_API_KEY` in that file, the runner's environment or the workflow: the runner exits 2 when it is set (also `ANTHROPIC_AUTH_TOKEN` and the Bedrock, Vertex and Foundry switches), so no run can bill the API.
3. **Parallelism (optional).** [Repository variable](https://github.com/Grahammmm/skippercast/settings/variables/actions) `FLEET_OSINT_PARALLEL` (1–8, default 3). Lower it if the subscription's usage limits stop batches.
4. **A small run first.** `gh workflow run fleet-osint.yml --repo Grahammmm/skippercast -f region=CA -f sink=worker -f max_batches=1`, then `gh run watch`. Check the summary: one batch `done`, `profiles` > 0, ingest `refused` 0. On the box, read `summaries/batch-001.md` and a profile or two before letting the schedule run every batch.
5. The schedule takes over from the next Sunday. Design § 9's order from an empty registry: registry `run`, then this run, then registry `run` again.

## Pinned Claude Code CLI and its flags

The pin is `CLAUDE_CODE_VERSION` in `scripts/fleet/run_osint.py`: `2.1.289` (npm `@anthropic-ai/claude-code`). The workflow installs that version (`--print-cli-version`) and the runner refuses any other (`claude --version`), then requires `claude auth status` to report `authMethod` `oauth_token` with provider `firstParty`, so an `apiKeyHelper` or a stored Console key cannot take over. The session runs with `DISABLE_AUTOUPDATER=1`.

Each batch runs, with the prompt on stdin and the run directory as working directory:

| Flag | Value | Why |
| --- | --- | --- |
| `-p` | | Print (headless) mode. |
| `--agents` | `<run dir>/osint/agents.json` | The `charter-osint` definition built from `.claude/agents/charter-osint.md` (file form needs 2.1.281 or later with `--print`). |
| `--agent` | `charter-osint` | Runs that agent as the session: its body replaces the system prompt, its `model` and `tools` apply. |
| `--tools` | `Read,Write,Glob,Grep,WebFetch,WebSearch,Bash` | The only built-in tools available; the runner refuses an agent file whose `tools` differ. |
| `--allowedTools` | `WebFetch`, `WebSearch`, `Bash(python -m skippercast.fleet validate-profile *)`, `Edit(//<run dir>/profiles/**)`, `Edit(//<run dir>/summaries/**)`, `Edit(//<cache dir>/**)` | Pre-approved calls. Writes are checked against `Edit` path rules. Reads need no rule inside the working directories and are denied outside them. |
| `--disallowedTools` | `WebFetch(domain:<host>)` and `WebFetch(domain:*.<host>)` for every host in `catalog/fleet/off-limits.json`, and `mcp__*` | The D7 hosts are refused at fetch time (deny wins over allow); no MCP tools. |
| `--permission-mode` | `dontAsk` | Every call not pre-approved is denied. |
| `--permission-prompts` | `none` | Nobody answers prompts; Claude is told not to retry a denial (2.1.259 or later). |
| `--max-turns` | `200` | Bounds a batch (documented in the CLI reference; `--help` does not list it). |
| `--output-format` | `json` | One result object: `subtype`, `is_error`, `num_turns`, `permission_denials`, `result`. |
| `--add-dir` | `<repo>/schemas`, `<repo>/catalog/fleet`, the cache directory | Read access to the schema, the off-limits list and the fetch cache; only the cache is writable. |
| `--strict-mcp-config` | | No MCP servers from the box's configuration. |
| `--no-session-persistence` | | No transcript of registry research under `~/.claude`. |
| `--disable-slash-commands` | | No skills or custom commands. |

`--bare` is not used: bare mode never reads `CLAUDE_CODE_OAUTH_TOKEN`. The session's environment is an allowlist (`PASS_ENV` in the script): the job's OIDC request token, `GITHUB_TOKEN` and any other secret never reach it.

These were checked against `claude --help` of 2.1.289 and the [CLI reference](https://code.claude.com/docs/en/cli-reference), [headless](https://code.claude.com/docs/en/headless), [authentication](https://code.claude.com/docs/en/authentication) and [permissions](https://code.claude.com/docs/en/permissions) pages (October 2026).

**Changing the pin.** In a PR: set `CLAUDE_CODE_VERSION`, re-read `claude --help` and the pages above for every flag in the table (removed or renamed flags, changed defaults, the `--agents` file form, `authMethod` values), update this table, and run `python -m pytest tests/unit/test_fleet_run_osint.py`. After merging, dispatch with `max_batches=1` before the schedule runs.

## Reruns and resume

- **Some batches failed** (the job is red, `failed` > 0): the batches that finished were ingested. Resume: `gh workflow run fleet-osint.yml --repo Grahammmm/skippercast -f region=CA -f sink=worker -f run_id=<id>`. Done batches are skipped; each failed one gets another try and one retry. Profiles written by a failed attempt that pass validation are ingested too.
- **A batch that fails every time:** on the box, `jq '.osint.batches["batch-NNN"]' <run dir>/state.json` (status, attempts, exit code, error, profiles written, turns, denials) and `jq '{subtype, is_error, num_turns, permission_denials}' <run dir>/osint/batch-NNN.json`. `timed out after 60 min` or `error_max_turns`: the batch is too slow; lower `max_requests_per_boat` or the batch size in a PR. Many `permission_denials`: the agent keeps calling something the session denies (an off-limits host, a write outside `profiles/`); read `summaries/batch-NNN.md` and fix the agent file in a PR.
- **A new run instead of a resume** plans again from the registry: boats a failed batch held are selected again (they are still unprofiled), so either works; a resume keeps the done batches' work and costs less.

## Failures before any batch (exit 2)

| Message | Fix |
| --- | --- |
| `ANTHROPIC_API_KEY is set: the OSINT run uses the Claude subscription only` | Remove it from the runner's environment (the runner service's `.env`, `~/.profile`) or from `claude.env`. Never "fix" this by changing the script. |
| `no CLAUDE_CODE_OAUTH_TOKEN in the environment and no ~/.config/skippercast/claude.env` | First run, step 2. |
| `... mode 0644; the token file must be 0600` | `chmod 600 ~/.config/skippercast/claude.env`. |
| `claude auth status reports authMethod 'api_key_helper'` (or `api_key`) | A settings file on the box sets `apiKeyHelper`, or a Console login stored a key: remove it (`claude auth logout` as the runner user); the token in `claude.env` must be the one in use. |
| `claude auth status reports authMethod 'none'` or sessions fail with an authentication error | The token expired (one year) or was revoked: repeat first-run step 2. |
| `Claude Code X found, 2.1.289 pinned` | The install step failed or something else is on `PATH`; read the install step's log. |
| `... no plan-agent output` | The plan step failed (read its log), or a resume named a run id from the other sink. |

## Related

- `.claude/agents/charter-osint.md`: the agent, its manifest contract, allowed sources and the D7 off-limits list and handle rule (`tests/unit/test_fleet_run_osint.py` checks it against `catalog/fleet/off-limits.json` and `src/skippercast/fleet/agent.py`).
- [Secrets rotation](secrets-rotation.md): rotate the token on any runner compromise.
