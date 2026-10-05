# Runbook: rotate a secret

**Symptom:** a secret leaked or may have (committed, pasted into an issue or log, a laptop lost, a collaborator removed), a provider revoked it, it expired, or a scheduled rotation is due. Jobs failing with `could not verify CLOUDFLARE_API_TOKEN`, Wrangler `Authentication error`, a watchdog log `dispatch-failed-401`, or AI boat lookups answering 502 also point here.
**Severity:** SEV1 if a secret that can write data or spend money is known to be exposed; SEV3 for an expired or revoked secret; planned rotation is not an incident.
**Owner:** repository owner. Only the owner holds the Cloudflare, GitHub and Anthropic accounts.

## Inventory

| Secret | Stored in | Used by | Grants |
| --- | --- | --- | --- |
| `CLOUDFLARE_API_TOKEN` | GitHub Actions secret | `deploy-cloudflare.yml`, `live-conditions.yml`, `daily-data.yml`, `forecast-tiles.yml`, `seafloor.yml` (via `scripts/cloudflare_deploy.sh`, `scripts/publish_r2.py`, `src/skippercast/seafloor/publish.py`) | Workers, D1 and R2 edit on the account; its id and SHA-256 are also the R2 S3 key pair |
| `CLOUDFLARE_ACCOUNT_ID` | GitHub Actions secret | same | Not a credential; an identifier |
| `ANTHROPIC_API_KEY` | GitHub Actions secret → Worker secret (uploaded by `cloudflare_deploy.sh`) | `server/boat-lookup.ts` via `/api/boat/lookup` | Spends Anthropic credit |
| `WATCHDOG_GITHUB_TOKEN` | GitHub Actions secret → Worker secret `GITHUB_TOKEN` | `server/watchdog.ts` | Fine-grained token: Actions read and write on this repository only |
| `VAPID_PRIVATE_KEY` / `VAPID_PUBLIC_KEY` | `secrets/vapid.json` in the private backup bucket (`cloudflare_deploy.sh` generates it on the first deploy and reads it back on every later one), or GitHub Actions secrets of the same names, which take precedence → Worker secrets | `server/trips.ts` `deliver()`; `/api/session` returns the public key | Signs Web Push messages to subscribed devices |
| `EXTRA_ORIGINS` | GitHub Actions variable → Worker secret | `server/http.ts` `requireOrigin` (origins from `server/middleware/context.ts`) | Not a credential; adds allowed origins |

