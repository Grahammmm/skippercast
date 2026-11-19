# Runbook: the fleet AIS listener is down or silent

**Symptom:** `<FLEET_VAR>/CA/ais/heartbeat.json` on the data runner box is older than a few minutes, or its `last_message_at` stops moving; the *Fleet AIS listener* workflow (`fleet-ais-listener.yml`, in the private `Grahammmm/skippercast-ops`) failed with "shows no aisstream messages"; the `fleet-ais-stale` issue is open in this repository (heartbeat stale for more than 3 hours).
**Severity:** SEV3. AIS data is internal only (D8) and nothing user-facing depends on it in real time, but aisstream has no replay: every minute the listener is down is lost from the raw store (MarineCadastre backfill, CF-47, can fill a gap months later, for planning use only).
**Owner:** repository owner (the box, the aisstream account and the key). An agent can read the heartbeat and logs on the box when given a shell, and opens fix PRs.
**Setup reference:** [design.md § 10](../../plans/charter-fleet/design.md#10-ais-listener), [runners](../runners.md#the-fleet-ais-listener).

## Where the controls live

The fleet jobs run from the private repository **`Grahammmm/skippercast-ops`** (operators only), on our own runners labelled `skippercast-ops`. Each job checks out this repository's `main` and runs its code. This public repository keeps the hosted monitor (`fleet-health.yml`) and the Worker, and has no fleet job to dispatch. Dispatch, rerun and switch the jobs in the private repository: every `gh workflow run` and `gh run list` for them takes `--repo Grahammmm/skippercast-ops`.

| Control | Repository | What it does |
| --- | --- | --- |
| `fleet-ais.yml`, `fleet-osint.yml`, `fleet-registry.yml`, `fleet-ais-listener.yml` | private `Grahammmm/skippercast-ops` | The fleet jobs: runs, logs, summaries, dispatch. |
| `ENABLE_FLEET` variable | private `Grahammmm/skippercast-ops` | Switches the fleet jobs. A job is skipped while it is not `true`, and on any ref but `main`. |
| `FLEET_REGION`, `FLEET_OSINT_PARALLEL` variables | private `Grahammmm/skippercast-ops` | The scheduled runs' region (default `CA`) and the OSINT parallelism. |
| `fleet-health.yml`, the `fleet-ais-stale` issue | public `Grahammmm/skippercast` | The hosted hourly staleness monitor. It reads only the Worker's health route; its issue links the private processor runs (operators only) and this runbook. |
| `ENABLE_FLEET`, `FLEET_REGION` variables | public `Grahammmm/skippercast` | Switch and region of the monitor only; they start or stop no fleet job. Keep `ENABLE_FLEET` `true` so the monitor keeps alerting. |
| `FLEET_ENABLED` variable | public `Grahammmm/skippercast` | The Worker's fleet routes; it reaches the Worker with the next deploy. Off, every `/api/fleet/jobs/*` call answers 404. |

The private run logs and summaries still carry counts only, never boat names, contacts or positions.

## What runs where

The listener is `python -m skippercast.fleet.ais listen --region CA`, a **user** systemd unit of the runner user (`runner`, home `/opt/actions-runner`, from `scripts/runner/setup.sh`), not an Actions job. `scripts/fleet/install_listener.sh` installs it; the private `fleet-ais-listener.yml` workflow runs that script, from a checkout of this repository's `main`, on a `skippercast-ops` runner.

| What | Where (`~` is the runner user's home) |
| --- | --- |
| Unit template | `~/.config/systemd/user/skippercast-fleet-ais@.service` (from `scripts/fleet/`), instance `skippercast-fleet-ais@CA` |
| Deployed revisions | `~/.local/share/skippercast/app/<sha>/` (code plus its own `.venv`); `app/current` and `app/previous` are symlinks; the newest three revisions are kept |
| Environment | `~/.config/skippercast/fleet-ais.env`, mode 0600: `AISSTREAM_API_KEY`, `SKIPPERCAST_FLEET_VAR`, `SKIPPERCAST_GIT_SHA` |
| Raw store, heartbeat, watch list | `~/.local/share/skippercast/fleet/CA/ais/` (`raw/YYYY-MM-DD.sqlite`, `heartbeat.json`, `watch.json`) |

Every command below runs **as the runner user** with its user manager in reach. From an SSH session on the box:

```bash
sudo -iu runner
export XDG_RUNTIME_DIR=/run/user/$(id -u)
```

## First install (owner steps, once)

1. **aisstream key.** Sign in at [aisstream.io](https://aisstream.io) and create an API key. Use is internal only until aisstream publishes written terms (D8).
2. **Key file.** The private listener workflow passes no Actions secret: the installer takes `AISSTREAM_API_KEY` from its environment or reuses the one in `~/.config/skippercast/fleet-ais.env`. On the box, as the runner user, write the key there (read at the prompt, so it stays out of shell history and the process list):
   ```bash
   mkdir -p ~/.config/skippercast && chmod 700 ~/.config/skippercast
   ( umask 077; read -rs -p 'Key: ' k; printf 'AISSTREAM_API_KEY=%s\n' "$k" > ~/.config/skippercast/fleet-ais.env; unset k )
   ls -l ~/.config/skippercast/fleet-ais.env   # -rw------- and owned by the runner user
   ```
   The install then rewrites the file with the key, `SKIPPERCAST_FLEET_VAR` and `SKIPPERCAST_GIT_SHA`.
3. **Linger.** On the box: `sudo loginctl enable-linger runner`, then check `loginctl show-user runner -p Linger` prints `Linger=yes`. Without it the runner user has no systemd manager outside a login session; the install stops with "no user systemd manager" and the unit would not survive a reboot.
4. **Variables.** Set `FLEET_ENABLED=true` in this repository (the Worker) and `ENABLE_FLEET=true` in the private repository (`gh variable set ENABLE_FLEET --body true --repo Grahammmm/skippercast-ops`), in that order (design.md § 16 flip order: `FLEET_ENABLED`, then `ENABLE_FLEET`, then the listener install). The private workflow's job is skipped while its `ENABLE_FLEET` is unset. This repository's `ENABLE_FLEET` switches only the monitor (above).
5. **Dispatch once.** `gh workflow run fleet-ais-listener.yml --repo Grahammmm/skippercast-ops -f region=CA`, then `gh run watch --repo Grahammmm/skippercast-ops`. The run copies the revision, builds the virtualenv, writes the env file, restarts the unit and passes only when the heartbeat shows messages within 90 seconds (the first heartbeat comes at start, the second 60 seconds later with the first minute's counts).

To deploy a later `main`, dispatch the private workflow again. It never runs on a push or a schedule.
The installer prefers a non-empty `AISSTREAM_API_KEY` from its environment. If it is unset or
empty, the installer reuses the key in `~/.config/skippercast/fleet-ais.env`. With no key in
either place, it stops before building or restarting the listener.

## Diagnose, in this order

1. **Heartbeat.** `jq '{written_at, started_at, git_sha, connected, last_message_at, messages_per_min, reconnects, idle_reconnects, last_error, drops, queue_depth}' ~/.local/share/skippercast/fleet/CA/ais/heartbeat.json`
   - `written_at` more than 2 minutes old: the process is not running or is stuck. Go to step 2.
   - `connected: false`, `reconnects` climbing, `last_error` set: the stream is failing. Go to step 4 (egress), then step 5 (key).
   - `connected: true` but `messages_per_min` 0 for several heartbeats: the subscription is accepted and empty (bounding box in `regions/CA/fleet.json`, `mmsi_filter` with an empty watch list) or aisstream is quiet. The listener reconnects by itself after 120 s without a message (`idle_reconnects`).
   - `drops` growing: the writer is behind (disk full or slow); `df -h ~` and step 3.
2. **Unit state.** `systemctl --user status skippercast-fleet-ais@CA`. `activating (auto-restart)` with exit status 2 means a configuration error (usually no key: step 5); other exit codes mean a crash, see the log. `Unit ... not found` means it was never installed for this user: dispatch the private listener workflow (first install, step 5).
3. **Logs.** `journalctl --user -u skippercast-fleet-ais@CA -n 200 --no-pager` (add `-f` to follow). Log lines are JSON from `skippercast.log`. The runner user is a system user (UID below 1000), and journald writes system users' units to the **system** journal, so this can print nothing; then read the same lines with `sudo journalctl _SYSTEMD_USER_UNIT=skippercast-fleet-ais@CA.service -n 200 --no-pager`.
4. **Direct egress to aisstream.** The listener's WebSocket client has no proxy support: the box must reach `stream.aisstream.io:443` directly.
   ```bash
   python3 -c 'import socket; socket.create_connection(("stream.aisstream.io", 443), timeout=10); print("reachable")'
   ```
   A timeout or "Network is unreachable" means a firewall, proxy-only egress or DNS problem on the box or its network: fix that, not the listener. Check `cat /etc/resolv.conf` and whether other outbound HTTPS works.
5. **The key.** An expired, revoked or mistyped key shows up as the connection ending soon after each subscription (`AIS connection lost ...; reconnecting` repeating in the log, or an error frame in `last_error`) while `last_message_at` stays null. That looks like an egress problem, so do step 4 first. Create a new key at aisstream.io, write it to `~/.config/skippercast/fleet-ais.env` on the box exactly as in first install step 2, and dispatch the private listener workflow (step 5): the install rewrites the env file around the new key and restarts the unit. There is no Actions secret to set. Never paste the key into an issue, a PR or a log; [secrets rotation](secrets-rotation.md) covers a leaked key.
6. **A bad revision.** If the failures started with a deploy (`git_sha` in the heartbeat is the new revision, `app/previous` is the last good one), roll back (below), then fix forward with a PR.

## Processor schedule and publication

The processor's intended cadence is every half hour, at `:17` and `:47` UTC in
the private `fleet-ais.yml` (`Grahammmm/skippercast-ops`). GitHub schedule events are best effort: [they can be delayed or
dropped](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule).
These off-hour slots reduce exposure to the start-of-hour peak; changing slots
alone does not prove that trigger delivery has recovered.

For a cadence gap, in the private repository check that the workflow is active
on default `main`, its `ENABLE_FLEET` is true, a runner labelled `skippercast-ops`
is online, and the latest **schedule** event exists
(`gh run list --repo Grahammmm/skippercast-ops --workflow fleet-ais.yml --event schedule --limit 5`).
No run record means there is no runner job yet; an existing queued run
may instead be waiting on the `fleet-ais` concurrency group. It intentionally
serializes normal processing and backfill without cancelling the active run.
A newer pending run can replace an older pending run in the same group; this is
not an unbounded queue. Backfills
have a 150-minute timeout; normal runs retain their 25-minute timeout.

The processing step logs run kind, trigger, scheduled cron and source revision,
without input paths, tokens or vessel identities. Verify a natural `schedule`
event with `kind=normal`, successful heartbeat/trip/aggregate processing and
publication, then later scheduled runs, before declaring cadence recovered.
A manual normal run proves processing; a historical backfill proves its window.
Neither proves scheduled delivery. The three-hour Worker health threshold is a
staleness alert, not a half-hour cadence check.

The health answer and the `fleet-ais-stale` issue name a likely `cause`
(derived from the three ages; the heartbeat is stored only when the processor
pushes it). Check first:

| `cause` | Meaning | Check first |
| --- | --- | --- |
| `processor-not-delivered` | all three clocks are equally old: no processor run arrived | the private `fleet-ais.yml` schedule run list (above), not the listener; never restart the listener for it |
| `listener-stale` | the processor ran but carried a heartbeat more than 10 min old | the listener service and its log ("Diagnose", above) |
| `no-messages` | the listener is alive but heard no AIS message for 3 h | the AIS feed and geofence before the listener |
| `no-data` | no processor push or heartbeat is stored, or a time is unreadable | first install and the processor's heartbeat step |

Local `state.sqlite` logs historical and normal runs. Backfill/window runs
leave the Worker's ordinary heartbeat and processed clocks alone, so a newer
local finished timestamp is not evidence that ordinary publication advanced.
Preserve the separate clocks and source/event receipts. Do not restart the live
listener, change retention or weaken identity checks to repair a missing trigger.

## Restart

```bash
systemctl --user restart skippercast-fleet-ais@CA
sleep 90; jq '{started_at, git_sha, last_message_at, messages_per_min}' ~/.local/share/skippercast/fleet/CA/ais/heartbeat.json
```

The restart is clean: SIGTERM makes the listener flush its queue and write a last heartbeat. `Restart=always` brings a crashed process back after 10 seconds, with no start limit; a reboot starts it again through linger and `WantedBy=default.target`. To stop it on purpose: `systemctl --user disable --now skippercast-fleet-ais@CA` (enable it again with `enable --now`, or a dispatch of the private listener workflow).

## Roll back to the previous `<sha>`

```bash
ls -lt ~/.local/share/skippercast/app/          # kept revisions, newest first
readlink ~/.local/share/skippercast/app/current ~/.local/share/skippercast/app/previous
bash ~/.local/share/skippercast/app/current/scripts/fleet/install_listener.sh --region CA --rollback          # to app/previous
bash ~/.local/share/skippercast/app/current/scripts/fleet/install_listener.sh --region CA --rollback <sha>    # to any kept <sha>
```

`--rollback` points `app/current` at that revision (the one it replaces becomes `app/previous`, so running it again flips back), rewrites only `SKIPPERCAST_GIT_SHA` in the env file (the key and mode 0600 are kept), reinstalls that revision's unit file, restarts and runs the same 90-second heartbeat check. It needs no key in the environment and builds nothing.

If the script itself is broken, do the same by hand:

```bash
cd ~/.local/share/skippercast/app
ln -sfn <sha> .current.new && mv -Tf .current.new current
sed -i "s/^SKIPPERCAST_GIT_SHA=.*/SKIPPERCAST_GIT_SHA=<sha>/" ~/.config/skippercast/fleet-ais.env   # keeps mode 0600
systemctl --user restart skippercast-fleet-ais@CA
```

The private listener workflow runs only from its `main` and always checks out this repository's `main` (its job is skipped for any other ref, so the key never reaches unreviewed code), and there is no `--ref <branch>` dispatch. A revision older than the three kept ones is gone from the box: revert the bad change on `main` through a PR and dispatch the private workflow again. Either way, the next dispatch from `main` deploys whatever `main` holds, so land the fix or the revert first.

## Remove the listener

```bash
systemctl --user disable --now skippercast-fleet-ais@CA
rm ~/.config/systemd/user/skippercast-fleet-ais@.service ~/.config/skippercast/fleet-ais.env
systemctl --user daemon-reload
rm -rf ~/.local/share/skippercast/app
```

The raw store under `~/.local/share/skippercast/fleet/` stays; its retention runs only while the listener runs, so delete day files by hand if it is gone for good. Revoke the key at aisstream.io; the env file removed above held the only copy the listener used.
