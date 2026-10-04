# 03. Channels: the number, the relay, Twilio, web chat

## The one number

SkipperCast owns one US mobile number (`ADVISOR_NUMBER`, E.164). It is the
only number ever printed, linked or saved. Facts that shape everything below
(sources: Apple support 102545 and 108758, BlueBubbles docs, Twilio porting
guidelines; research dated 2026-10-03):

- An iMessage identity for a *phone number* is registered by an iPhone with
  that SIM, signed into an Apple Account. A Mac can send as that number only
  when it is signed into the **same** Apple Account and the number is ticked
  under Messages › Settings › iMessage › "You can be reached at".
- SMS/MMS reach the Mac only through **Text Message Forwarding** from that
  iPhone (same Apple Account, iPhone on and online). BlueBubbles sends SMS the
  same way, using chat GUIDs of the form `SMS;-;+1…`.
- Twilio can receive a ported mobile number (wireless carriers need the
  account number and port-out PIN; 3–15 business days; SMS activates up to 3
  business days after the port) and then that number is SMS/MMS only; it can
  never be an iMessage handle again. Deregister iMessage first
  (`selfsolve.apple.com/deregister-imessage`) or iPhones keep routing to
  iMessage and the texts vanish.

So the setup is: **one dedicated Apple Account** (`imessage@quietfinch.com`
style, 2FA on, recovery contact = the owner), **one spare iPhone** holding the
SIM, signed into that account, Text Message Forwarding enabled for the Mac,
plugged in, Wi-Fi, auto-lock off, next to **one Mac mini** signed into the
same account running BlueBubbles. Nothing else on that account.

### Owner setup checklist (task TA-O1; owner steps, engineering writes the runbook)

1. Buy the number: a prepaid or cheap postpaid line on a carrier that permits
   port-out (any major carrier does). Record account number and PIN in the
   owner's password manager, not in the repo.
2. Create the Apple Account; sign in on the iPhone; Settings › Messages › Send
   & Receive shows the number ticked. Enable Messages in iCloud.
3. Mac mini: a macOS version BlueBubbles' current release notes list as
   supported (the runbook says where to check); same Apple Account;
   Messages › iMessage shows the number;
   iPhone › Messages › Text Message Forwarding › the Mac: on.
4. Install the BlueBubbles server. Set a long server password. Enable the
   Private API only if typing indicators and read receipts are wanted (needs
   SIP off; the plan treats them as optional: `BLUEBUBBLES_PRIVATE_API=true`
   turns on typing/read calls, otherwise they are skipped).
5. Expose the server to the Worker with a **named Cloudflare Tunnel**
   (`cloudflared` on the Mac) at `relay.skippercast.com`, protected by
   **Cloudflare Access** with a service token (`CF_ACCESS_CLIENT_ID/SECRET`)
   so only the Worker can reach it. Not the quick tunnel (its URL changes).
6. In BlueBubbles › API & Webhooks, add the webhook
   `https://skippercast.com/api/advisor/inbound/bluebubbles/<ADVISOR_WEBHOOK_TOKEN>`
   with events `new-message`, `updated-message`, `message-send-error`,
   `new-server`.
7. Energy: never sleep, auto-login the macOS user, BlueBubbles in Login Items,
   a `launchd` job restarting `cloudflared`. A smart plug on a daily reboot
   schedule is optional but recommended.
8. Run `node scripts/advisor/relay-check.mjs` from the owner's laptop (it
   hits `/api/v1/ping` through the tunnel with the service token and sends one
   test iMessage and one test SMS to the owner's phone). Paste the output in
   the task's PR.

## The adapter interface (`server/advisor/channels/index.ts`)

