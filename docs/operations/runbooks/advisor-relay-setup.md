# Runbook: set up the Text Advisor's Mac relay

**When:** once, before the Text Advisor's pilot (task TA-O1 in [the build plan](../../plans/text-advisor/10-work-breakdown.md)), and again if the Mac mini or the iPhone is replaced.
**Owner:** repository owner. Every step needs the owner's accounts, devices or money; an agent can only check the result (`relay-check.mjs`, `GET /api/advisor/health`).
**Background:** [03 · Channels](../../plans/text-advisor/03-channels.md) explains why the setup is one number, one dedicated Apple Account, one spare iPhone and one Mac mini. If the relay later stops working, use [relay down](advisor-relay-down.md).

What you end up with:

```
iPhone (SIM with the number) --Text Message Forwarding--> Mac mini: Messages + BlueBubbles :1234
                                                             | cloudflared (named tunnel, launchd)
skippercast.com Worker --CF Access service token--> https://relay.skippercast.com
Mac mini BlueBubbles --webhook--> https://skippercast.com/api/advisor/inbound/bluebubbles/<token>
```

Keep a note as you go (in your password manager, never in the repository) of: the carrier account number and port-out PIN, the Apple Account and its password, the BlueBubbles server password, the Access service token's id and secret, and the webhook token.

## 1. Buy the number

1. Buy a prepaid or cheap postpaid line on a major US carrier (all of them allow port-out). Choose a local area code if you can.
2. Put the SIM (or eSIM) in the spare iPhone.
3. In the carrier's account pages, find and record the **account number** and set a **port-out (transfer) PIN**. You need both only if the number ever moves to Twilio (the port-to-Twilio runbook, `advisor-port-to-twilio.md`, written in TA-C7), but they are hardest to find when you need them.
4. Turn off carrier voicemail-to-text and any carrier "message+" app on that line; plain SMS is what forwards to the Mac.

## 2. Create the dedicated Apple Account

