# Runbook: Meta App Review for the Instagram inbox

**When:** after TA-S6 is merged and deployed, to turn on Instagram DMs and comment keywords (SP-8, SP-9). This is owner task TA-O5.
**Owner:** repository owner. Every step needs the owner's Meta Business, Meta developer, Instagram or GitHub accounts. An agent can check results (`GET /api/admin/health`, the D1 queries below) and update the docs.
**Background:** [09 · Social](../../plans/text-advisor/09-social.md) § Inbox and § As built (TA-S6); the code is `server/advisor/social/inbox.ts` (the webhook) and `server/advisor/channels/instagram.ts` (replies). Until this runbook is finished, nothing the public sends on Instagram reaches the advisor: Meta delivers DMs and comments only for accounts that hold a role on the app, and `ADVISOR_INBOX_ENABLED` keeps the code from acting on anything.

Do the steps in order and tick them as you go. Meta's dashboard labels move often (this was written on 2026-10-04 without access to the dashboard); if a menu path below has changed, look for the named setting. What the code needs does not change: the callback URL, the verify token, the `messages` and `comments` fields, and Advanced Access for the two inbox permissions.

## 0. Before you start

- [ ] TA-O4 is done: `META_APP_ID`, `META_APP_SECRET`, `META_VERIFY_TOKEN`, `META_PAGE_ID`, `META_PAGE_TOKEN` and `META_IG_USER_ID` are repository secrets, and the admin Health view shows the publishing quota. `META_VERIFY_TOKEN` is any long random string you choose (for example `openssl rand -hex 24`); Meta sends it back during the handshake.
- [ ] The advisor is deployed with `TEXT_ADVISOR_ENABLED=true`. Every advisor path, the webhook included, answers `404` while it is off, and Meta cannot verify a `404`.
- [ ] Health → **Instagram inbox** shows "Webhook verify token and app secret: Set".
- [ ] `ADVISOR_INBOX_ENABLED` is unset or `false` for now.
- [ ] The privacy notice ([`dist/privacy.html` § Text Advisor](../../../dist/privacy.html)) has been reviewed and approved by you and counsel. It is a draft until then, and App Review checks it.

## 1. Business Verification

Meta requires a verified business for Advanced Access to messaging permissions. It can take several days, so start it first.

- [ ] Meta Business Suite → **Settings** (Business settings) → **Security Center** → **Start verification**. Use the business that owns the Page and the app.
- [ ] Enter the legal name, address, phone number and website (`https://skippercast.com`) **exactly** as they appear on your documents.
- [ ] Upload documents. Meta accepts one document that shows the legal business name, and one that shows the name with the address or phone number. Typical choices:
  - Legal name: articles of incorporation or organization, a business license, or the IRS EIN letter (CP 575 or 147C).
  - Name with address or phone: a utility bill, a bank statement or a phone bill in the business's name.
  - A sole proprietor without a registered business uses the business license or the DBA filing, if any; check Meta's current list on the verification screen.
- [ ] Confirm by the method offered (email to an address on the business domain, phone, or a domain check).
- [ ] **Domain verification** (Business settings → Brand safety → Domains): add `skippercast.com` and verify it with the DNS TXT record Meta shows (Cloudflare DNS → Add record → TXT at the root). Keep the record.
- [ ] Done when Security Center shows the business as **Verified**.

## 2. App settings

App Dashboard → the "SkipperCast Publisher" app → **App settings → Basic**:

- [ ] **Privacy Policy URL:** `https://skippercast.com/privacy.html`
- [ ] **Terms of Service URL:** `https://skippercast.com/terms.html`
- [ ] **User data deletion:** choose "Data deletion instructions URL" and enter `https://skippercast.com/privacy.html#text-advisor`. The section says how to erase everything: send "forget me", then "DELETE", by DM or text.
- [ ] **App icon** (1024 × 1024), **category** (Business and Pages, or the nearest), a contact email you read.
- [ ] Save. Live mode later refuses an app without these.

## 3. The webhook

App Dashboard → **Webhooks** (or Products → Webhooks; on newer dashboards, Use cases → the Instagram use case → Customize → Webhooks):

