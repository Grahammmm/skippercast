# Runbook: move the Text Advisor's number to Twilio

**When:** the Mac relay cannot be kept running ([relay down](advisor-relay-down.md#when-to-stop-fixing-the-relay) says when to escalate). Step 0 is done earlier, at TA-O3, so that a port is possible at short notice.
**This is one-way.** After the port the number is SMS/MMS only, for good: it can never be an iMessage handle again, and `ADVISOR_CHANNEL` never goes back to `bluebubbles` for this number.
**Owner:** repository owner. Every step needs the owner's carrier, Apple, Twilio or GitHub accounts. An agent can check results (`relay-check.mjs --twilio`, `GET /api/advisor/health`, the D1 queries below) and update the docs.
**Background:** [03 · Channels](../../plans/text-advisor/03-channels.md) § The one number and § Twilio adapter. The adapter is `server/advisor/channels/twilio.ts`; its inbound and status webhooks are always mounted, so nothing is lost while a port is in progress.

Do the steps in order and tick them as you go. Facts about porting, iMessage and 10DLC below were researched on 2026-10-03; Twilio's console labels change, so look for the named setting if a menu path has moved.

## 0. Readiness (TA-O3, done in advance)

Nothing here sends a text or changes the live site. Do it once, before the pilot.

- [ ] **Twilio account.** Create it with the owner's details, add billing, turn on two-factor authentication. Do not buy a Twilio number; the advisor's own number comes over in step 3.
- [ ] **A2P 10DLC brand.** Messaging → Regulatory compliance → A2P 10DLC (Trust Hub). Every application text from a 10-digit US number needs a registered brand and campaign; carriers block unregistered traffic. Choose, in order of preference:
  1. **Low Volume Standard (recommended if you have an EIN).** Needs the business's legal name, address and EIN exactly as the IRS has them. About 2,000 message segments a day to T-Mobile.
  2. **Sole Proprietor (if there is no EIN).** Your legal name and address; Twilio sends a one-time code to a real mobile number, use your own mobile, not the advisor's number. One campaign, one number, about 1,000 segments a day to T-Mobile. Enough for the pilot: one long reply is three segments.
- [ ] **Campaign.** Create it with the text in [§ 10DLC package](#10dlc-package) (paste it as written). Vetting takes up to 5 business days. Fees, roughly: $4.50 one-time for the brand, $15 one-time for campaign vetting, $1.50–2 a month for the campaign, plus Twilio's per-message and number fees (see the console's pricing pages). Twilio creates a **Messaging Service** for the campaign; the ported number joins it in step 5.
- [ ] **First reply.** The opt-in text below promises that the first reply to a new contact says who we are, "Msg & data rates may apply" and how to get HELP or STOP (sample message 1). Check the engine's welcome (TA-E1) says that before submitting; if it does not, change the welcome, not the campaign text.
- [ ] **Privacy page.** Vetting reviewers check that the site's privacy policy covers text messages. `dist/privacy.html` § Text Advisor (added with TA-S6: what is stored, that numbers are never sold or shared for marketing, how to stop and erase) is a draft until you and counsel approve it; do that before submitting the campaign, or vetting may be rejected.
- [ ] **Secrets.** Repository → Settings → Secrets and variables → Actions:
  ```bash
  gh secret set TWILIO_ACCOUNT_SID     # ACXXXXXXXX… from the console's Account Info
  gh secret set TWILIO_AUTH_TOKEN      # the primary auth token
  ```
  Leave **`TWILIO_FROM` unset**: the adapter refuses to send without it (`not-configured`), which keeps Twilio dark until step 5. Run **Actions → Deploy to Cloudflare → Run workflow** (action `deploy`) so the Worker can check Twilio signatures if a text ever arrives early.
- [ ] **Check the account** from your laptop, without sending anything:
  ```bash
  read -rs TWILIO_AUTH_TOKEN; export TWILIO_AUTH_TOKEN
  export TWILIO_ACCOUNT_SID=ACXXXXXXXX…
  node scripts/advisor/relay-check.mjs --twilio --no-send
  ```
  Done when it ends `PASS`.
- [ ] **Carrier details** in your password manager (from [relay setup step 1](advisor-relay-setup.md#1-buy-the-number)): the carrier account number, the port-out PIN, and the account holder's name and service address **exactly** as the carrier has them. Download one recent bill to check them against.

## 1. Decide

- [ ] One of the escalation conditions in [relay down § When to stop fixing the relay](advisor-relay-down.md#when-to-stop-fixing-the-relay) holds: the relay has been down more than 48 hours, the Apple Account is suspended or locked, or there were two outages in a month.
- [ ] Step 0 is complete and the campaign shows **Approved** (or will be by the expected port date). If it is not approved, Twilio cannot send from the number after the port; start or chase it now.
- [ ] Note the decision and the date in the incident notes.

## 2. Deregister iMessage while the SIM still works

If the number is still registered for iMessage when it leaves the iPhone, other iPhones keep sending to it as iMessage and those texts vanish with no error. Deregistering needs the SIM to receive one text, so it must happen **before** the port completes.

Timing: if the relay is already dead, do it now. If the relay is still carrying texts, you may wait until step 3 gives you a FOC date and do it about two business days before that date, because turning iMessage off also ends Text Message Forwarding: from then on texts reach only the iPhone, and the Worker sees nothing until step 5.

- [ ] On the advisor iPhone: **Settings → Apps → Messages → iMessage: off** and **Settings → Apps → FaceTime → FaceTime: off** (iOS 17 and earlier: Settings → Messages / Settings → FaceTime).
- [ ] Or, if the iPhone is unusable or the Apple Account is locked: Apple's deregister page, `selfsolve.apple.com/deregister-imessage`. Enter the number, receive the code by SMS on the SIM (put it in any phone), enter the code.
- [ ] Check: from another iPhone, start a new message to the number. It must turn **green**. (Apple's servers can take some hours to catch up; check again the next day.)

## 3. Request the port

- [ ] Twilio console → **Phone Numbers → Port a number** (porting). Enter the number; Twilio confirms it is portable.
- [ ] Give it:
  - the **Letter of Authorization (LOA)**, e-signed in the console;
  - a **recent bill**, issued within the last 30 days;
  - the carrier **account number** and **port-out PIN** (if the carrier issues a transfer PIN on request, request it just before submitting);
  - the account holder's **name and service address exactly as on the carrier's record**. A mismatch is the most common reason a port is rejected; copy them from the bill, character for character.
- [ ] Choose the **FOC date** (Firm Order Commitment: the day the number moves). Twilio's console shows the status and the confirmed date.
- [ ] Expect 3–15 business days. A rejection (wrong PIN, name or address) restarts the clock and can stretch it past 4 weeks; fix the field the rejection names and resubmit the same day.
- [ ] **Do not cancel the carrier line.** A port needs an active line; keep a prepaid line topped up. The carrier closes it when the port completes.

## 4. While waiting

Nothing in the repository or on Cloudflare changes. `ADVISOR_CHANNEL` stays `bluebubbles`.

- Every reply the engine makes is written `held` (relay down) and **ages out after 6 hours** (`failed`, `held-expired`); people who text in this window get no answer. That is expected; there is nothing to replay.
- Once iMessage is off (step 2), texts reach only the iPhone, never the Worker. If you want, read them in Messages on the iPhone and answer the important ones by hand from your own phone.
- Do not set `TWILIO_FROM` or change `ADVISOR_CHANNEL` early. The relay watchdog keeps running and keeps the relay marked `down`.

## 5. Port day

Twilio's console shows the port **Completed** and the number under Active Numbers. SMS on a ported number can take up to 3 business days more to start working; if the checks below fail on the first day, wait and retry rather than changing settings.

- [ ] **Number into the campaign.** Messaging → Services → the campaign's Messaging Service → **Sender Pool → Add senders** → the number. Without this, carriers treat the number's texts as unregistered.
- [ ] **Inbound webhook.** Phone Numbers → Active Numbers → the number → Messaging configuration → **A message comes in**: Webhook, **HTTP POST**,
  ```
  https://skippercast.com/api/advisor/inbound/twilio/<ADVISOR_WEBHOOK_TOKEN>
  ```
  with the same token as the BlueBubbles webhook. Use exactly `https://skippercast.com` (no `www`, no trailing slash): Twilio signs the URL it calls, and the Worker rebuilds it from `ADVISOR_PUBLIC_BASE`, so any other spelling fails the signature check with `401`. In the Messaging Service's **Integration** settings, choose **Defer to sender's webhook** (or put the same URL there): exactly one place should point Twilio at this URL.
- [ ] **No status callback in the console.** The Worker sets `StatusCallback` on every message it sends (`/api/advisor/inbound/twilio-status/<token>`); leave the console's status callback fields empty.
- [ ] **HELP auto-reply.** In the Messaging Service's **Opt-Out Management** (Advanced Opt-Out), set the HELP reply to the engine's help wording (keep the two identical; [§ HELP and STOP wording](#help-and-stop-wording)). Leave Twilio's STOP handling on: it is what carriers require, and the Worker relies on Twilio's error 21610 to stop a contact who opted out through Twilio.
- [ ] **Set the sender secret:** `gh secret set TWILIO_FROM` and paste the number in E.164 (`+1` and ten digits). It reaches the Worker with the deploy below.
- [ ] **Outbound check** from your laptop:
  ```bash
  read -rs TWILIO_AUTH_TOKEN; export TWILIO_AUTH_TOKEN
  export TWILIO_ACCOUNT_SID=ACXXXXXXXX… TWILIO_FROM=<the number>
  node scripts/advisor/relay-check.mjs --twilio --to <your own mobile number>
  ```
  Done when it ends `PASS` and the test SMS arrives on your phone from the advisor's number.
- [ ] **Switch outbound to Twilio and deploy:**
  ```bash
  gh variable set ADVISOR_CHANNEL --body twilio
  gh workflow run deploy-cloudflare.yml --ref main -f action=deploy
  ```
  Every advisor setting is a repository variable applied by a deploy; nothing is edited on the Cloudflare dashboard. Wait for the run to finish green (it smoke-tests and rolls back by itself on failure).
- [ ] **Verify:** `curl -s https://skippercast.com/api/advisor/health` shows `"channel":"twilio"`. Its `relay` field keeps the last BlueBubbles state (`down`): the watchdog stops checking once the channel is `twilio`, so ignore it.
- [ ] **Inbound check:** text the number from your phone. The reply arrives by SMS within a few seconds, and
  ```bash
  npx wrangler d1 execute skippercast --remote --command \
    "SELECT created_at, direction, channel, status, error FROM advisor_messages ORDER BY created_at DESC LIMIT 6"
  ```
  shows your `in` row on channel `sms` and an `out` row `sent`. An inbound text that got no reply before the switch was held; the next cron tick (15 minutes) sends it through Twilio if it is less than 6 hours old.
- [ ] **STOP and HELP forwarding (record the answer).** From your phone, text `HELP`, then `STOP`, then `START`. Twilio auto-replies to HELP and STOP itself. Rerun the query above with `substr(body,1,10) AS body` added to the columns (your own texts only) and note which of `HELP`, `STOP` and `START` appear as `in` rows: those are the keywords Twilio also forwards to the webhook. Write the result, with the date, in [03 § Twilio adapter](../../plans/text-advisor/03-channels.md) under "STOP/HELP forwarding", and fix [02 § STOP](../../plans/text-advisor/02-data-model.md) if it says otherwise. Finish with `START` so your own number is not left opted out (Twilio refuses sends to an opted-out number with error 21610).

If something goes wrong after the switch, do not set `ADVISOR_CHANNEL` back (the relay cannot send for a ported number). Set the repository variable `ADVISOR_REPLIES_ENABLED=false` and deploy: inbound texts are stored and held, nothing is sent, until you fix it and set it back to `true`.

## 6. Afterwards

- **What users see:** the same number, the same contact card and links; replies arrive as green SMS bubbles instead of blue ones, and long replies come in numbered parts (`(2/3)`). Tell users nothing. Someone whose iPhone still shows an old blue thread and gets "Not Delivered" can delete that thread and text again.
- **What is lost:** iMessage itself (blue bubbles, typing indicators, read receipts), full-size photos (carriers compress MMS; skippers get the upload link for originals and videos) and the contact card as an attachment (SMS links it instead).
- **What is kept:** every conversation, contact, report, consent and opt-out, and the number.
- [ ] **Retire the Mac relay.** BlueBubbles → API & Webhooks: delete the webhook. Zero Trust: delete the `relay.skippercast.com` Access application, the `skippercast-worker` service token and the `skippercast-relay` tunnel (and its DNS record). Remove the relay secrets from GitHub and from the Worker (a deploy only uploads secrets that are set; it never deletes one):
  ```bash
  for s in BLUEBUBBLES_URL BLUEBUBBLES_PASSWORD CF_ACCESS_CLIENT_ID CF_ACCESS_CLIENT_SECRET; do
    gh secret delete "$s"; npx --yes wrangler@4.142.0 secret delete "$s" --name skippercast
  done
  gh variable delete BLUEBUBBLES_PRIVATE_API 2>/dev/null || true
  ```
  Keep `ADVISOR_WEBHOOK_TOKEN`: the Twilio webhooks use it. Sign the Mac and the iPhone out of the dedicated Apple Account, erase them, and stop the smart-plug schedule. Keep the Apple Account itself for a few months in case anything was tied to it, then delete it at `account.apple.com`.
- [ ] **Carrier:** confirm the old line closed and stopped billing.
- [ ] **Status log:** add a dated line to [the plan's README](../../plans/text-advisor/README.md#status-log): "number ported to Twilio; `ADVISOR_CHANNEL=twilio`; STOP/HELP forwarding: …".

## 10DLC package

Paste-ready text for the brand and campaign forms (step 0). Keep the wording true: if SkipperCast starts sending anything not described here (alerts, briefs, any promotion), update the campaign first.

**Brand description**

> SkipperCast (skippercast.com) is a free fishing-conditions and catch-report website for California's Central Coast, starting with Morro Bay. People text SkipperCast to ask about conditions, fishing rules and recent catches, and charter skippers text their daily catch counts and photos.

**Campaign use case:** Low Volume Standard: **Mixed**, with the sub-use cases **Customer Care**, **Account Notification** and **Two-Factor Authentication**. Sole Proprietor: the form offers one use case; use the same description.

**Campaign description**

> SkipperCast answers fishing questions by text for anglers and charter skippers on California's Central Coast. A person texts our number first, or taps "Text SkipperCast" on skippercast.com, which opens their messaging app with a message to send. We reply to what they ask: sea and weather conditions for a trip, current fishing rules with a link to the official source, recent catch reports, and fish identification from a photo. Charter skippers text their daily catch counts and photos; we confirm the report back to them before it is published. A charter skipper who has agreed in person to send reports may receive one registration invite from us, and a skipper can add a crew member, who receives one text saying so; both texts say how to opt out. A website visitor who asks to continue a conversation by text receives a one-time code. We do not send marketing or promotions. Messages are replies to the person's own texts, a confirmation of their own report, a code they asked for, or the single invite described above.

**Sample messages** (variables in brackets)

1. > SkipperCast here. Ask me about conditions, rules or recent catches for [port], or send a fish photo for an ID. Msg & data rates may apply. Reply HELP for help, STOP to opt out.
2. > [Port] tomorrow: NW wind 10–15 kt, rising to 20 kt after 1 pm; seas 5 ft at 9 seconds. Morning looks best. Current rules: skippercast.com/ports/[port]
3. > Got it: [boat], [date], [anglers] anglers, [count] rockfish, [count] lingcod. Reply Y to publish or send a correction.
4. > Your SkipperCast code is [6 digits]. If you didn't ask for it, ignore this text.

**Opt-in (how people consent)**

> Opt-in is always started by the person. They text our number first, either typing it themselves or tapping a "Text SkipperCast" link or QR code on skippercast.com or our Instagram, which opens their messaging app with a pre-filled message they choose to send. A website visitor can also type their own number into skippercast.com to continue a chat by text; they receive one code and must type it back. Our first reply says who we are, that message and data rates may apply, and how to get help or stop. A charter skipper who agrees in person to send reports, or a crew member a skipper adds, receives one text naming SkipperCast (and the skipper and boat, for crew), with STOP instructions, and gets nothing more unless they reply.

**Opt-out and help keywords**

- Opt-out: `STOP`, `STOPALL`, `UNSUBSCRIBE`, `CANCEL`, `END`, `QUIT` (and Spanish `ALTO`, `PARAR`). Opt back in: `START`, `UNSTOP`.
- Help: `HELP` (and `AYUDA`).

**Message flow summary**

> 1. A person texts SkipperCast or taps a Text SkipperCast link that opens their messaging app with a pre-filled message. 2. SkipperCast replies with an introduction, "Msg & data rates may apply", and HELP/STOP instructions. 3. Each later message from us answers a message they sent, confirms a catch report they sent, or is a one-time code they requested. Message frequency varies with how often they text. 4. STOP ends all messages immediately; START resumes. HELP returns a description of the service and how to reach us.

### HELP and STOP wording

The engine's `help` command ([04 § Stage 1](../../plans/text-advisor/04-advisor-engine.md#stage-1-commands-and-language-no-model-call)) lists what you can ask, STOP, "forget me" and a link; 04 does not fix the exact words. Use this text both as Twilio's HELP auto-reply and as the engine's help reply (TA-E1), and change both together:

> SkipperCast: fishing conditions, rules, catch reports and fish IDs by text. Ask a question or send a photo. Text STOP to stop, FORGET ME to erase your data. Help and contact: skippercast.com

The engine's STOP reply ([04 § Stage 1](../../plans/text-advisor/04-advisor-engine.md#stage-1-commands-and-language-no-model-call)) is "Done. You won't hear from me unless you text START." Twilio sends its own STOP confirmation on SMS; if Twilio forwards STOP, the engine's own confirmation is refused with 21610, which only re-applies the stop (03 § Twilio adapter).
