# Runbook: the Text Advisor's Mac relay is down

**Symptom:** the Worker logs `advisor_relay_down` (three failed pings in a row, 45 minutes); `GET /api/advisor/health` shows `"relay":{"state":"down",…}`; texts to the advisor get no reply; outbound rows pile up with status `held`; `advisor_send_not_sent` warnings with `http-5xx`, `network` or `timeout`.
**Severity:** SEV3 (replies are delayed, nothing is lost) for the first 6 hours; SEV2 after that, because held replies older than 6 hours are dropped. See [incident response](../incident-response.md).
**Owner:** repository owner (the devices and accounts are the owner's). An agent can read logs, the health endpoint and D1, and open fix PRs.
**Setup reference:** [relay setup](advisor-relay-setup.md).

## What keeps working while it is down

- **Inbound depends on BlueBubbles.** Webhooks come from the Mac. If only the tunnel or Access is broken, BlueBubbles still delivers inbound webhooks to the Worker (they go out, not in) and the messages are stored. If the Mac or BlueBubbles is down, texts still reach Messages on the Mac once it is back, but BlueBubbles does not replay them as webhooks: look in Messages on the Mac for anything received during the outage.
- **Outbound is held, not dropped.** While job_state `advisor.relay` is `down` and `ADVISOR_CHANNEL` is `bluebubbles`, every new reply is written to `advisor_messages` with status `held` (error `relay-down`) and not sent.
- **Release is automatic.** On every cron tick (every 15 minutes) after the watchdog, `releaseHeld` (`server/advisor/consumer.ts`): marks held rows older than 6 hours `failed` (`held-expired`); then, if the relay is `up` again, sends up to 50 held rows, oldest first, through the contact's current adapter. Nothing to replay by hand. After a long outage, a backlog over 50 drains at 50 per tick.

## Diagnose, in this order

1. **Is it really down?** `curl -s https://skippercast.com/api/advisor/health` → `relay.state` and `relay.checked_at`. Workers Logs (Workers & Pages → skippercast → Logs), filter `advisor_relay_down`, `advisor_relay_up`, `advisor_send_not_sent`, `advisor_held_release`.
2. **Through the tunnel, with the token:** from your laptop run `node scripts/advisor/relay-check.mjs --no-send` with the four relay variables set ([setup step 11](advisor-relay-setup.md#11-run-the-relay-check)). Read the first failing line:
   - `environment` → a variable is missing on your laptop, not a relay problem.
   - `ping: HTTP 403` / `302` / "Cloudflare Access rejected the service token" → **Access**: the service token expired or was deleted, or the Access application's policy changed. Zero Trust → Access → Service credentials: check the token's expiry; Applications → `relay.skippercast.com` → policy is **Service Auth** with that token. A new token means new `CF_ACCESS_CLIENT_ID`/`SECRET` GitHub secrets and a deploy.
   - `ping: HTTP 502`, `530`, `1033` or a timeout → **tunnel or Mac**: go to step 3.
   - `ping: HTTP 401` or a relay error about the password → the BlueBubbles password changed; update `BLUEBUBBLES_PASSWORD` and deploy.
   - `ping` passes but `send …` fails → **Messages**: go to step 4.
3. **Tunnel:** Zero Trust → Networks → Tunnels → `skippercast-relay`: **Healthy**, **Down** or **Inactive**. Down/Inactive means `cloudflared` on the Mac is not running or the Mac is off or offline. On the Mac (screen sharing, or in person): `sudo launchctl list | grep cloudflared`; `sudo launchctl kickstart -k system/com.cloudflare.cloudflared`; logs in `/Library/Logs/com.cloudflare.cloudflared.err.log`. Check the Mac has internet.
4. **BlueBubbles and Messages on the Mac:**
   - BlueBubbles is open and its status shows the server running on port 1234; restart it if not.
   - Messages → Settings → iMessage: still signed in, the phone number still ticked under "You can be reached at". A sign-out (often after an Apple Account password change or a security prompt) is the most common cause of sends failing while ping works.
   - macOS updated itself? Check BlueBubbles' release notes for that macOS version; roll back or wait for a BlueBubbles update.
5. **iPhone:** on, charged, on Wi-Fi, SIM active (bars, not "SOS"). Settings → Messages → Send & Receive still shows the number ticked; Text Message Forwarding still lists the Mac. iMessage failing for one contact while SMS works points to the iPhone's registration; SMS failing alone points to forwarding or the carrier (prepaid balance, line suspended).
6. **Apple Account alerts:** sign in at `account.apple.com` and check for a locked account, a password reset request, or a security notice. Apple can rate-limit or lock a new account that sends many first-contact messages; if locked, recover it with the account recovery contact, then sign in again on the iPhone and the Mac.

## Restart order

Restart from the network inward, checking `relay-check.mjs --no-send` after each step and stopping when it passes:

1. iPhone: toggle Wi-Fi, then restart the phone. Wait until Send & Receive shows the number.
2. Mac: quit and reopen Messages; check it is signed in.
3. Mac: quit and reopen BlueBubbles.
4. Mac: `sudo launchctl kickstart -k system/com.cloudflare.cloudflared`.
5. Mac: restart the Mac (auto-login, Login Items and launchd bring everything back; or power-cycle with the smart plug).

The watchdog marks the relay `up` on the first successful ping (within 15 minutes) and the same tick releases held replies. To confirm: `GET /api/advisor/health` shows `up`; Workers Logs shows `advisor_relay_up` and `advisor_held_release`.

## Check the held backlog

```bash
npx wrangler d1 execute skippercast --remote --command \
  "SELECT status, error, COUNT(*) n, MIN(created_at) oldest FROM advisor_messages WHERE direction='out' AND status IN ('held','failed','unknown') GROUP BY status, error"
```

`held` rows are waiting; `failed` with `held-expired` were older than 6 hours and will not be sent (people who texted then get no reply to that message; nothing else to do). `unknown` rows were possibly delivered and are never resent automatically.

## When to stop fixing the relay

Escalate to [move the number to Twilio](advisor-port-to-twilio.md) when any of these holds:

- the relay has been down for **more than 48 hours** despite the restart order above;
- the dedicated **Apple Account is suspended, locked or disabled** and recovery has not restored it (or Apple keeps signing Messages out);
- **two outages in one month** (each long enough to mark the relay `down`).

Hardware or software with no fix in sight (the Mac has failed with no replacement within a day, the iPhone's number will not register for iMessage again, or BlueBubbles drops support for the macOS the Mac can run) counts as the first rule: it will be down for more than 48 hours.

The port is one-way (the number becomes SMS-only for good), takes 3–15 business days, and needs 10DLC approved in advance (TA-O3, the port runbook's step 0). Setting `ADVISOR_CHANNEL=twilio` is that runbook's last step, never a first response: while the relay is down and the channel is still `bluebubbles`, replies stay held for 6 hours; once `ADVISOR_CHANNEL=twilio` is deployed, the next cron tick sends any remaining held rows through Twilio.