```ts
export interface InboundMessage {
  channel: 'imessage' | 'sms' | 'web' | 'instagram_dm' | 'instagram_comment';
  providerId: string;              // unique per channel
  from: string;                    // E.164, or web session id, or IGSID
  to: string;                      // our number / page id
  text: string;                    // '' when media-only
  media: InboundMedia[];           // see below
  receivedAt: string;              // ISO
  isGroup: boolean;                // group chats are ignored with one polite reply
  raw?: unknown;                   // never persisted
}
export interface InboundMedia {
  providerRef: string;             // attachment guid / media URL / IG attachment id
  mime: string | null;             // provider's claim; sniffed again after download
  bytes: number | null;
  name: string | null;
  fetch: (env: Env) => Promise<Response>;   // authenticated download
}
export interface OutboundMessage {
  id: string;                      // advisor_messages.id, deterministic
  to: string;                      // E.164 / session / IGSID
  text?: string;
  mediaKeys?: string[];            // R2 keys to attach (derived public JPEGs)
  replyToProviderId?: string;      // threads the reply where the channel supports it
  channelHint?: 'imessage' | 'sms'; // the contact's last channel; picks the BlueBubbles chat GUID
}
export interface SendResult { providerId: string | null; status: 'sent' | 'failed' | 'unknown'; error?: string }
export interface ChannelAdapter {
  name: 'bluebubbles' | 'twilio' | 'web';
  normalize(request: Request, env: Env): Promise<InboundMessage[] | 'ignore' | 'unauthorized'>;
  send(message: OutboundMessage, env: Env): Promise<SendResult>;
  typing?(to: string, on: boolean, env: Env): Promise<void>;
  markRead?(to: string, env: Env): Promise<void>;   // BlueBubbles marks a chat read, so: the stored address
  health(env: Env): Promise<{ok: boolean; detail: string}>;
  capabilities: {media: boolean; maxMediaBytes: number; typing: boolean; read: boolean; segments: number | null};
}
```

`channelFor(env, contact)` returns the adapter for outbound: `web` when the
contact is web-only, otherwise the one named by `ADVISOR_CHANNEL`. Inbound
webhooks for `bluebubbles` and `twilio` are both always mounted.

Message splitting: `splitForChannel(text, adapter, channel?)` breaks a reply at
paragraph or sentence boundaries into chunks ≤ 1,000 characters for iMessage
and ≤ 480 for SMS (3 segments), sent in order with a 300 ms gap; chunks after
the first are prefixed `(2/3)` only on SMS. BlueBubbles carries both iMessage
and SMS, so the contact's channel is the third argument (Twilio is always SMS;
web is never split). The consumer writes one outbound row per chunk: chunk 0
keeps the action's id, chunk n is `outboundId(message, '<index>.<n>')`.

`twilio` and `web` are registered as stubs that throw `ChannelNotImplemented`
until TA-C2 and TA-C3 replace them in `ADAPTERS`; a send through a stub is
recorded `failed`, not `unknown`.

## BlueBubbles adapter (`channels/bluebubbles.ts`)

Every BlueBubbles endpoint below is under `/api/v1/` (`/api/v1/message/text`,
`/api/v1/attachment/<guid>/download`, `/api/v1/ping`, …); the prefix is
omitted in the text for brevity.

- Base URL `BLUEBUBBLES_URL`, every call appends `?password=<BLUEBUBBLES_PASSWORD>`
  and sends `CF-Access-Client-Id` / `CF-Access-Client-Secret` headers. 15 s
  timeout; one retry on network error, none on 4xx.
- **normalize**: body `{type, data}`. Handle `new-message` (and
  `updated-message` only to mark delivery status on an outbound row by
  `provider_id`; it never creates an inbound). Skip `isFromMe`, reactions
  (`associatedMessageType` set), tapbacks, group chats (`chats[0].style`
  group or GUID containing `;+;`), and `itemType != 0`. `from` is
  `handle.address` normalized to E.164 (`handle.service` tells
  `imessage` vs `sms`). Attachments map to `InboundMedia` with
  `fetch = GET /api/v1/attachment/<guid>/download`. `providerId` is
  `data.guid`. `message-send-error` marks the outbound row `failed`.
  `new-server` is logged; with a named tunnel it should not fire.
  As built (TA-C1): `updated-message` and `message-send-error` find our row by
  `provider_id = data.guid` or by `data.tempGuid`, which `send` sets to our
  outbound id (the send-error webhook may carry a guid the send response never
  returned). 02 has no delivered/read columns, so `updated-message` only
  promotes an `unknown`/`sending` row to `sent` on delivery or read, and marks
  it `failed` when `data.error` is non-zero. Groups are also detected by
  `chats[0].style == 43` or more than one chat; a sender that is not a NANP
  number (including an email handle) is dropped with a counted log line.
  U+FFFC (the attachment placeholder iMessage puts in `text`) is stripped.
