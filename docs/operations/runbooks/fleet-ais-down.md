# Runbook: the fleet AIS listener is down or silent

**Symptom:** `<FLEET_VAR>/CA/ais/heartbeat.json` on the data runner box is older than a few minutes, or its `last_message_at` stops moving; the *Fleet AIS listener* workflow (`fleet-ais-listener.yml`) failed with "shows no aisstream messages"; once CF-45 lands, the `fleet-ais-stale` issue is open (heartbeat stale for more than 3 hours).
**Severity:** SEV3. AIS data is internal only (D8) and nothing user-facing depends on it in real time, but aisstream has no replay: every minute the listener is down is lost from the raw store (MarineCadastre backfill, CF-47, can fill a gap months later, for planning use only).
**Owner:** repository owner (the box, the aisstream account and the secret). An agent can read the heartbeat and logs on the box when given a shell, and opens fix PRs.
**Setup reference:** [design.md § 10](../../plans/charter-fleet/design.md#10-ais-listener), [runners](../runners.md#the-fleet-ais-listener).

## What runs where

The listener is `python -m skippercast.fleet.ais listen --region CA`, a **user** systemd unit of the runner user (`runner`, home `/opt/actions-runner`, from `scripts/runner/setup.sh`), not an Actions job. `scripts/fleet/install_listener.sh` installs it; the `fleet-ais-listener.yml` workflow runs that script on `vars.DATA_RUNNER`.

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
2. **Secret.** `gh secret set AISSTREAM_API_KEY --repo Grahammmm/skippercast` and paste the key at the prompt (not on the command line, so it stays out of shell history).
3. **Linger.** On the box: `sudo loginctl enable-linger runner`, then check `loginctl show-user runner -p Linger` prints `Linger=yes`. Without it the runner user has no systemd manager outside a login session; the install stops with "no user systemd manager" and the unit would not survive a reboot.
4. **Variables.** `DATA_RUNNER` is already set for the data jobs; set `ENABLE_FLEET=true` (design.md § 16 flip order: `FLEET_ENABLED`, then `ENABLE_FLEET`, then the listener install). The workflow's job is skipped while either is unset.
5. **Dispatch once.** `gh workflow run fleet-ais-listener.yml --repo Grahammmm/skippercast -f region=CA`, then `gh run watch`. The run copies the revision, builds the virtualenv, writes the env file, restarts the unit and passes only when the heartbeat shows messages within 90 seconds (the first heartbeat comes at start, the second 60 seconds later with the first minute's counts).

To deploy a later `main`, dispatch the workflow again. It never runs on a push or a schedule.

## Diagnose, in this order

1. **Heartbeat.** `jq '{written_at, started_at, git_sha, connected, last_message_at, messages_per_min, reconnects, idle_reconnects, last_error, drops, queue_depth}' ~/.local/share/skippercast/fleet/CA/ais/heartbeat.json`
   - `written_at` more than 2 minutes old: the process is not running or is stuck. Go to step 2.
   - `connected: false`, `reconnects` climbing, `last_error` set: the stream is failing. Go to step 4 (egress), then step 5 (key).
   - `connected: true` but `messages_per_min` 0 for several heartbeats: the subscription is accepted and empty (bounding box in `regions/CA/fleet.json`, `mmsi_filter` with an empty watch list) or aisstream is quiet. The listener reconnects by itself after 120 s without a message (`idle_reconnects`).
   - `drops` growing: the writer is behind (disk full or slow); `df -h ~` and step 3.
2. **Unit state.** `systemctl --user status skippercast-fleet-ais@CA`. `activating (auto-restart)` with exit status 2 means a configuration error (usually no key: step 5); other exit codes mean a crash, see the log. `Unit ... not found` means it was never installed for this user: dispatch the workflow.
3. **Logs.** `journalctl --user -u skippercast-fleet-ais@CA -n 200 --no-pager` (add `-f` to follow). Log lines are JSON from `skippercast.log`. The runner user is a system user (UID below 1000), and journald writes system users' units to the **system** journal, so this can print nothing; then read the same lines with `sudo journalctl _SYSTEMD_USER_UNIT=skippercast-fleet-ais@CA.service -n 200 --no-pager`.
4. **Direct egress to aisstream.** The listener's WebSocket client has no proxy support: the box must reach `stream.aisstream.io:443` directly.
   ```bash
   python3 -c 'import socket; socket.create_connection(("stream.aisstream.io", 443), timeout=10); print("reachable")'
   ```
   A timeout or "Network is unreachable" means a firewall, proxy-only egress or DNS problem on the box or its network: fix that, not the listener. Check `cat /etc/resolv.conf` and whether other outbound HTTPS works.
5. **The key.** An expired, revoked or mistyped key shows up as the connection ending soon after each subscription (`AIS connection lost ...; reconnecting` repeating in the log, or an error frame in `last_error`) while `last_message_at` stays null. That looks like an egress problem, so do step 4 first. Create a new key at aisstream.io, `gh secret set AISSTREAM_API_KEY`, and dispatch the workflow: it rewrites the env file. Never paste the key into an issue, a PR or a log; [secrets rotation](secrets-rotation.md) covers a leaked key.
6. **A bad revision.** If the failures started with a deploy (`git_sha` in the heartbeat is the new revision, `app/previous` is the last good one), roll back (below), then fix forward with a PR.

## Restart

```bash
systemctl --user restart skippercast-fleet-ais@CA
sleep 90; jq '{started_at, git_sha, last_message_at, messages_per_min}' ~/.local/share/skippercast/fleet/CA/ais/heartbeat.json
```

The restart is clean: SIGTERM makes the listener flush its queue and write a last heartbeat. `Restart=always` brings a crashed process back after 10 seconds, with no start limit; a reboot starts it again through linger and `WantedBy=default.target`. To stop it on purpose: `systemctl --user disable --now skippercast-fleet-ais@CA` (enable it again with `enable --now`, or a workflow dispatch).

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

A revision older than the three kept ones is gone from the box: push a branch or tag at it and dispatch the workflow there (`gh workflow run fleet-ais-listener.yml --ref <branch> -f region=CA`). Either way, the next dispatch from `main` moves forward again, so land the fix first.

## Remove the listener

```bash
systemctl --user disable --now skippercast-fleet-ais@CA
rm ~/.config/systemd/user/skippercast-fleet-ais@.service ~/.config/skippercast/fleet-ais.env
systemctl --user daemon-reload
rm -rf ~/.local/share/skippercast/app
```

The raw store under `~/.local/share/skippercast/fleet/` stays; its retention runs only while the listener runs, so delete day files by hand if it is gone for good. Delete the `AISSTREAM_API_KEY` secret and revoke the key at aisstream.io.