1. On a computer, go to `account.apple.com` → **Create Your Apple Account**. Use an address that is only for this (for example `imessage@quietfinch.com`), not your personal Apple Account.
2. Turn on **two-factor authentication** with your own phone as a trusted number (not the advisor's number, so a lost SIM never locks you out).
3. Add yourself as **Account Recovery** contact (Sign-In and Security → Account Recovery).
4. Use this account for nothing else: no purchases, no family sharing, no other devices.

## 3. Set up the spare iPhone

1. Erase it or start fresh, and sign in with the dedicated Apple Account (Settings → Sign in).
2. **Settings → Apps → Messages** (on iOS 17 and earlier: **Settings → Messages**): turn **iMessage** on. Wait until **Send & Receive** shows the phone number ticked (activation can take a few minutes; up to 24 hours on a new line).
3. In **Send & Receive**, under **Start New Conversations From**, choose the phone number, not the email address.
4. **Settings → [account name] → iCloud → Messages in iCloud** (on some versions under **Show All**): turn on.
5. Leave it plugged in, on Wi-Fi, near the Mac. **Settings → Display & Brightness → Auto-Lock → Never.** Turn off automatic iOS updates that restart the phone overnight if you prefer to update by hand (**Settings → General → Software Update → Automatic Updates**).

Text Message Forwarding is switched on in step 5, once the Mac is signed in.

## 4. Set up the Mac mini

1. Install a macOS version that the current BlueBubbles server release supports. Check before you install: the BlueBubbles documentation at `docs.bluebubbles.app` (server installation and the macOS compatibility notes) and the release notes on the server's GitHub releases page (`github.com/BlueBubblesApp/bluebubbles-server/releases`). Do not upgrade macOS later until BlueBubbles' release notes say the new version works.
2. Create one macOS user for the relay. Sign in to **iCloud** with the dedicated Apple Account (System Settings → Sign in).
3. Open **Messages → Settings → iMessage**:
   - sign in with the same Apple Account if it is not already;
   - tick **Enable Messages in iCloud**;
   - under **You can be reached for messages at**, tick the **phone number**;
   - under **Start new conversations from**, choose the phone number.
   If the number does not appear, wait for the iPhone's activation to finish (step 3.2) and sign out and in again on the Mac.

## 5. Turn on Text Message Forwarding

1. On the iPhone: **Settings → Apps → Messages → Text Message Forwarding** (iOS 17 and earlier: **Settings → Messages → Text Message Forwarding**).
2. Turn on the Mac mini. If a code appears on the Mac, type it on the iPhone.
3. Check it: from your own phone, send an SMS to the number from a non-iPhone if you have one (or with iMessage turned off on your phone for a minute). It must appear in Messages on the Mac. Reply from the Mac; it must arrive green.

## 6. Install BlueBubbles

1. Download the latest BlueBubbles server for macOS from `bluebubbles.app` (or the GitHub releases page above) and move it to Applications.
2. Open it and grant what it asks for: **Full Disk Access** (System Settings → Privacy & Security → Full Disk Access) so it can read the Messages database, **Accessibility** and the **Automation → Messages** prompt so it can send through AppleScript. Restart BlueBubbles after granting them.
3. In BlueBubbles' setup, set a **server password**: long and random (for example `openssl rand -base64 32`). This is `BLUEBUBBLES_PASSWORD`.
4. **Proxy service:** choose the option for your own URL (named "Dynamic DNS" / custom URL in current versions) and enter `https://relay.skippercast.com`. Do not use the built-in Cloudflare quick tunnel or Ngrok: their URL changes on every restart. Leave Firebase/Google notification setup off unless BlueBubbles requires it to finish setup; the Worker does not use it.
5. Note the local port (default `1234`).
6. Optional, **Private API** (typing indicators and read receipts only): it needs System Integrity Protection partly disabled on the Mac, which lowers the Mac's security, and macOS updates can break it. Follow BlueBubbles' Private API guide (`docs.bluebubbles.app`, Private API section) exactly if you want it. If you turn it on, set the repository variable `BLUEBUBBLES_PRIVATE_API=true`; otherwise leave it unset and the Worker skips typing and read calls.

## 7. Expose BlueBubbles through a named Cloudflare Tunnel with Access

All in the Cloudflare account that owns `skippercast.com`.

1. On the Mac: install `cloudflared` (`brew install cloudflared`, or the package from Cloudflare's downloads page).
2. Create a named tunnel:
   ```bash
   cloudflared tunnel login                                  # opens a browser; pick skippercast.com
   cloudflared tunnel create skippercast-relay               # writes ~/.cloudflared/<tunnel-id>.json
   cloudflared tunnel route dns skippercast-relay relay.skippercast.com
   ```
3. Write `~/.cloudflared/config.yml`:
   ```yaml
   tunnel: skippercast-relay
   credentials-file: /Users/<relay user>/.cloudflared/<tunnel-id>.json
   ingress:
     - hostname: relay.skippercast.com
       service: http://localhost:1234
     - service: http_status:404
   ```
4. Run it once in the foreground to check: `cloudflared tunnel run skippercast-relay`, then stop it with Ctrl-C.
5. Install it as a launchd service so it starts at boot and restarts when it dies: `sudo cloudflared service install` (it copies the config to `/etc/cloudflared/` and loads `com.cloudflare.cloudflared`). Check with `sudo launchctl list | grep cloudflared`.
6. **Service token:** Cloudflare dashboard → **Zero Trust → Access → Service credentials → Service Tokens → Create Service Token** (older dashboards: **Access → Service Auth**). Name it `skippercast-worker`, duration **Non-expiring** (or a year, with a calendar reminder). Copy the **Client ID** (`CF_ACCESS_CLIENT_ID`) and **Client Secret** (`CF_ACCESS_CLIENT_SECRET`); the secret is shown once.
7. **Access application:** **Zero Trust → Access → Applications → Add an application → Self-hosted**. Domain `relay.skippercast.com`. Add one policy with action **Service Auth** that includes the service token `skippercast-worker`. No other policy: nobody, not even you in a browser, reaches the relay without the token.
8. Check from your laptop: `curl -s -o /dev/null -w '%{http_code}\n' https://relay.skippercast.com/api/v1/ping` answers `302` or `403` (Access blocks it). With the token headers (step 11 does this for you) it answers `200`.

## 8. Register the webhook

1. Make the webhook token: `openssl rand -base64 32 | tr '+/' '-_' | tr -d '='` (URL-safe, 43 characters). This is `ADVISOR_WEBHOOK_TOKEN`.
2. BlueBubbles → **API & Webhooks → Add Webhook**. URL:
   `https://skippercast.com/api/advisor/inbound/bluebubbles/<ADVISOR_WEBHOOK_TOKEN>`
   Events: **New Messages**, **Message Updates**, **Message Send Errors**, **Server URL Changes** (`new-message`, `updated-message`, `message-send-error`, `new-server`). Nothing else.
3. The webhook answers `404` until the advisor is switched on and `401` until the secret is deployed; both are expected now.

## 9. Keep the Mac running

1. **System Settings → Users & Groups → Automatically log in as →** the relay user (needs FileVault off on this Mac; the Mac holds no data beyond Messages).
2. **System Settings → Energy** (or **Energy Saver**): turn on **Prevent automatic sleeping when the display is off**, **Wake for network access** and **Start up automatically after a power failure**.
3. **System Settings → General → Login Items & Extensions → Open at Login:** add **BlueBubbles** (and **Messages**).
4. BlueBubbles' own settings: turn on **Startup with macOS** and **Auto-restart / keep alive** options where your version offers them.
5. `cloudflared` is already a launchd service (step 7.5).
6. Optional but recommended: a smart plug on a daily schedule (off at 04:00, on at 04:01) with "start up after power failure" on, so a stuck Mac recovers by itself.
7. Turn off automatic macOS updates (**System Settings → General → Software Update → Automatic Updates**) so an update never lands before BlueBubbles supports it.

## 10. Add the secrets to GitHub

Repository → **Settings → Secrets and variables → Actions**. `gh secret set NAME` reads the value from standard input, so it stays out of your shell history.

| Kind | Name | Value |
| --- | --- | --- |
| Secret | `BLUEBUBBLES_URL` | `https://relay.skippercast.com` |
| Secret | `BLUEBUBBLES_PASSWORD` | the BlueBubbles server password (step 6.3) |
| Secret | `CF_ACCESS_CLIENT_ID` | the service token's Client ID (step 7.6) |
| Secret | `CF_ACCESS_CLIENT_SECRET` | the service token's Client Secret (step 7.6) |
| Secret | `ADVISOR_WEBHOOK_TOKEN` | the webhook token (step 8.1) |
| Secret | `ADVISOR_PHONE_KEY` | if not set already: `openssl rand -base64 32` (encrypts stored numbers; never change it once contacts exist) |
| Variable | `ADVISOR_NUMBER` | the number in E.164, `+1` and ten digits |
| Variable | `BLUEBUBBLES_PRIVATE_API` | `true` only if you enabled the Private API (step 6.6) |

The deploy workflow passes `ADVISOR_WEBHOOK_TOKEN` and `ADVISOR_PHONE_KEY` to `scripts/cloudflare_deploy.sh` as `SECRET_ADVISOR_*` (an `ADVISOR_*` name would be copied into the Worker's plain vars), and the script uploads them under their real names. Run **Actions → Deploy to Cloudflare → Run workflow** to upload them. The advisor stays dark until `ENABLE_ADVISOR` and `TEXT_ADVISOR_ENABLED` are `true`.

## 11. Run the relay check

From your laptop, in a checkout of the repository (Node 22):

```bash
read -rs BLUEBUBBLES_PASSWORD; export BLUEBUBBLES_PASSWORD
read -rs CF_ACCESS_CLIENT_SECRET; export CF_ACCESS_CLIENT_SECRET
export BLUEBUBBLES_URL=https://relay.skippercast.com CF_ACCESS_CLIENT_ID=<client id>
node scripts/advisor/relay-check.mjs --to <your own mobile number>
```

It pings the relay through the tunnel with the service token, prints the BlueBubbles and macOS versions and whether the Private API is loaded, checks whether your number is on iMessage, and sends one iMessage and one SMS test text to your phone. It prints no secret. Done when it ends `PASS` and both texts arrived (one blue, one green). Paste its output in the TA-O1 note or PR.

Then, once the advisor is deployed with `TEXT_ADVISOR_ENABLED=true`: text the number from your phone; the stub reply ("SkipperCast is warming up…") arrives within a few seconds, and `GET https://skippercast.com/api/advisor/health` shows `"relay":{"state":"up",…}` after the next cron tick.