- **send**: choose the chat GUID: if the contact's last inbound was `imessage`
  use `iMessage;-;<e164>`; if `sms`, `SMS;-;<e164>`; for a first contact we
  initiate (invites), call `GET /handle/availability/imessage?address=` and
  pick accordingly. Text: `POST /message/text` `{chatGuid, tempGuid, message,
  method: 'apple-script'}` (`private-api` when enabled). Media: `POST
  /message/attachment` multipart (`attachment`, `chatGuid`, `name`,
  `tempGuid`) after fetching the derived JPEG from R2; a text and a photo are
  two sends, text first. A 200 whose body carries `error` is a failure (seen
  on SMS sends). Result `providerId = data.guid`.
- **health**: `GET /api/v1/ping` and `GET /api/v1/server/info` (records the
  server version and whether the Private API is loaded) under 10 s.
- Fixtures: `tests/fixtures/advisor/bluebubbles/*.json` with real payload
  shapes (phone numbers replaced by the fictional `+15555550100` series),
  covering a text,
  a photo, a video, an SMS-forwarded MMS, a reaction, a group message, an
  outbound echo and a send error.

## Twilio adapter (`channels/twilio.ts`)

- **normalize**: form-encoded body; verify `X-Twilio-Signature` =
  base64(HMAC-SHA1(`TWILIO_AUTH_TOKEN`, publicUrl + sorted `key+value`
  pairs)), where `publicUrl` is rebuilt from `ADVISOR_PUBLIC_BASE` + path +
  query, never from the `Host` header. `From`, `To`, `Body`, `NumMedia`,
  `MediaUrl0..N`, `MediaContentType0..N`; `providerId = MessageSid`; media
  `fetch` uses Basic auth `AccountSid:AuthToken`. Twilio's default opt-out
  handling auto-replies to STOP and HELP itself; whether each keyword is also
  forwarded to the webhook is confirmed in TA-C2 against Twilio's current
  docs, and the engine's STOP/HELP paths run on whatever is forwarded. The
  Twilio console's HELP auto-reply text is set to the same wording as the
  engine's `help` reply (documented in the runbook). Answer `<Response/>`
  with `text/xml`.
- **send**: `POST https://api.twilio.com/2010-04-01/Accounts/<sid>/Messages.json`
  with `To`, `From=TWILIO_FROM`, `Body`, `MediaUrl` (public derived JPEG URL
  on skippercast.com), `StatusCallback` = `/api/advisor/inbound/twilio-status/<token>`
  (updates `sent`/`failed`). Error 21610 (opted out) sets the contact
  `stopped`. Media ≤ 600 KB for non-JPEG; JPEG under 5 MB total.
- Compliance (owner tasks in TA-O3): A2P 10DLC registration (Low Volume
  Standard with an EIN, or Sole Proprietor without; ~$4.50 brand, $15
  campaign vetting, $1.50–2/month, up to 5 business days) before any SMS is
  sent from Twilio. The campaign description and sample messages live in
  `docs/operations/runbooks/advisor-port-to-twilio.md` so they are ready to
  paste.

## Web adapter (`channels/web.ts`)

`send` pushes the outbound into an in-memory array the HTTP handler returns;
`normalize` reads the JSON body `{text, media_ids}`. The `sc_adv` cookie is
set on the first request (`HttpOnly; Secure; SameSite=Lax; Max-Age=7776000`).
A web visitor who types a phone number when the engine offers "want me to
text you this?" is **linked**: the engine sends a 6-digit code to the number
through the text channel, the visitor types it back, and the web contact's
history is merged into the phone contact (WH-2). Linking is rate-limited to 3
attempts per session per day.