- [ ] Choose the **Instagram** object.
- [ ] **Callback URL:** `https://skippercast.com/api/advisor/inbound/meta`
- [ ] **Verify token:** the value of `META_VERIFY_TOKEN`.
- [ ] **Verify and save.** Meta calls `GET /api/advisor/inbound/meta?hub.mode=subscribe&hub.verify_token=…&hub.challenge=…`; the Worker echoes the challenge. A failure here is almost always `TEXT_ADVISOR_ENABLED` off, the token not deployed (run the deploy workflow after setting the secret), or a typo.
- [ ] Subscribe the fields **messages** and **comments** (the "Subscribe" toggles next to each field). Leave the others off.
- [ ] Admin → **Health** → **Instagram inbox** → **Subscribe webhooks**. It calls `POST /<ig-user-id>/subscribed_apps?subscribed_fields=messages,comments` with the Page token and shows "Subscribed: messages,comments." If it shows an error with code 200 or 10, the token lacks a permission: rerun `node scripts/advisor/meta-token.mjs` (TA-O4) and update `META_PAGE_TOKEN`. If Meta's dashboard instead asks you to subscribe the linked **Page** to the app for `messages`, do that there as well (Messenger API settings for Instagram → the Page → Add subscriptions → `messages`).

## 4. The Instagram app toggle

On a phone signed into the `@skippercast` Instagram account:

- [ ] Settings and activity → **Messages and story replies** → **Message controls** (on some versions: Settings → Privacy → Messages) → **Connected tools** → turn on **Allow access to messages**. Without it Meta delivers no DM to any app.
- [ ] While there, check that **message requests** from people you don't follow are allowed: most people who DM a business account for the first time arrive as a request.

## 5. Test accounts

In Development mode only accounts with a role on the app produce webhook events. Use them for the screencast.

- [ ] Create (or pick) a personal Instagram account that is **not** `@skippercast`, for example a test account of yours. Don't use a real customer's account.
- [ ] App Dashboard → **App roles → Roles** → add that person as a **Tester** (for Instagram: **Instagram Testers** → Add, then accept the invite in that account: Instagram → Settings → Website permissions → Apps and websites → Tester invites).
- [ ] Set `ADVISOR_INBOX_ENABLED=true` for the recording and deploy:
  ```bash
  gh variable set ADVISOR_INBOX_ENABLED --body true
  ```
  then **Actions → Deploy to Cloudflare → Run workflow** (action `deploy`). In Development mode only role holders' messages and comments arrive, so the public is not answered yet. If review takes a long time you may set it back to `false` after recording; turn it on for good in step 9.
- [ ] From the test account: DM `@skippercast` "any lingcod around the rock?" and check a reply arrives within a minute. Comment `RIG` under a recent `@skippercast` post and check a private reply arrives in the test account's DMs (as a message request the first time). Check the D1 rows:
  ```bash
  npx wrangler d1 execute skippercast --remote --command "SELECT channel, status, intent, error, created_at FROM advisor_messages WHERE channel IN ('instagram_dm','instagram_comment') ORDER BY created_at DESC LIMIT 10"
  ```
  Inbound rows end `done`; outbound rows `sent`. `outside-window` on an outbound row means the person's last DM was more than 24 hours earlier.

## 6. Permissions and the usage text to paste

App Dashboard → **App Review → Permissions and features**. Request **Advanced Access** for the two inbox permissions; the form also asks about the permissions they depend on. Paste the text under each (edit "we" to your business name if Meta asks for the legal name). Publishing and insights stay on Standard Access: they act only on our own accounts, which hold roles on the app.

**`instagram_manage_messages`**

> SkipperCast is a fishing-information service for the California Central Coast. People send our Instagram account (@skippercast) direct messages asking what fish boats are catching, the day's conditions, size and bag limits, or to identify a fish from a photo. Our server receives each message through the messaging webhook and replies once, within Instagram's 24-hour messaging window, with an answer from our own reports and public data (NOAA forecasts, California Department of Fish and Wildlife regulations). We never message someone who has not messaged us first, we send no promotions, and a person can type STOP to stop replies or "forget me" to erase everything we stored. Messages are stored only to answer the conversation and are deleted on request.

**`instagram_manage_comments`**

> When someone comments one of our keywords (RIG, REPORT, ID or BOATS, or the Spanish equivalents) on a SkipperCast post, our server sends exactly one private reply to that comment with a link to the matching guide on skippercast.com (how the boats rig, the latest reports, the fish-ID page, or the list of boats). We read only comments on our own posts, store only comments that contain a keyword, and do not reply publicly, hide or delete comments. If we later enable public answers to fishing questions under our own posts, the same permission covers one reply per question.