Text Advisor secrets ([threat model § 9](../../legal/threat-model.md#9-text-advisor); uploaded by `scripts/cloudflare_deploy.sh` only when set; `ADVISOR_*` names reach it as `SECRET_ADVISOR_*` so they are never copied into plain vars):

| Secret | Stored in | Used by | Grants | Rotate |
| --- | --- | --- | --- | --- |
| `ADVISOR_PHONE_KEY` | GitHub secret (`SECRET_ADVISOR_PHONE_KEY` to the deploy) → Worker secret | `server/advisor/contacts.ts` (HKDF subkeys: number hash, number encryption, upload and export link signatures), `outbound-guard.ts` `ipHash` | Reads every stored number; forges upload and export links | Only with the re-key script ([below](#advisor_phone_key-text-advisor)); on a leak at once |
| `ADVISOR_WEBHOOK_TOKEN` | GitHub secret (`SECRET_ADVISOR_WEBHOOK_TOKEN`) → Worker secret; BlueBubbles' webhook URL on the Mac | `server/routes/advisor.ts` inbound webhooks (path segment) | Posts texts as any contact | Every 90 days, when someone leaves the Cloudflare account, on a leak ([below](#advisor_webhook_token-text-advisor)) |
| `BLUEBUBBLES_PASSWORD` | GitHub secret → Worker secret; BlueBubbles server settings | `server/advisor/channels/bluebubbles.ts` (query string through the tunnel) | Sends and reads every conversation on the relay, with the Access token | Yearly, on a leak |
| `CF_ACCESS_CLIENT_ID`, `CF_ACCESS_CLIENT_SECRET` | GitHub secrets → Worker secrets; the Zero Trust service token | the same, as `CF-Access-Client-Id`/`-Secret` headers | Passes Access in front of the relay | Yearly (set the token's duration to 1 year, relay setup step 7.6), on a leak |
| `BLUEBUBBLES_URL` | GitHub secret → Worker secret | the same | Not a credential (the tunnel hostname) | When the hostname changes |
| `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_FROM` | GitHub secrets → Worker secrets (after a port) | `server/advisor/channels/twilio.ts` (sends; `X-Twilio-Signature` check) | Sends from the number; forges inbound webhooks with the path token | Yearly, on a leak ([below](#twilio_auth_token-text-advisor)) |
| `META_APP_SECRET` | GitHub secret → Worker secret | `server/advisor/social/inbox.ts` (`X-Hub-Signature-256`), `meta.ts` (`appsecret_proof`) | Forges Meta webhooks; with the Page token, calls the Graph API | On a leak ([below](#meta-secrets-text-advisor)) |
| `META_PAGE_TOKEN` | GitHub secret → Worker secret | `server/advisor/social/meta.ts`, `publish.ts`, `insights.ts` | Posts and reads DMs as SkipperCast; does not expire | Yearly, when anyone with Page access leaves, on a leak |
| `META_VERIFY_TOKEN` | GitHub secret → Worker secret; the Meta app's webhook settings | `GET /api/advisor/inbound/meta` handshake | Subscribes the webhook (not a data credential) | On a leak |
| `META_APP_ID`, `META_PAGE_ID`, `META_IG_USER_ID` | GitHub secrets → Worker secrets | `meta.ts`, `inbox.ts` | Identifiers, not credentials | — |
| `R2_ADVISOR_TOKEN` | GitHub secret, read by `advisor-media.yml` on the self-hosted runner | `scripts/advisor/media_job.py` (S3 keys derived from it) | Reads and replaces every advisor photo and video original | Yearly, when the runner machine changes hands, on a leak ([below](#r2_advisor_token-text-advisor)) |
| `CF_ANALYTICS_TOKEN` | GitHub secret → Worker secret (with `CLOUDFLARE_ACCOUNT_ID`) | `ops-report.yml`, the admin funnel (`server/advisor/admin/funnel.ts`) | Account Analytics: Read | Yearly, on a leak |
| `ANTHROPIC_API_KEY` | as above | also the advisor engine and Claude vision | Spends Anthropic credit | [above](#anthropic_api_key); the advisor's soft switch `ADVISOR_REPLIES_ENABLED=false` stops model calls without touching the key |
| `HERMES_VISION_URL`, `HERMES_VISION_TOKEN` | GitHub secrets → Worker secrets (TA-V2) | `server/advisor/vision/hermes.ts` | Sends photos to the owner's Hermes host | On a leak; set the same token on the Hermes host |

No secret exists for: the scheduler (GitHub OIDC; the policy is the public `deployments/production.json`, see `server/job-auth.ts`), the Actions `github.token` (issued per run), D1 and R2 bindings (granted by the Worker's configuration). Repository variables `CLOUDFLARE_SITE_URL` and, after PR #30, `FEEDS_PUBLIC_BASE` are not secrets.

## General order

- **Planned rotation or suspected leak:** create the new secret → install it everywhere → verify → revoke the old one. No downtime.
- **Confirmed leak of a secret that writes data or spends money:** revoke first, accept that the jobs using it fail until the new one is installed, then continue as above.
- After any leak, check the provider's audit log for use you don't recognise: Cloudflare (**Manage Account → Audit Log**), GitHub (**Settings → Security log** and the repository's **Actions** runs), Anthropic Console usage.
- A secret committed to git stays in history even after a revert. Rotate it; do not rely on rewriting history. `python3 scripts/check_repository.py` flags common credential shapes before commit.

Commands below assume the GitHub CLI (`gh`) authenticated as the owner, and:

```bash
W="npx --yes wrangler@4.142.0"
export CLOUDFLARE_API_TOKEN=... CLOUDFLARE_ACCOUNT_ID=...   # the token being installed, for Wrangler steps
```

`gh secret set NAME` and `wrangler secret put NAME` read the value from standard input, so it never lands in shell history when you paste it at the prompt.

## CLOUDFLARE_API_TOKEN

1. Cloudflare dashboard → **My Profile → API Tokens → Create Token** → template **Edit Cloudflare Workers**; add **Account · D1 · Edit** and **Account · Workers R2 Storage · Edit**; restrict to the SkipperCast account ([Cloudflare setup](../../cloudflare.md)).
2. Check it: `curl -fsS -H "Authorization: Bearer <new token>" https://api.cloudflare.com/client/v4/user/tokens/verify` → `"status":"active"`.
3. Install: `gh secret set CLOUDFLARE_API_TOKEN`.
4. Verify every consumer: `gh workflow run deploy-cloudflare.yml --ref main` (deploy) and `gh workflow run live-conditions.yml --ref main` (R2 publish); both must be green and the live run must log `R2 skippercast-feeds/conditions: ... uploaded`.
5. Revoke the old token in the dashboard (**API Tokens → ... → Delete**).

Until step 3, R2 publication fails; on `main` that is a warning and GitHub branches stay current (see [R2 outage](r2-outage.md) for catching up R2).

## ANTHROPIC_API_KEY

1. Emergency stop (spend or abuse): remove the Worker secret so `/api/boat/lookup` answers 503 "not configured", and the GitHub secret so the next deploy doesn't restore it:
   ```bash
   $W secret delete ANTHROPIC_API_KEY --name skippercast
   gh secret delete ANTHROPIC_API_KEY
   ```
   After PR #29 ([P0-08]) merges, setting the Worker variable `BOAT_LOOKUP_ENABLED` to `false` also stops lookups without touching the key.
2. Anthropic Console → **API Keys** → create a new key.
3. Install: `gh secret set ANTHROPIC_API_KEY`, then either run the deploy workflow (it uploads the secret) or `$W secret put ANTHROPIC_API_KEY --name skippercast`.
4. Verify: a signed-in boat lookup succeeds (not available on Cloudflare until sign-in exists; there, check that `$W secret list --name skippercast` lists the name).
5. Revoke the old key in the Console.

## WATCHDOG_GITHUB_TOKEN

1. GitHub → **Settings → Developer settings → Fine-grained tokens → Generate**: repository access *Only Grahammmm/skippercast*, permission **Actions: Read and write**, nothing else; set an expiry.
2. Check it: `curl -fsS -o /dev/null -w '%{http_code}\n' -H "Authorization: Bearer <new token>" https://api.github.com/repos/Grahammmm/skippercast/actions/workflows/live-conditions.yml` → `200`.
3. Install: `gh secret set WATCHDOG_GITHUB_TOKEN`, then run the deploy workflow, or `$W secret put GITHUB_TOKEN --name skippercast` (the Worker secret is named `GITHUB_TOKEN`).
4. Verify: `$W tail skippercast --format pretty --search "Live feed watchdog"` shows no `dispatch-failed-401` over the next stale period; `$W secret list --name skippercast` lists `GITHUB_TOKEN`.
5. Delete the old token in GitHub settings.

## VAPID key pair

Where the pair lives: the deploy script keeps it at `r2://skippercast-backups/secrets/vapid.json` (generated once by the first deploy that found none, read back by every deploy since) unless both `VAPID_PUBLIC_KEY` and `VAPID_PRIVATE_KEY` are set as GitHub Actions secrets, which win. A read that fails for any reason other than a missing object stops the deploy rather than generating a new pair over the stored one.

Rotate only if the private key leaked: every existing push subscription is bound to the old public key, so each person must turn notifications on again.

1. Either delete the stored object so the next deploy generates a fresh pair (`$W r2 object delete skippercast-backups/secrets/vapid.json --remote`, then run the deploy workflow and skip to step 3), or generate a pair yourself (Node 22; prints JSON with both values):
   ```bash
   node --input-type=module -e "const k=await crypto.subtle.generateKey({name:'ECDSA',namedCurve:'P-256'},true,['sign']);const b=u=>Buffer.from(u).toString('base64url');console.log(JSON.stringify({VAPID_PUBLIC_KEY:b(await crypto.subtle.exportKey('raw',k.publicKey)),VAPID_PRIVATE_KEY:(await crypto.subtle.exportKey('jwk',k.privateKey)).d}))"
   ```
   The public key is 87 characters and the private key 43, the formats `@block65/webcrypto-web-push` expects.
2. If you generated the pair yourself, set both as GitHub Actions secrets (`gh secret set VAPID_PUBLIC_KEY` and `gh secret set VAPID_PRIVATE_KEY`) and run the deploy workflow; the deploy uploads them to the Worker and the smoke test checks that `/api/session` serves the public key.
3. Old subscriptions now fail; deliveries are recorded as `failed` and alerts as `held`, which makes `scripts/check_saved_trips.py` fail the live job. Remove them in the database that holds them (`DELETE FROM subscriptions`; see [D1 restore](d1-restore.md) for running SQL) and tell users to re-enable notifications from the app. In-app assessments keep working without push.
4. Verify: `curl -fsS https://skippercast.com/api/session` returns the new `publicKey`; enabling notifications on a test device and saving a trip produces a delivered alert on the next check.

## ADVISOR_WEBHOOK_TOKEN (Text Advisor)

The BlueBubbles webhook (and the Twilio ones, after a port) carries this token in its URL path, because BlueBubbles cannot send a header or sign its requests ([threat model § 9.1](../../legal/threat-model.md#91-inbound-webhooks)). Our own logs never hold it (`redactPath` in `server/middleware/error.ts`, and the advisor's routes answer their own errors), but Cloudflare's **Workers Logs invocation log** records every request URL, so anyone with log access to the account can read it until the logs age out. Keep account membership minimal; set the repository variable `WORKERS_INVOCATION_LOGS=false` to stop the invocation log entirely (our own log lines stay; `scripts/wrangler_config.mjs`). Rotate it on a schedule (every 90 days), whenever someone leaves the Cloudflare account, and at once if it may have leaked: anyone who has it can post texts as any contact (§ 9.1).

Rotation drops the deliveries that arrive between the deploy and the BlueBubbles change (each answers `401`, and BlueBubbles is not known to retry), so do it at a quiet hour and keep the gap to a minute or two.

1. Make the new token: `openssl rand -base64 32 | tr '+/' '-_' | tr -d '='` (URL-safe, 43 characters).
2. Install: `gh secret set ADVISOR_WEBHOOK_TOKEN`, then upload it at once with `$W secret put ADVISOR_WEBHOOK_TOKEN --name skippercast` (a later deploy uploads the same value from the GitHub secret).
3. Straight away, on the Mac: **BlueBubbles → API & Webhooks**, edit the webhook's URL to `https://skippercast.com/api/advisor/inbound/bluebubbles/<new token>` and save. After a Twilio port, also change the messaging and status callback URLs in the Twilio console ([port to Twilio](advisor-port-to-twilio.md)).
4. Verify: text the advisor's number from your phone and get the reply; `$W tail skippercast --format pretty --search advisor_webhook_unauthorized` shows no new lines after step 3.
5. Catch up: open Messages on the Mac and look for texts received between steps 2 and 3; answer them by hand from the admin queue or ask the sender to text again.
6. The old token is now useless, including the copies in Workers Logs; nothing to revoke elsewhere.

## ADVISOR_PHONE_KEY (Text Advisor)

Every stored number is `phone_hash = HMAC(K_hash, number)` and `phone_enc = AES-GCM(K_enc, number)` with both keys derived from `ADVISOR_PHONE_KEY` (`server/advisor/contacts.ts`), and upload and export links are signed with a third subkey. Replacing the secret alone would make every contact unreachable and every returning number a stranger. Rotate it only with `scripts/advisor/rekey-phones.mjs`, which decrypts each number with the old key and writes the new hash and ciphertext for every contact in one D1 transaction.

What else changes: live upload and export links (24 hours) stop working (people text LINK or SEND ME MY DATA again); pending web phone-link codes (10 minutes) are cleared; the per-number and per-address counters start over (they are keyed by the old hashes and expire within 8 days).

1. Make the new key and keep the old one at hand (password manager): `openssl rand -base64 32`.
2. Dry run, from a checkout (Node 22.18+, Wrangler credentials for the account):
   ```bash
   read -rs OLD_ADVISOR_PHONE_KEY; export OLD_ADVISOR_PHONE_KEY
   read -rs NEW_ADVISOR_PHONE_KEY; export NEW_ADVISOR_PHONE_KEY
   node scripts/advisor/rekey-phones.mjs
   ```
   It must end `cannot read: 0`. A row it cannot read (decrypts with neither key) blocks the run: erase that contact from the admin contact page first.
3. At a quiet hour, so the gap between the next two steps is seconds: `node scripts/advisor/rekey-phones.mjs --apply`, then at once `$W secret put ADVISOR_PHONE_KEY --name skippercast` with the new key. A text that arrives in between is hashed with the old key and makes a second contact for that number.
4. `gh secret set ADVISOR_PHONE_KEY` (the new key), so the next deploy uploads the same value.
5. Run `node scripts/advisor/rekey-phones.mjs` again (dry run): it must report `contacts to re-key: 0`. A contact made during the gap shows as `duplicate of <id>`: erase it from the admin contact page (its one message is also in the original contact's channel on the relay).
6. Verify: text the advisor from your phone and get a reply in the same conversation (the admin contact page shows your earlier messages); `send me a link` returns a working upload link.
7. Delete the old key from wherever you kept it.

## TWILIO_AUTH_TOKEN (Text Advisor)

Only after a port ([port to Twilio](advisor-port-to-twilio.md)). Twilio console → **Account → API keys & tokens → Auth tokens**: create the secondary token, `gh secret set TWILIO_AUTH_TOKEN` and `$W secret put TWILIO_AUTH_TOKEN --name skippercast`, send a test text both ways (inbound requests are signed with the primary until you promote), then **Promote** the secondary to primary. The old token stops working at once; inbound requests signed with it answer `401` (`advisor_webhook_unauthorized`).

## Meta secrets (Text Advisor)

- `META_PAGE_TOKEN`: run `node scripts/advisor/meta-token.mjs` again ([09 § Setup](../../plans/text-advisor/09-social.md)) for a fresh never-expiring Page token, `gh secret set META_PAGE_TOKEN` and `$W secret put META_PAGE_TOKEN --name skippercast`, check **Admin → Health** shows Meta configured and the quota read works, then revoke the old one: Facebook **Settings → Business integrations** (remove and re-add the app) or change the password of the Facebook account that issued it, which invalidates its Page tokens.
- `META_APP_SECRET`: Meta app dashboard → **App settings → Basic → App secret → Reset**. The old secret stops at once: set the new one with `$W secret put META_APP_SECRET --name skippercast` straight away (webhooks fail their signature check and `appsecret_proof` calls fail until then), then `gh secret set META_APP_SECRET`.
- `META_VERIFY_TOKEN`: any new random string (`openssl rand -hex 24`); set it as the secret and in the app's **Webhooks** settings, then press **Verify and save** there.

## R2_ADVISOR_TOKEN (Text Advisor)

Cloudflare dashboard → **R2 → Manage R2 API tokens → Create API token**: **Object Read & Write**, scoped to the bucket `skippercast-advisor-media` only. `gh secret set R2_ADVISOR_TOKEN` with the token **value** (the media job derives the S3 key pair from it like `scripts/publish_r2.py`). Run **Actions → Advisor media → Run workflow**; it must log its work list and finish green. Then delete the old token in the R2 token list.

## BLUEBUBBLES_PASSWORD and the Access service token (Text Advisor)

- Password: BlueBubbles → **Settings → Server password**: set a new one (`openssl rand -base64 32`), then at once `$W secret put BLUEBUBBLES_PASSWORD --name skippercast` and `gh secret set BLUEBUBBLES_PASSWORD`. Sends fail (and are held, then retried by the cron) until the Worker has it.
- Service token: **Zero Trust → Access → Service credentials → Service Tokens → Create Service Token** (as in [relay setup step 7.6](advisor-relay-setup.md#7-expose-bluebubbles-through-a-named-cloudflare-tunnel-with-access); duration 1 year), add it to the relay application's Service Auth policy next to the old one, install both values (`$W secret put CF_ACCESS_CLIENT_ID`, `CF_ACCESS_CLIENT_SECRET`, and `gh secret set` each), run `node scripts/advisor/relay-check.mjs --no-send` with the new values, then remove the old token from the policy and revoke it.

## EXTRA_ORIGINS

Not secret. Change the repository variable (`gh variable set EXTRA_ORIGINS`) and run the deploy workflow. Each entry must match `https://[a-z0-9.-]+` or the Worker ignores it.

## Verify (any rotation)

- The workflows that use the secret are green on their next run.
- `python3 scripts/check_feed_freshness.py --max-age-hours 3` passes.
- The old secret is revoked at the provider, not only replaced.

## Rollback

A revoked secret cannot be restored. If the new secret is wrong, create another one; do not re-enable a leaked one.

## Escalate

Provider support (Cloudflare, GitHub, Anthropic) if the dashboard will not revoke a credential or the audit log shows use you can't explain. Unexplained use of a data-writing secret is SEV1.

## Postmortem

Required for any leak. Use the [postmortem template](../incident-response.md#postmortem-template).