## Uploads for compressed channels (SMS skippers, big videos)

`GET /u/<token>` is a page with one file input; the token is minted by the
engine (`advisor_upload_tokens` is not a table: the token is
`base64url(contact_id ‖ expiry ‖ HMAC)` verified statelessly, 24 h). The page
posts to `POST /api/advisor/upload/<token>` (multipart, ≤ 300 MB, streamed
to R2), which creates the `advisor_media` row and enqueues a synthetic
inbound message `{text: '', media: [...]}` so the normal intake runs and the
skipper gets the confirmation by text.

As built (TA-C4): the token's three fields are joined with `|`, the expiry is
epoch seconds and the HMAC is hex, keyed with a third HKDF subkey of
`ADVISOR_PHONE_KEY` (info `upload`, `PhoneKeys.uploadKey`). A bad, tampered or
expired token, an unknown contact or a blocked one answers the gate's 404 on
both routes. The synthetic message has `body=''`, `media_json=[media_id]`, the
contact's channel and `provider_id='upload:<media_id>'`, and goes through
`server/advisor/inbound.ts` `dispatchInbound()`, the same store-and-dispatch
the webhooks use. The page sends with `XMLHttpRequest`, not `fetch`: only XHR
reports upload progress in every browser, and `connect-src 'self'` covers it.
The multipart body is read as a stream (`server/advisor/multipart.ts`), never
with `request.formData()`, which would buffer 300 MB. Each adapter gains
`fetchMediaByRef(ref, env)` (optional on the interface so the Twilio adapter
can add its own; BlueBubbles: `GET /api/v1/attachment/<guid>/download`); the
consumer picks the adapter from the message channel and the ref (an https ref
is a Twilio media URL).

## Contact card and deep links (FC-3, FC-5)

- `GET /contact.vcf` returns a vCard 3.0: `FN:SkipperCast`, `TEL;TYPE=CELL:<ADVISOR_NUMBER>`,
  `URL:https://skippercast.com`, `PHOTO;ENCODING=b;TYPE=JPEG:` (the app icon).
  The first reply to a new contact attaches it on iMessage (as a file) and
  links it on SMS.
- `GET /text?s=<source>&m=<message>` redirects to
  `sms:<ADVISOR_NUMBER>?&body=<message>` (the `?&body=` form is the one both
  iOS and Android open with the body pre-filled; TA-C6 verifies on both and
  branches on user agent only if a device rejects it). `s` is recorded by the engine from
  the pre-filled body, which starts with an invisible marker:
  the body is `"<message> [via <source>]"` and the engine strips and stores
  the source. Instagram bio and post CTAs use `https://skippercast.com/text?s=ig`.

## Runbook: relay down and port to Twilio (OP-7)

`docs/operations/runbooks/advisor-port-to-twilio.md` (task TA-C7) contains,
in full: the diagnosis steps (ping, tunnel status, Messages.app signed in,
iPhone online, Apple Account alerts), the restart procedure, and the one-way
switch:

1. Set `ADVISOR_CHANNEL=twilio` only *after* steps 2–5.
2. Before the port completes, deregister iMessage for the number (on the
   iPhone: Messages › iMessage off, FaceTime off; or Apple's deregister page,
   which needs an SMS code so do it while the SIM still works).
3. Port request in Twilio with LOA, bill, account number, PIN; choose a FOC
   date; expect 3–15 business days; SMS live up to 3 days later.
4. 10DLC must already be approved (done at TA-O3 as a standing readiness step
   even though Twilio sends nothing until the switch).
5. Set `TWILIO_FROM=<ADVISOR_NUMBER>`, run `relay-check.mjs --twilio`, then
   flip `ADVISOR_CHANNEL`. Held outbound messages (`status='held'`) are
   released by the next cron run.
6. Tell users nothing. The contact card and every link already carry the
   number. Update `docs/plans/text-advisor/README.md` status log.

What is lost: blue bubbles and full-size inbound photos (Twilio compresses
MMS; the upload link covers skippers). What is kept: every conversation,
contact, report, consent and the number.