**`instagram_basic`**

> Required to read our own Instagram professional account's id and username, which our server uses to recognise our own account in webhook events (so we never answer our own replies) and to address the messaging API.

**`pages_show_list`**

> Our Instagram professional account is linked to our Facebook Page. Our server uses the Page's access token, and this permission to find the Page and its linked Instagram account when the owner connects the app.

**`pages_read_engagement`**

> Needed together with instagram_manage_comments to read the comments on our own posts that the webhook announces.

**`pages_manage_metadata`**

> Used once, from our admin page, to subscribe our own account to the app's webhook for the messages and comments fields.

**`business_management`** (only if the form lists it)

> Our Page and Instagram account belong to our Business portfolio; the permission lets the app use that portfolio's Page token.

## 7. The screencast

Meta wants one recording per permission, or one recording that shows each permission used end to end. Record the screen at a readable size, with no other accounts or notifications visible. Speak or caption each step. About 3 minutes.

1. **The connection.** Show the App Dashboard briefly, then run the login the owner uses: in a terminal, `node scripts/advisor/meta-token.mjs`, open the printed Facebook Login URL, and show the permission dialog listing `instagram_manage_messages`, `instagram_manage_comments`, `instagram_basic`, `pages_show_list`, `pages_read_engagement` and `pages_manage_metadata`. Accept. Show the script printing the Page and Instagram account (cover the token on screen: blur it in the edit).
2. **The webhook subscription** (`pages_manage_metadata`). Open skippercast.com/admin → Health → Instagram inbox. Click **Subscribe webhooks** and show "Subscribed: messages,comments."
3. **A DM** (`instagram_manage_messages`, `instagram_basic`). On a phone signed into the tester account, open `@skippercast` and send "What's biting out of Morro Bay?". Show the reply arriving in the same thread. Send a second message with a fish photo and show the identification reply.
4. **Stop and erase.** From the tester account send "STOP", show the confirmation, send "START". Send "forget me", then "DELETE", and show the confirmation that everything was erased.
5. **A comment keyword** (`instagram_manage_comments`, `pages_read_engagement`). On the tester account, open a recent `@skippercast` post and comment `RIG`. Open the tester's DMs (Requests the first time) and show the one private reply with the guide link. Tap the link and show the page opening on skippercast.com.
6. **No reply to anything else.** Comment "Nice fish!" and show that no reply comes.
7. **The privacy notice.** Open skippercast.com/privacy.html#text-advisor and scroll through the Text Advisor section.

## 8. Submit

- [ ] In the App Review request, attach the screencast to each permission and paste the usage text.
- [ ] **Reviewer instructions** (paste): "Our webhook answers Instagram DMs and keyword comments for @skippercast. To test: from any Instagram account, send @skippercast a direct message such as 'What's biting out of Morro Bay?' and you will receive a reply within a minute. Comment RIG under any of our posts and you will receive one private reply with a link. Send STOP to stop replies and 'forget me' then 'DELETE' to erase your data. No login to our site is needed." If Meta asks for a test user, give the tester account's username and password in the secure field only.
- [ ] Submit. Meta reviews in days to weeks; answer its questions in the App Review inbox.

## 9. After approval: Live, then the switch

- [ ] App Dashboard → top bar → **App Mode: Live** (or Publish). It refuses if step 2 is incomplete.
- [ ] Check Health → Instagram inbox. Set the switch and deploy:
  ```bash
  gh variable set ADVISOR_INBOX_ENABLED --body true
  ```
  then **Actions → Deploy to Cloudflare → Run workflow** (action `deploy`).
- [ ] From an Instagram account that has **no** role on the app, DM `@skippercast` and comment `REPORT` on a post. Check the replies arrive and the D1 rows from step 5.
- [ ] Optional, later: public answers to question comments. They post the model's answer under the comment for everyone to see, so try it with the tester account first:
  ```bash
  gh variable set ADVISOR_INBOX_PUBLIC_REPLIES --body true
  ```
- [ ] Record the approval date and anything that differed from this runbook in [09 § As built (TA-S6)](../../plans/text-advisor/09-social.md) and the plan's status log.

## Turning it off

`gh variable set ADVISOR_INBOX_ENABLED --body false` and run the deploy workflow. The webhook keeps answering `200` to Meta (so Meta does not disable the subscription) and writes nothing. Nothing new is stored; messages already queued are still answered.
